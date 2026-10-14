"""TG 机器人操作：通过 Telegram Bot 命令查询/操作面板（轮询模式）。

命令：
  /start /help          帮助
  /instances            全部租户实例列表（名称/状态/IP）
  /instance <关键词>    实例详情
  /snatch               抢机任务状态
  /traffic <关键词>     实例 24h 流量汇总
  /startvm|/stopvm|/rebootvm <关键词>   电源操作（需二次确认）
  /changeip <关键词>    发起换 IP 任务（需二次确认）

安全：仅响应白名单 chat_id（系统设置 tg_ops_chat_ids），token 复用通知渠道中
第一个启用的 Telegram 渠道。总开关：系统设置 tg_ops_enabled=1。
"""
import json
import logging
import threading
import time

import httpx

from ..db import models
from ..db.session import SessionLocal

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

_thread: threading.Thread | None = None
_stop = threading.Event()

HELP = """🤖 OCI 面板操作机器人

/instances - 实例列表
/instance <关键词> - 实例详情
/snatch - 抢机任务状态
/traffic <关键词> - 24h 流量汇总
/startvm|/stopvm|/rebootvm <关键词> - 电源操作
/changeip <关键词> - 换 IP
/help - 本帮助"""


def _get_setting(db, key: str, default: str = "") -> str:
    row = db.get(models.SystemSetting, key)
    return (row.value if row and row.value else default).strip()


def get_ops_config() -> dict:
    """读取运维机器人配置。"""
    db = SessionLocal()
    try:
        enabled = _get_setting(db, "tg_ops_enabled", "0") == "1"
        chat_ids = [c.strip() for c in _get_setting(db, "tg_ops_chat_ids").split(",") if c.strip()]
        token = ""
        cfg = (
            db.query(models.NotificationConfig)
            .filter(models.NotificationConfig.type == "telegram",
                    models.NotificationConfig.enabled.is_(True))
            .order_by(models.NotificationConfig.id)
            .first()
        )
        if cfg:
            try:
                token = (json.loads(cfg.config_json or {}).get("bot_token") or "").strip()
            except Exception:
                pass
        return {"enabled": enabled, "token": token, "chat_ids": chat_ids}
    finally:
        db.close()


def set_ops_config(enabled: bool, chat_ids: str) -> dict:
    db = SessionLocal()
    try:
        for key, val in (("tg_ops_enabled", "1" if enabled else "0"),
                         ("tg_ops_chat_ids", chat_ids.strip())):
            row = db.get(models.SystemSetting, key)
            if row is None:
                db.add(models.SystemSetting(key=key, value=val, is_secret=False))
            else:
                row.value = val
        db.commit()
    finally:
        db.close()
    restart()
    return get_ops_config()


def _api(token: str, method: str, **params):
    resp = httpx.post(_API.format(token=token, method=method), json=params, timeout=30)
    data = resp.json()
    if not data.get("ok"):
        log.warning("TG API %s 失败: %s", method, str(data)[:200])
    return data


def _send(token: str, chat_id: str, text: str, reply_markup: dict | None = None):
    params: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return _api(token, "sendMessage", **params)


def _find_instances(keyword: str) -> list[dict]:
    """按名称关键词跨租户查找实例。返回 [{tenant_id, tenant_name, id, display_name, ...}]。"""
    from . import instance_service

    db = SessionLocal()
    try:
        tenants = db.query(models.Tenant).all()
        out = []
        for t in tenants:
            db.expunge(t)
        for t in tenants:
            try:
                items = instance_service.list_instances(t)
            except Exception as exc:
                log.warning("TG 查询租户 %s 实例失败: %s", t.name, exc)
                continue
            for it in items:
                name = it.get("display_name") or ""
                if keyword.lower() in name.lower() or keyword.lower() in it.get("id", "").lower():
                    out.append({"tenant_id": t.id, "tenant_name": t.name, **it})
        return out
    finally:
        db.close()


def _confirm_kb(action: str, tenant_id: int, instance_id: str) -> dict:
    return {
        "inline_keyboard": [[
            {"text": "✅ 确认", "callback_data": f"confirm:{action}:{tenant_id}:{instance_id}"},
            {"text": "❌ 取消", "callback_data": "cancel"},
        ]]
    }


def _handle_message(token: str, chat_id: str, text: str):
    parts = text.strip().split(None, 1)
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("start", "help"):
        _send(token, chat_id, HELP)
    elif cmd == "instances":
        items = _find_instances("")
        if not items:
            _send(token, chat_id, "暂无实例（或租户查询失败）")
            return
        lines = [f"• {i['display_name']} [{i['lifecycle_state']}] {i.get('public_ip') or '-'}"
                 for i in items[:30]]
        _send(token, chat_id, "<b>实例列表</b>\n" + "\n".join(lines))
    elif cmd == "instance":
        if not arg:
            _send(token, chat_id, "用法：/instance <关键词>")
            return
        items = _find_instances(arg)
        if not items:
            _send(token, chat_id, "未找到匹配的实例")
            return
        i = items[0]
        extra = f"\n共匹配 {len(items)} 台，仅显示第一台" if len(items) > 1 else ""
        _send(token, chat_id,
              f"<b>{i['display_name']}</b>{extra}\n租户：{i['tenant_name']}\n"
              f"状态：{i['lifecycle_state']}\nShape：{i.get('shape')}\n"
              f"配置：{i.get('ocpus')}C / {i.get('memory_in_gbs')}G\n"
              f"公网 IP：{i.get('public_ip') or '-'}\n私网 IP：{i.get('private_ip') or '-'}")
    elif cmd == "snatch":
        db = SessionLocal()
        try:
            tasks = db.query(models.SnatchTask).order_by(models.SnatchTask.id.desc()).limit(10).all()
            if not tasks:
                _send(token, chat_id, "暂无抢机任务")
                return
            lines = [f"• {t.name} [{t.status}] 尝试 {t.attempts} 次" for t in tasks]
            _send(token, chat_id, "<b>抢机任务</b>\n" + "\n".join(lines))
        finally:
            db.close()
    elif cmd == "traffic":
        if not arg:
            _send(token, chat_id, "用法：/traffic <关键词>")
            return
        items = _find_instances(arg)
        if not items:
            _send(token, chat_id, "未找到匹配的实例")
            return
        i = items[0]
        db = SessionLocal()
        try:
            t = db.get(models.Tenant, i["tenant_id"])
            db.expunge(t)
        finally:
            db.close()
        try:
            from . import monitoring_service

            vnic_id = monitoring_service.get_primary_vnic_id(t, i["id"])
            points = monitoring_service.query_vnic_traffic(t, vnic_id, 24, "1h")
            if not points:
                _send(token, chat_id, f"{i['display_name']}：暂无流量数据")
                return
            ib = sum(p["inbound_mbps"] for p in points) / 8 / 3600 * 24  # Mbps均值 -> GB
            ob = sum(p["outbound_mbps"] for p in points) / 8 / 3600 * 24
            peak = max(max(p["inbound_mbps"], p["outbound_mbps"]) for p in points)
            _send(token, chat_id,
                  f"<b>{i['display_name']} 24h 流量</b>\n入站约 {ib:.2f} GB\n"
                  f"出站约 {ob:.2f} GB\n峰值 {peak:.1f} Mbps")
        except Exception as exc:
            _send(token, chat_id, f"流量查询失败：{str(exc)[:150]}")
    elif cmd in ("startvm", "stopvm", "rebootvm"):
        if not arg:
            _send(token, chat_id, f"用法：/{cmd} <关键词>")
            return
        items = _find_instances(arg)
        if not items:
            _send(token, chat_id, "未找到匹配的实例")
            return
        i = items[0]
        op = {"startvm": "开机", "stopvm": "关机", "rebootvm": "重启"}[cmd]
        _send(token, chat_id,
              f"确认为 <b>{i['display_name']}</b> 执行「{op}」？",
              reply_markup=_confirm_kb(cmd, i["tenant_id"], i["id"]))
    elif cmd == "changeip":
        if not arg:
            _send(token, chat_id, "用法：/changeip <关键词>")
            return
        items = _find_instances(arg)
        if not items:
            _send(token, chat_id, "未找到匹配的实例")
            return
        i = items[0]
        _send(token, chat_id,
              f"确认为 <b>{i['display_name']}</b>（当前 IP {i.get('public_ip') or '-'}）执行「换 IP」？",
              reply_markup=_confirm_kb("changeip", i["tenant_id"], i["id"]))
    else:
        _send(token, chat_id, "未知命令，/help 查看帮助")


def _handle_callback(token: str, cb):
    data = (cb.get("data") or "")
    chat_id = str(cb["message"]["chat"]["id"])
    cb_id = cb["id"]
    _api(token, "answerCallbackQuery", callback_query_id=cb_id)
    if data == "cancel":
        _send(token, chat_id, "已取消")
        return
    try:
        _, action, tenant_id_s, instance_id = data.split(":", 3)
        tenant_id = int(tenant_id_s)
    except Exception:
        _send(token, chat_id, "回调参数无效")
        return
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
        if action in ("startvm", "stopvm", "rebootvm"):
            from . import instance_service

            op = {"startvm": "start", "stopvm": "stop", "rebootvm": "reboot"}[action]
            instance_service.power_instance(tenant, instance_id, op)
            _send(token, chat_id, f"已下发「{op}」操作")
            _audit_log(db, f"tg.{op}", f"TG 机器人对实例 {instance_id} 执行 {op}")
        elif action == "changeip":
            task = models.IpTask(tenant_id=tenant_id, instance_id=instance_id,
                                 preferred_cidrs="[]", update_dns=False,
                                 max_retries=3, status="running")
            db.add(task)
            db.commit()
            _send(token, chat_id, f"已创建换 IP 任务（#{task.id}），后台执行中")
            _audit_log(db, "tg.change_ip", f"TG 机器人对实例 {instance_id} 发起换 IP")
    except Exception as exc:
        _send(token, chat_id, f"执行失败：{str(exc)[:200]}")
    finally:
        db.close()


def _audit_log(db, action: str, detail: str):
    try:
        from ..core.audit import write_log

        write_log(db, None, action, detail)
    except Exception:
        pass


def _loop():
    log.info("TG 运维机器人轮询线程启动")
    offset = 0
    while not _stop.is_set():
        cfg = get_ops_config()
        if not cfg["enabled"] or not cfg["token"]:
            time.sleep(10)
            continue
        token, allow = cfg["token"], set(cfg["chat_ids"])
        try:
            resp = httpx.post(
                _API.format(token=token, method="getUpdates"),
                json={"offset": offset, "timeout": 25, "allowed_updates": ["message", "callback_query"]},
                timeout=35,
            )
            data = resp.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for upd in data.get("result", []):
                offset = max(offset, upd["update_id"] + 1)
                if "message" in upd:
                    m = upd["message"]
                    chat_id = str(m["chat"]["id"])
                    text = (m.get("text") or "").strip()
                    if not text.startswith("/"):
                        continue
                    if allow and chat_id not in allow:
                        _send(token, chat_id, "⛔ 未授权的 chat，命令已忽略")
                        continue
                    _handle_message(token, chat_id, text)
                elif "callback_query" in upd:
                    cb = upd["callback_query"]
                    chat_id = str(cb["message"]["chat"]["id"])
                    if allow and chat_id not in allow:
                        continue
                    _handle_callback(token, cb)
        except Exception as exc:
            log.warning("TG 轮询异常: %s", exc)
            time.sleep(5)
    log.info("TG 运维机器人轮询线程停止")


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="tg-ops-bot")
    _thread.start()


def restart():
    stop()
    time.sleep(0.5)
    start()


def stop():
    _stop.set()
