"""通知渠道服务：Telegram / 邮件。

设计：
- send_to_all(title, body)：聚合所有 enabled 渠道发送，单个渠道失败不影响其他
- 函数内部自行创建 DB session（SessionLocal），可在 worker、定时任务等
  无请求上下文的地方调用；异步上下文中请用 asyncio.to_thread 包裹
- Telegram：httpx POST Bot API；Email：smtplib 纯文本邮件
"""
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate

import httpx

from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

TELEGRAM_TIMEOUT_SEC = 15
SMTP_TIMEOUT_SEC = 20

# 需要脱敏的敏感字段
SENSITIVE_FIELDS = {"bot_token", "smtp_pass"}


def mask_value(value: str) -> str:
    """只保留前 4 位，其余打码。"""
    if not value:
        return ""
    return value[:4] + "****" if len(value) > 4 else "****"


def mask_config(cfg: dict) -> dict:
    """返回脱敏后的配置副本（用于列表/详情输出）。"""
    return {k: (mask_value(str(v)) if k in SENSITIVE_FIELDS else v) for k, v in cfg.items()}


def parse_config(raw: str | None) -> dict:
    try:
        return json.loads(raw or "{}") or {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_enabled() -> list[tuple[models.NotificationConfig, dict]]:
    db = SessionLocal()
    try:
        rows = (
            db.query(models.NotificationConfig)
            .filter(models.NotificationConfig.enabled.is_(True))
            .order_by(models.NotificationConfig.id)
            .all()
        )
        return [(r, parse_config(r.config_json)) for r in rows]
    finally:
        db.close()


def send_telegram(cfg: dict, title: str, body: str) -> tuple[bool, str]:
    """发送 Telegram 消息。返回 (是否成功, 说明)。"""
    token = (cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    if not token or not chat_id:
        return False, "配置缺失：bot_token / chat_id"
    text = f"<b>{title}</b>\n{body}"
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=TELEGRAM_TIMEOUT_SEC,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, "发送成功"
        return False, f"Telegram API 返回 {resp.status_code}：{resp.text[:200]}"
    except Exception as exc:
        return False, f"发送异常：{exc}"


def send_email(cfg: dict, title: str, body: str) -> tuple[bool, str]:
    """发送邮件（纯文本）。返回 (是否成功, 说明)。"""
    host = (cfg.get("smtp_host") or "").strip()
    port = int(cfg.get("smtp_port") or 587)
    user = (cfg.get("smtp_user") or "").strip()
    password = cfg.get("smtp_pass") or ""
    from_addr = (cfg.get("from_addr") or user).strip()
    to_addrs = cfg.get("to_addrs") or []
    use_tls = bool(cfg.get("use_tls", True))
    if not host or not to_addrs:
        return False, "配置缺失：smtp_host / to_addrs"
    if isinstance(to_addrs, str):
        to_addrs = [to_addrs]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = title
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg["Date"] = formatdate(localtime=True)
    try:
        if use_tls and port == 465:
            smtp: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT_SEC)
        else:
            smtp = smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT_SEC)
        with smtp:
            if use_tls and port != 465:
                smtp.starttls()
            if user:
                smtp.login(user, password)
            smtp.sendmail(from_addr, to_addrs, msg.as_string())
        return True, f"已发送至 {len(to_addrs)} 个收件人"
    except Exception as exc:
        return False, f"发送异常：{exc}"


_SENDERS = {"telegram": send_telegram, "email": send_email}


def send_to_one(cfg_obj: models.NotificationConfig, cfg: dict, title: str, body: str) -> dict:
    """向单个渠道发送，返回结构化结果。"""
    sender = _SENDERS.get(cfg_obj.type)
    if sender is None:
        result = {"ok": False, "msg": f"不支持的渠道类型：{cfg_obj.type}"}
    else:
        try:
            ok_flag, msg = sender(cfg, title, body)
            result = {"ok": ok_flag, "msg": msg}
        except Exception as exc:  # 最后一道防线，保证不抛异常
            log.exception("通知渠道 %s 发送异常", cfg_obj.name)
            result = {"ok": False, "msg": f"未知异常：{exc}"}
    return {"id": cfg_obj.id, "name": cfg_obj.name, "type": cfg_obj.type, **result}


def send_to_all(title: str, body: str) -> dict:
    """向所有启用的通知渠道发送。

    返回示例：
    {"sent": 2, "failed": 0,
     "results": [{"id":1,"name":"运维群","type":"telegram","ok":True,"msg":"发送成功"}, ...]}
    """
    results = [send_to_one(obj, cfg, title, body) for obj, cfg in _load_enabled()]
    ok_count = sum(1 for r in results if r["ok"])
    return {"sent": ok_count, "failed": len(results) - ok_count, "results": results}
