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
from . import tg_menu

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

_thread: threading.Thread | None = None
_stop = threading.Event()

HELP = """🤖 zy-panel 操作机器人

/start - 打开按钮菜单（不用记命令）
/instances - 实例列表
/instance <关键词> - 实例详情
/snatch - 抢机任务状态
/traffic <关键词> - 24h 流量汇总
/startvm|/stopvm|/rebootvm <关键词> - 电源操作
/changeip <关键词> - 换 IP
/ssh <命令> - 在已连接的实例上执行命令（先从菜单 SSH 管理连接）
/exit - 退出当前输入（AI 聊天/填表）
/help - 本帮助

菜单里还有：创建实例、引导卷、任务启停、一键测活、资源监控、
日志查询、AI 聊天、MFA、VNC、备份恢复、IP 黑名单、防御模式。"""

# 输入框左侧 ☰ 菜单按钮里的命令列表：轮询线程启动时调 setMyCommands 注册一次
BOT_COMMANDS = [
    {"command": "start", "description": "打开主菜单"},
    {"command": "instances", "description": "查看全部实例列表"},
    {"command": "instance", "description": "查看实例详情（/instance 关键词）"},
    {"command": "snatch", "description": "查看抢机任务"},
    {"command": "traffic", "description": "查看实例 24h 流量"},
    {"command": "startvm", "description": "开机（/startvm 关键词）"},
    {"command": "stopvm", "description": "关机（/stopvm 关键词）"},
    {"command": "rebootvm", "description": "重启（/rebootvm 关键词）"},
    {"command": "changeip", "description": "更换公网 IP（/changeip 关键词）"},
    {"command": "ssh", "description": "在实例上执行命令（/ssh 命令）"},
    {"command": "exit", "description": "退出当前输入"},
    {"command": "help", "description": "查看帮助"},
]

_commands_set_token: str | None = None


def _set_bot_commands(token: str) -> None:
    """向 Telegram 注册命令列表，客户端输入框左侧出现 ☰ 菜单按钮。
    同一 token 只注册一次；失败只记日志，不影响轮询。"""
    global _commands_set_token
    if _commands_set_token == token:
        return
    try:
        resp = httpx.post(
            _API.format(token=token, method="setMyCommands"),
            json={"commands": BOT_COMMANDS},
            timeout=15,
        )
        data = resp.json()
        if data.get("ok"):
            _commands_set_token = token
            log.info("TG 菜单命令已注册（%d 条）", len(BOT_COMMANDS))
        else:
            log.warning("TG setMyCommands 失败: %s", data)
    except Exception as exc:
        log.warning("TG setMyCommands 异常: %s", exc)


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


def _confirm_kb(chat_id: str, action: str, tenant_id: int, instance_id: str) -> dict:
    # 回调数据限 64 字节，实例 OCID 不直接进回调，改用短引用
    ref = tg_menu._put_ref(chat_id, {"tenant_id": tenant_id, "instance_id": instance_id})
    return {
        "inline_keyboard": [[
            {"text": "✅ 确认", "callback_data": f"cf:{action}:{ref}"},
            {"text": "❌ 取消", "callback_data": "cancel"},
        ]]
    }


def _handle_message(token: str, chat_id: str, text: str):
    # 菜单侧先消费：/ssh、/exit、AI 聊天与各填表输入
    if tg_menu.handle_text(token, chat_id, text.strip()):
        return
    parts = text.strip().split(None, 1)
    cmd = parts[0].lstrip("/").split("@")[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "start":
        tg_menu.show_menu(token, chat_id)
    elif cmd == "help":
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
              reply_markup=_confirm_kb(chat_id, cmd, i["tenant_id"], i["id"]))
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
              reply_markup=_confirm_kb(chat_id, "changeip", i["tenant_id"], i["id"]))
    else:
        _send(token, chat_id, "未知命令，/help 查看帮助")


def _handle_callback(token: str, cb):
    chat_id = str(cb["message"]["chat"]["id"])
    # 菜单回调优先处理
    if tg_menu.handle_callback(token, chat_id, cb):
        return
    # 兼容旧版确认按钮（confirm:action:tenant_id:instance_id）
    data = (cb.get("data") or "")
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
    tg_menu.execute_confirm(token, chat_id, action,
                            {"tenant_id": tenant_id, "instance_id": instance_id})


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
        _set_bot_commands(token)
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
                    if allow and chat_id not in allow:
                        if m.get("text"):
                            _send(token, chat_id, "⛔ 未授权的 chat，命令已忽略")
                        continue
                    if "document" in m:
                        tg_menu.handle_document(token, chat_id, m["document"])
                        continue
                    text = (m.get("text") or "").strip()
                    if not text:
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
