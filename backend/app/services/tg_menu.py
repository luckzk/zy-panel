"""TG 机器人菜单版操作：/start 内联菜单 + 功能入口（对标 Y 探长 oci-helper）。

在 tg_ops_bot 的文本命令之外，提供点按钮操作的菜单：
  配置列表 / 任务管理 / 一键测活 / 流量统计 / 资源监控 / 日志查询 /
  AI 聊天 / SSH 管理 / 版本信息 / MFA 管理 / VNC 配置 / 备份恢复 /
  IP 黑名单 / 防御模式 / 创建实例 / 引导卷管理

说明：
- Telegram 回调数据有 64 字节上限，实例 OCID / 任务 ID 之外的长 ID
  一律不进回调，改用按 chat 维度的短引用（REFS）映射。
- 防御模式开启时，所有写操作（电源/终止/换 IP/创建/任务启停/备份恢复/
  SSH 执行/MFA 改动/IP 黑名单改动）一律拒绝，只读查询不受影响。
- IP 黑名单与防御模式管的是面板登录（与 Y 探长一致）：黑名单 IP 拒绝
  登录，防御模式开启后拒绝一切登录；开关只能从 TG 操作。
"""
import asyncio
import html
import io
import ipaddress
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime

import httpx
import paramiko
import pyotp

from ..db import models
from ..db.session import SessionLocal
from . import backup_service, inspection_service, instance_service, meta_service
from . import monitoring_service, update_service, volume_service
from . import oci_factory
from ..workers import snatch_worker

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"

# ---- 设置键 ----
AI_KEY = "ai_chat_api_key"
AI_BASE = "ai_chat_base_url"
AI_MODEL = "ai_chat_model"
VNC_URL = "vnc_url"
IPBL_KEY = "security_ip_blacklist"
DEFENSE_KEY = "security_defense_mode"

AI_DEFAULT_BASE = "https://api.siliconflow.cn/v1"
AI_DEFAULT_MODEL = "Qwen/Qwen3-8B"
AI_MODELS = [
    ("deepseek-ai/DeepSeek-R1-0528-Qwen3-8B", "DeepSeek-R1 推理"),
    ("Qwen/Qwen3-8B", "Qwen3-8B"),
    ("THUDM/GLM-Z1-9B-0414", "GLM-Z1-9B 推理"),
    ("Qwen/Qwen2.5-7B-Instruct", "Qwen2.5-7B"),
]
AI_MODEL_NAMES = dict(AI_MODELS)

# 创建实例可选方案：(key, 显示名, shape, ocpus, memory_gbs)
CREATE_PLANS = [
    ("a1-4c", "A1.Flex 4C / 24G", "VM.Standard.A1.Flex", 4, 24),
    ("a1-1c", "A1.Flex 1C / 6G", "VM.Standard.A1.Flex", 1, 6),
    ("e2m", "E2.1.Micro 1C / 1G", "VM.Standard.E2.1.Micro", None, None),
]
PLAN_MAP = {p[0]: p for p in CREATE_PLANS}

MAIN_TEXT = """🤖 <b>zy-panel 操作菜单</b>
不用登录网页，在这里点按钮就能操作。"""

# ---- 会话与短引用（内存态，重启丢失不影响使用） ----
SESSIONS: dict[str, dict] = {}
REFS: dict[str, dict[str, dict]] = {}
_REF_COUNTER = [0]


def _session(chat_id: str) -> dict:
    sess = SESSIONS.setdefault(chat_id, {"awaiting": None, "ctx": {}, "ai_history": [], "ssh": None})
    return sess


def _put_ref(chat_id: str, payload: dict) -> str:
    """把长 ID 等数据存成短引用，回调里只传引用。"""
    _REF_COUNTER[0] += 1
    ref = f"{_REF_COUNTER[0]:x}"
    bucket = REFS.setdefault(chat_id, {})
    if len(bucket) > 100:
        bucket.pop(next(iter(bucket)))
    bucket[ref] = payload
    return ref


def _get_ref(chat_id: str, ref: str) -> dict | None:
    return REFS.get(chat_id, {}).get(ref)


# ---- 设置读写（复用 update_service 的 Fernet 体系） ----
def _setting(key: str, default: str = "") -> str:
    return update_service._get_setting(key, default)


def _set_setting(key: str, value: str, secret: bool = False) -> None:
    update_service._set_setting(key, value, secret=secret)


def get_ai_config() -> dict:
    """AI 聊天配置：api_key（Fernet 加密存库）、base_url、model。"""
    cipher = _setting(AI_KEY)
    key = ""
    if cipher:
        try:
            key = update_service._get_fernet().decrypt(cipher.encode()).decode()
        except Exception:
            log.warning("AI API Key 解密失败，可能 FERNET_KEY 已更换")
    return {
        "api_key": key,
        "has_key": bool(key),
        "base_url": _setting(AI_BASE, AI_DEFAULT_BASE) or AI_DEFAULT_BASE,
        "model": _setting(AI_MODEL, AI_DEFAULT_MODEL) or AI_DEFAULT_MODEL,
    }


def set_ai_config(api_key: str = "", base_url: str = "", model: str = "") -> dict:
    if api_key:
        _set_setting(AI_KEY, api_key.strip(), secret=True)
    if base_url:
        _set_setting(AI_BASE, base_url.strip())
    if model:
        _set_setting(AI_MODEL, model.strip())
    return get_ai_config()


def _defense_on() -> bool:
    return _setting(DEFENSE_KEY, "0") == "1"


def _ip_blacklist() -> list[str]:
    try:
        v = json.loads(_setting(IPBL_KEY, "[]"))
        return [str(x) for x in v if isinstance(v, list)] if isinstance(v, list) else []
    except Exception:
        return []


def _save_ip_blacklist(entries: list[str]) -> None:
    _set_setting(IPBL_KEY, json.dumps(entries, ensure_ascii=False))


def ip_is_blacklisted(ip: str) -> bool:
    """登录拦截用：IP 是否在黑名单（含 CIDR 段匹配）。"""
    ip = (ip or "").strip()
    if not ip:
        return False
    for entry in _ip_blacklist():
        try:
            net = ipaddress.ip_network(entry, strict=False)
            if ipaddress.ip_address(ip) in net:
                return True
        except ValueError:
            if ip == entry:
                return True
    return False


# ---- Telegram API ----
def _tg_api(token: str, method: str, **params):
    try:
        resp = httpx.post(_API.format(token=token, method=method), json=params, timeout=30)
        data = resp.json()
        if not data.get("ok"):
            log.warning("TG API %s 失败: %s", method, str(data)[:200])
        return data
    except Exception as exc:
        log.warning("TG API %s 异常: %s", method, exc)
        return {"ok": False}


def _send(token: str, chat_id: str, text: str, reply_markup: dict | None = None):
    params: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return _tg_api(token, "sendMessage", **params)


def _edit(token: str, chat_id: str, message_id: int, text: str, reply_markup: dict | None = None):
    params: dict = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    r = _tg_api(token, "editMessageText", **params)
    if not r.get("ok"):
        _send(token, chat_id, text, reply_markup)
    return r


def _answer(token: str, cb_id: str, text: str = ""):
    return _tg_api(token, "answerCallbackQuery", callback_query_id=cb_id, text=text or "")


def _send_document(token: str, chat_id: str, filename: str, data: bytes, caption: str = ""):
    try:
        resp = httpx.post(
            _API.format(token=token, method="sendDocument"),
            data={"chat_id": chat_id, "caption": caption or ""},
            files={"document": (filename, data)},
            timeout=60,
        )
        return resp.json()
    except Exception as exc:
        log.warning("TG sendDocument 异常: %s", exc)
        return {"ok": False}


def _download_file(token: str, file_id: str) -> bytes | None:
    r = _tg_api(token, "getFile", file_id=file_id)
    path = (r.get("result") or {}).get("file_path")
    if not path:
        return None
    try:
        resp = httpx.get(f"https://api.telegram.org/file/bot{token}/{path}", timeout=60)
        return resp.content if resp.status_code == 200 else None
    except Exception as exc:
        log.warning("TG 文件下载异常: %s", exc)
        return None


def _audit(action: str, detail: str) -> None:
    db = SessionLocal()
    try:
        from ..core.audit import write_log

        write_log(db, None, action, detail)
    except Exception:
        pass
    finally:
        db.close()


def _esc(s: object) -> str:
    return html.escape(str(s if s is not None else ""))


def _kb(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": c} for t, c in row] for row in rows]}


def _main_kb() -> dict:
    return _kb([
        [("🔧 配置列表", "cfg"), ("📃 任务管理", "tasks"), ("💓 一键测活", "alive")],
        [("🌐 流量统计", "traffic"), ("📊 资源监控", "metrics"), ("📋 日志查询", "logs")],
        [("🤖 AI 聊天", "ai"), ("🔌 SSH 管理", "ssh"), ("🏷️ 版本信息", "version")],
        [("🔐 MFA 管理", "mfa"), ("🖥️ VNC 配置", "vnc"), ("💾 备份恢复", "backup")],
        [("🚫 IP 黑名单", "ipbl"), ("🛡️ 防御模式", "defense")],
        [("➕ 创建实例", "create")],
        [("❌ 关闭窗口", "close")],
    ])


def _back_kb() -> dict:
    return _kb([[("◀️ 返回主菜单", "menu")]])


def show_menu(token: str, chat_id: str) -> None:
    _session(chat_id)["awaiting"] = None
    _send(token, chat_id, MAIN_TEXT, _main_kb())


def _write_blocked(token: str, chat_id: str) -> bool:
    """防御模式开启时拦截写操作。返回 True 表示已拦截。"""
    if _defense_on():
        _send(token, chat_id, "🛡️ 防御模式已开启，写操作已冻结（只能从 TG 关闭防御模式）。")
        return True
    return False


def _oci_tenants() -> list:
    db = SessionLocal()
    try:
        tenants = db.query(models.Tenant).filter(models.Tenant.provider == "oci").order_by(models.Tenant.id).all()
        for t in tenants:
            db.expunge(t)
        return tenants
    finally:
        db.close()


def _tenant_kb(action_prefix: str, tenants: list) -> dict:
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for t in tenants:
        # tenant_id 是小整数，可直接进回调
        row.append((f"{t.name}", f"{action_prefix}:{t.id}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("◀️ 返回主菜单", "menu")])
    return _kb(rows)


# ================= 实例导航与操作 =================

def _tenant_pick(token: str, chat_id: str, message_id: int | None, prefix: str, title: str) -> None:
    tenants = _oci_tenants()
    text = f"{title}\n" + ("请选择租户：" if tenants else "暂无 OCI 租户")
    kb = _tenant_kb(prefix, tenants) if tenants else _back_kb()
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _instance_list(token: str, chat_id: str, message_id: int | None, tenant_id: int, prefix: str = "inst") -> None:
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        items = instance_service.list_instances(tenant)
    except Exception as exc:
        _send(token, chat_id, f"查询实例失败：{_esc(str(exc))[:150]}")
        return
    if not items:
        _send(token, chat_id, f"租户 {_esc(tenant.name)} 下暂无实例")
        return
    sess = _session(chat_id)
    sess["ctx"]["inst_list"] = [{"tenant_id": tenant.id, "tenant_name": tenant.name, **it} for it in items[:10]]
    # 实例名常很长且前缀相同：每行只放一个按钮，名字放到 30 字，避免截断后长得一样
    rows: list[list[tuple[str, str]]] = []
    for idx, it in enumerate(sess["ctx"]["inst_list"]):
        state = (it.get("lifecycle_state") or "")
        emoji = "🟢" if state == "RUNNING" else "🔴" if state in ("STOPPED", "STOPPING") else "🟡"
        name = (it.get("display_name") or it.get("id", ""))[:30]
        ref = _put_ref(chat_id, {"tenant_id": tenant.id, "idx": idx})
        rows.append([(f"{emoji} {name}", f"{prefix}:{ref}")])
    if len(items) > 10:
        rows.append([("…", "noop")])
    rows.append([("◀️ 返回主菜单", "menu")])
    text = f"<b>{_esc(tenant.name)}</b> 实例列表（{len(items)} 台）"
    if message_id:
        _edit(token, chat_id, message_id, text, _kb(rows))
    else:
        _send(token, chat_id, text, _kb(rows))


def _instance_detail(token: str, chat_id: str, message_id: int | None, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    if not payload:
        _send(token, chat_id, "该按钮已过期，请重新打开菜单")
        return
    inst = _session(chat_id)["ctx"].get("inst_list", [])[payload["idx"]] if payload.get("idx") is not None else None
    if not inst:
        _send(token, chat_id, "实例信息已过期，请重新打开菜单")
        return
    text = (
        f"<b>{_esc(inst.get('display_name'))}</b>\n"
        f"租户：{_esc(inst.get('tenant_name'))}\n"
        f"状态：{_esc(inst.get('lifecycle_state'))}\n"
        f"Shape：{_esc(inst.get('shape'))}\n"
        f"配置：{_esc(inst.get('ocpus'))}C / {_esc(inst.get('memory_in_gbs'))}G\n"
        f"公网 IP：{_esc(inst.get('public_ip') or '-')}\n"
        f"私网 IP：{_esc(inst.get('private_ip') or '-')}"
    )
    kb = _kb([
        [("⚡ 开机", f"iop:start:{ref}"), ("⏸ 关机", f"iop:stop:{ref}"), ("🔄 重启", f"iop:reboot:{ref}")],
        [("🔀 换 IP", f"iop:changeip:{ref}"), ("📊 流量", f"iop:traffic:{ref}"), ("💾 引导卷", f"iop:bootvol:{ref}")],
        [("🗑 终止实例", f"iop:terminate:{ref}")],
        [("◀️ 返回主菜单", "menu")],
    ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _instance_traffic(token: str, chat_id: str, inst: dict) -> None:
    db = SessionLocal()
    try:
        t = db.get(models.Tenant, inst["tenant_id"])
        db.expunge(t)
    finally:
        db.close()
    try:
        vnic_id = monitoring_service.get_primary_vnic_id(t, inst["id"])
        points = monitoring_service.query_vnic_traffic(t, vnic_id, 24, "1h")
        if not points:
            _send(token, chat_id, f"{_esc(inst.get('display_name'))}：暂无流量数据")
            return
        ib = sum(p["inbound_mbps"] for p in points) / 8 / 3600 * 24
        ob = sum(p["outbound_mbps"] for p in points) / 8 / 3600 * 24
        peak = max(max(p["inbound_mbps"], p["outbound_mbps"]) for p in points)
        _send(token, chat_id,
              f"<b>{_esc(inst.get('display_name'))} 24h 流量</b>\n入站约 {ib:.2f} GB\n"
              f"出站约 {ob:.2f} GB\n峰值 {peak:.1f} Mbps")
    except Exception as exc:
        _send(token, chat_id, f"流量查询失败：{_esc(str(exc))[:150]}")


def _instance_op(token: str, chat_id: str, message_id: int | None, op: str, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    if not payload:
        _send(token, chat_id, "该按钮已过期，请重新打开菜单")
        return
    insts = _session(chat_id)["ctx"].get("inst_list", [])
    inst = insts[payload["idx"]] if payload.get("idx") is not None and payload["idx"] < len(insts) else None
    if not inst:
        _send(token, chat_id, "实例信息已过期，请重新打开菜单")
        return
    name = inst.get("display_name") or inst.get("id", "")
    if op == "traffic":
        _instance_traffic(token, chat_id, inst)
        return
    if op == "bootvol":
        _bootvol_list(token, chat_id, message_id, inst["tenant_id"])
        return
    if _write_blocked(token, chat_id):
        return
    labels = {"start": "开机", "stop": "关机", "reboot": "重启", "changeip": "换 IP", "terminate": "终止实例"}
    if op not in labels:
        return
    if op == "terminate":
        kb = _kb([
            [("🗑 终止（保留引导卷）", f"cf:term_keep:{ref}"), ("💥 终止并删除引导卷", f"cf:term_del:{ref}")],
            [("❌ 取消", "cancel")],
        ])
        text = f"确认终止 <b>{_esc(name)}</b>？此操作不可恢复。"
    else:
        kb = _kb([
            [("✅ 确认", f"cf:{op}:{ref}"), ("❌ 取消", "cancel")],
        ])
        extra = f"（当前 IP {_esc(inst.get('public_ip') or '-') }）" if op == "changeip" else ""
        text = f"确认为 <b>{_esc(name)}</b> 执行「{labels[op]}」？{extra}"
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def execute_confirm(token: str, chat_id: str, action: str, payload: dict) -> None:
    """执行二次确认后的写操作（菜单与旧文本命令共用）。"""
    if _write_blocked(token, chat_id):
        return
    # 菜单侧的 start/stop/reboot 映射到执行层命名
    action = {"start": "startvm", "stop": "stopvm", "reboot": "rebootvm"}.get(action, action)
    tenant_id = payload.get("tenant_id")
    instance_id = payload.get("instance_id")
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
        try:
            if action in ("startvm", "stopvm", "rebootvm"):
                op = {"startvm": "start", "stopvm": "stop", "rebootvm": "reboot"}[action]
                instance_service.power_instance(tenant, instance_id, op)
                _send(token, chat_id, f"已下发「{op}」操作")
                _audit(f"tg.{op}", f"TG 机器人对实例 {instance_id} 执行 {op}")
            elif action == "changeip":
                task = models.IpTask(tenant_id=tenant_id, instance_id=instance_id,
                                     preferred_cidrs="[]", update_dns=False,
                                     max_retries=3, status="running")
                db.add(task)
                db.commit()
                _send(token, chat_id, f"已创建换 IP 任务（#{task.id}），后台执行中")
                _audit("tg.change_ip", f"TG 机器人对实例 {instance_id} 发起换 IP")
            elif action in ("term_keep", "term_del"):
                instance_service.terminate_instance(tenant, instance_id, preserve_boot_volume=(action == "term_keep"))
                _send(token, chat_id, "已下发终止实例操作" + ("（保留引导卷）" if action == "term_keep" else "（删除引导卷）"))
                _audit("tg.terminate", f"TG 机器人终止实例 {instance_id}（保留引导卷={action == 'term_keep'}）")
            else:
                _send(token, chat_id, "未知操作")
        except Exception as exc:
            _send(token, chat_id, f"执行失败：{_esc(str(exc))[:200]}")
    finally:
        db.close()


# ================= 引导卷 =================

def _bootvol_list(token: str, chat_id: str, message_id: int | None, tenant_id: int) -> None:
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        vols = volume_service.list_boot_volumes(tenant, tenant.tenancy_ocid)
    except Exception as exc:
        _send(token, chat_id, f"查询引导卷失败：{_esc(str(exc))[:150]}")
        return
    if not vols:
        _send(token, chat_id, "该租户下暂无引导卷")
        return
    sess = _session(chat_id)
    sess["ctx"]["bv_list"] = [{"tenant_id": tenant.id, "tenant_name": tenant.name, **v} for v in vols[:10]]
    rows: list[list[tuple[str, str]]] = []
    row: list[tuple[str, str]] = []
    for idx, v in enumerate(sess["ctx"]["bv_list"]):
        ref = _put_ref(chat_id, {"tenant_id": tenant.id, "idx": idx})
        name = (v.get("display_name") or v.get("id", ""))[:14]
        row.append((f"💾 {name} {v.get('size_in_gbs')}G", f"bvd:{ref}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([("◀️ 返回主菜单", "menu")])
    text = f"<b>{_esc(tenant.name)}</b> 引导卷（{len(vols)} 个）"
    if message_id:
        _edit(token, chat_id, message_id, text, _kb(rows))
    else:
        _send(token, chat_id, text, _kb(rows))


def _bootvol_detail(token: str, chat_id: str, message_id: int | None, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    vols = _session(chat_id)["ctx"].get("bv_list", [])
    v = vols[payload["idx"]] if payload and payload.get("idx") is not None and payload["idx"] < len(vols) else None
    if not v:
        _send(token, chat_id, "引导卷信息已过期，请重新打开菜单")
        return
    text = (
        f"<b>{_esc(v.get('display_name'))}</b>\n"
        f"大小：{v.get('size_in_gbs')} GB\n状态：{_esc(v.get('lifecycle_state'))}\n"
        f"可用域：{_esc(v.get('availability_domain') or '-')}\n"
        f"挂载实例：{_esc(v.get('instance_name') or '未挂载')}"
    )
    kb = _kb([
        [("📏 调整大小", f"bvr:{ref}")],
        [("◀️ 返回主菜单", "menu")],
    ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _bootvol_resize_ask(token: str, chat_id: str, message_id: int | None, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    vols = _session(chat_id)["ctx"].get("bv_list", [])
    v = vols[payload["idx"]] if payload and payload.get("idx") is not None and payload["idx"] < len(vols) else None
    if not v:
        _send(token, chat_id, "引导卷信息已过期，请重新打开菜单")
        return
    if _write_blocked(token, chat_id):
        return
    sess = _session(chat_id)
    sess["awaiting"] = "boot_resize"
    sess["ctx"]["boot_resize"] = {"tenant_id": v["tenant_id"], "volume_id": v["id"],
                                  "name": v.get("display_name") or v["id"], "current": v.get("size_in_gbs")}
    _send(token, chat_id, f"请回复新的大小（GB，只能调大，当前 {v.get('size_in_gbs')} GB），或发送 /exit 取消。")


def _bootvol_resize_do(token: str, chat_id: str) -> None:
    ctx = _session(chat_id)["ctx"].get("boot_resize") or {}
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, ctx.get("tenant_id"))
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        volume_service.resize_boot_volume(tenant, ctx["volume_id"], int(ctx["size"]))
        _send(token, chat_id, f"✅ 引导卷 {_esc(ctx.get('name'))} 已调整为 {ctx['size']} GB（实例内还需自行扩容分区）")
        _audit("tg.boot_resize", f"TG 机器人调整引导卷 {ctx['volume_id']} 至 {ctx['size']} GB")
    except Exception as exc:
        _send(token, chat_id, f"调整失败：{_esc(str(exc))[:200]}")


# ================= 任务管理 / 测活 / 流量 / 监控 / 日志 / 版本 =================

def _task_list(token: str, chat_id: str, message_id: int | None) -> None:
    db = SessionLocal()
    try:
        tasks = db.query(models.SnatchTask).order_by(models.SnatchTask.id.desc()).limit(10).all()
        rows: list[list[tuple[str, str]]] = []
        for t in tasks:
            ref = _put_ref(chat_id, {"task_id": t.id})
            rows.append([(f"{'🟢' if t.status == 'running' else '⏸' if t.status == 'paused' else '⚪'} {t.name[:16]} [{t.status}]", f"task:{ref}")])
        if not rows:
            text = "暂无抢机任务"
        else:
            text = "<b>抢机任务</b>（最近 10 个）"
        rows.append([("◀️ 返回主菜单", "menu")])
        if message_id:
            _edit(token, chat_id, message_id, text, _kb(rows))
        else:
            _send(token, chat_id, text, _kb(rows))
    finally:
        db.close()


def _task_detail(token: str, chat_id: str, message_id: int | None, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    if not payload:
        _send(token, chat_id, "该按钮已过期，请重新打开菜单")
        return
    db = SessionLocal()
    try:
        t = db.get(models.SnatchTask, payload["task_id"])
        if t is None:
            _send(token, chat_id, "任务不存在")
            return
        text = (
            f"<b>{_esc(t.name)}</b>\n状态：{t.status}\nShape：{_esc(t.shape)}\n"
            f"尝试：{t.attempts or 0} 次\n"
            f"最近错误：{_esc((t.last_error or '-')[:120])}\n"
            f"已创建实例：{_esc(t.created_instance_id or '-')}"
        )
        rows: list[list[tuple[str, str]]] = []
        if t.status == "running":
            rows.append([("⏸ 暂停", f"top:pause:{ref}")])
        elif t.status == "paused":
            rows.append([("▶️ 继续", f"top:resume:{ref}")])
        elif t.status == "pending":
            rows.append([("▶️ 启动", f"top:start:{ref}")])
        rows.append([("◀️ 返回任务列表", "tasks"), ("◀️ 主菜单", "menu")])
        if message_id:
            _edit(token, chat_id, message_id, text, _kb(rows))
        else:
            _send(token, chat_id, text, _kb(rows))
    finally:
        db.close()


def _task_op(token: str, chat_id: str, message_id: int | None, op: str, ref: str) -> None:
    if _write_blocked(token, chat_id):
        return
    payload = _get_ref(chat_id, ref)
    if not payload:
        _send(token, chat_id, "该按钮已过期，请重新打开菜单")
        return
    allowed = {"start": ("pending", "paused"), "pause": ("running",), "resume": ("paused",)}
    new_status = {"start": "running", "pause": "paused", "resume": "running"}[op]
    db = SessionLocal()
    try:
        t = db.get(models.SnatchTask, payload["task_id"])
        if t is None:
            _send(token, chat_id, "任务不存在")
            return
        if t.status not in allowed[op]:
            _send(token, chat_id, f"当前状态 {t.status} 不能执行 {op}")
            return
        t.status = new_status
        db.commit()
        _audit(f"tg.snatch.{op}", f"TG 机器人对抢机任务 #{t.id}（{t.name}）执行 {op}，状态 -> {new_status}")
        _send(token, chat_id, f"✅ 任务「{_esc(t.name)}」已{'暂停' if op == 'pause' else '启动'}")
    finally:
        db.close()


def _alive(token: str, chat_id: str, message_id: int | None) -> None:
    _send(token, chat_id, "🔍 巡检中…")
    db = SessionLocal()
    try:
        report = inspection_service.inspect_all(db)
    except Exception as exc:
        _send(token, chat_id, f"巡检失败：{_esc(str(exc))[:150]}")
        return
    finally:
        db.close()
    issues = report.get("issues") or []
    lines = [f"<b>巡检完成</b>：{report.get('instances_total', 0)} 台实例，"
             f"运行 {report.get('running', 0)}，停止 {report.get('stopped', 0)}，异常 {len(issues)} 项"]
    for i in issues[:15]:
        lines.append(f"• [{i.get('level')}] {_esc(i.get('tenant'))} / {_esc(i.get('instance'))}：{_esc(i.get('message'))}")
    if len(issues) > 15:
        lines.append(f"…等共 {len(issues)} 项")
    if report.get("errors"):
        lines.append("部分租户巡检失败：" + "、".join(_esc(e.get("tenant")) for e in report["errors"]))
    _send(token, chat_id, "\n".join(lines))


def _traffic_menu(token: str, chat_id: str, message_id: int | None, tenant_id: int) -> None:
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        items = instance_service.list_instances(tenant)
    except Exception as exc:
        _send(token, chat_id, f"查询实例失败：{_esc(str(exc))[:150]}")
        return
    total_in = total_out = peak = 0.0
    counted = 0
    for inst in items[:5]:
        try:
            vnic_id = monitoring_service.get_primary_vnic_id(tenant, inst["id"])
            points = monitoring_service.query_vnic_traffic(tenant, vnic_id, 24, "1h")
            if not points:
                continue
            total_in += sum(p["inbound_mbps"] for p in points) / 8 / 3600 * 24
            total_out += sum(p["outbound_mbps"] for p in points) / 8 / 3600 * 24
            peak = max(peak, max(max(p["inbound_mbps"], p["outbound_mbps"]) for p in points))
            counted += 1
        except Exception:
            continue
    _send(token, chat_id,
          f"<b>{_esc(tenant.name)} 24h 流量汇总</b>\n"
          f"已统计 {counted} 台实例\n入站约 {total_in:.2f} GB\n出站约 {total_out:.2f} GB\n峰值 {peak:.1f} Mbps")


def _cpu_percent() -> float:
    def read():
        vals = {}
        with open("/proc/stat") as f:
            parts = f.readline().split()[1:]
        nums = [int(x) for x in parts]
        return sum(nums), nums[3]
    try:
        t1, i1 = read()
        time.sleep(0.3)
        t2, i2 = read()
        return round((1 - (i2 - i1) / max(t2 - t1, 1)) * 100, 1)
    except Exception:
        return 0.0


def _metrics(token: str, chat_id: str, message_id: int | None) -> None:
    try:
        cpu = _cpu_percent()
        mem_total = mem_avail = 0
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    mem_total = int(line.split()[1])
                elif line.startswith("MemAvailable"):
                    mem_avail = int(line.split()[1])
        mem_used_pct = round((1 - mem_avail / mem_total) * 100, 1) if mem_total else 0.0
        disk = shutil.disk_usage("/")
        disk_pct = round(disk.used / disk.total * 100, 1)
        load1, load5, _ = os.getloadavg()
        with open("/proc/uptime") as f:
            up = float(f.read().split()[0])
        days, rem = divmod(int(up), 86400)
        hrs, rem = divmod(rem, 3600)
        text = (
            "<b>📊 服务器资源监控</b>\n"
            f"CPU：{cpu}%（负载 {load1:.2f} / {load5:.2f}）\n"
            f"内存：{mem_used_pct}%（可用 {mem_avail // 1024} / {mem_total // 1024} MB）\n"
            f"磁盘：{disk_pct}%（可用 {disk.free // (1024 ** 3)} / {disk.total // (1024 ** 3)} GB）\n"
            f"运行时间：{days} 天 {hrs} 小时"
        )
    except Exception as exc:
        text = f"资源监控读取失败：{_esc(str(exc))[:150]}"
    if message_id:
        _edit(token, chat_id, message_id, text, _back_kb())
    else:
        _send(token, chat_id, text, _back_kb())


def _logs(token: str, chat_id: str, message_id: int | None) -> None:
    db = SessionLocal()
    try:
        rows = db.query(models.OperationLog).order_by(models.OperationLog.id.desc()).limit(100).all()
        lines = []
        for r in reversed(rows):
            ts = r.created_at.strftime("%m-%d %H:%M") if r.created_at else ""
            lines.append(f"[{ts}] {r.action} {r.detail or ''}")
        data = ("\n".join(lines) or "暂无操作记录").encode()
    finally:
        db.close()
    r = _send_document(token, chat_id, f"zy-panel-logs-{datetime.now():%Y%m%d-%H%M}.txt", data,
                       caption="最近 100 条操作记录")
    if not r.get("ok"):
        _send(token, chat_id, "日志发送失败，请重试")


def _version(token: str, chat_id: str, message_id: int | None) -> None:
    db = SessionLocal()
    try:
        n_tenants = db.query(models.Tenant).count()
        n_running = db.query(models.SnatchTask).filter(models.SnatchTask.status == "running").count()
        n_tasks = db.query(models.SnatchTask).count()
    finally:
        db.close()
    try:
        backend_v = update_service.get_current_version()
    except Exception:
        backend_v = "未知"
    ai = get_ai_config()
    text = (
        "<b>🏷️ 版本信息</b>\n"
        f"后端：zy-panel-backend v{backend_v}\n"
        f"租户：{n_tenants} 个\n"
        f"抢机任务：{n_tasks} 个（运行中 {n_running}）\n"
        f"AI 聊天：{'已配置' if ai['has_key'] else '未配置 API Key'}（{AI_MODEL_NAMES.get(ai['model'], ai['model'])}）\n"
        f"防御模式：{'已开启 🛡️' if _defense_on() else '未开启'}"
    )
    if message_id:
        _edit(token, chat_id, message_id, text, _back_kb())
    else:
        _send(token, chat_id, text, _back_kb())


# ================= AI 聊天 =================

def _ai_menu(token: str, chat_id: str, message_id: int | None) -> None:
    cfg = get_ai_config()
    sess = _session(chat_id)
    if not cfg["has_key"]:
        text = "🤖 AI 聊天未配置 API Key。\n请先在网页端「通知渠道」页的 TG 机器人卡片里填写 SiliconFlow API Key。"
        if message_id:
            _edit(token, chat_id, message_id, text, _back_kb())
        else:
            _send(token, chat_id, text, _back_kb())
        return
    model = sess.get("ai_model") or cfg["model"]
    sess["ai_model"] = model
    rows = [[("🔄 切换模型", "ai_models")], [("🚪 退出聊天", "menu")]]
    text = (
        "🤖 <b>AI 聊天</b>\n"
        f"当前模型：{AI_MODEL_NAMES.get(model, model)}\n"
        "直接发消息开始聊天，发送 /exit 退出。"
    )
    sess["awaiting"] = "ai"
    if message_id:
        _edit(token, chat_id, message_id, text, _kb(rows))
    else:
        _send(token, chat_id, text, _kb(rows))


def _ai_models(token: str, chat_id: str, message_id: int | None) -> None:
    sess = _session(chat_id)
    cur = sess.get("ai_model") or get_ai_config()["model"]
    rows = [[(f"{'✅ ' if m == cur else ''}{name}", f"ai_set:{m}")] for m, name in AI_MODELS]
    rows.append([("◀️ 返回", "ai")])
    _edit(token, chat_id, message_id, "选择模型：", _kb(rows)) if message_id else _send(token, chat_id, "选择模型：", _kb(rows))


def _ai_chat(token: str, chat_id: str, text: str) -> None:
    cfg = get_ai_config()
    if not cfg["has_key"]:
        _send(token, chat_id, "AI 聊天未配置 API Key。")
        return
    sess = _session(chat_id)
    model = sess.get("ai_model") or cfg["model"]
    history = sess.setdefault("ai_history", [])
    messages = [{"role": "system", "content": "你是 zy-panel 的运维助手，回答简洁，用中文。"}]
    messages += history[-10:]
    messages.append({"role": "user", "content": text})
    try:
        resp = httpx.post(
            cfg["base_url"].rstrip("/") + "/chat/completions",
            json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 2000},
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            timeout=60,
        )
        data = resp.json()
        reply = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        if not reply:
            reply = f"AI 未返回内容：{str(data)[:200]}"
    except Exception as exc:
        _send(token, chat_id, f"AI 请求失败：{_esc(str(exc))[:200]}")
        return
    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    del history[:-20]
    _send(token, chat_id, _esc(reply[:3500]))


# ================= SSH 管理 =================

def _ssh_menu(token: str, chat_id: str, message_id: int | None) -> None:
    sess = _session(chat_id)
    conn = sess.get("ssh") or {}
    if conn.get("connected"):
        text = (
            "🔌 <b>SSH 已连接</b>\n"
            f"实例：{_esc(conn.get('display_name'))}\n"
            f"地址：{_esc(conn.get('username'))}@{_esc(conn.get('host'))}\n"
            "发送 /ssh &lt;命令&gt; 执行命令。"
        )
        kb = _kb([[("🔌 断开连接", "ssh_off")], [("◀️ 返回主菜单", "menu")]])
    else:
        text = "🔌 <b>SSH 管理</b>\n请选择租户，再选实例建立连接。"
        kb = None
        _tenant_pick(token, chat_id, message_id, "ssh_t", text)
        return
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _ssh_connect(token: str, chat_id: str, message_id: int | None, ref: str) -> None:
    payload = _get_ref(chat_id, ref)
    insts = _session(chat_id)["ctx"].get("inst_list", [])
    inst = insts[payload["idx"]] if payload and payload.get("idx") is not None and payload["idx"] < len(insts) else None
    if not inst or not inst.get("public_ip"):
        _send(token, chat_id, "该实例无公网 IP，无法 SSH 连接")
        return
    if _write_blocked(token, chat_id):
        return
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, inst["tenant_id"])
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        key_pem = oci_factory.decrypt_private_key(tenant.private_key_ciphertext)
        db.expunge(tenant)
    except Exception as exc:
        _send(token, chat_id, f"读取租户私钥失败：{_esc(str(exc))[:150]}")
        return
    finally:
        db.close()
    _send(token, chat_id, f"正在连接 {_esc(inst.get('display_name'))}…")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    last_exc: Exception | None = None
    for username in ("opc", "ubuntu"):
        try:
            pkey = paramiko.RSAKey.from_private_key(io.StringIO(key_pem))
            client.connect(hostname=inst["public_ip"], port=22, username=username,
                           pkey=pkey, timeout=15, banner_timeout=15, auth_timeout=15)
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            try:
                client.close()
            except Exception:
                pass
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if last_exc is not None:
        _send(token, chat_id, f"SSH 连接失败：{_esc(str(last_exc))[:200]}")
        return
    _session(chat_id)["ssh"] = {
        "connected": True, "tenant_id": inst["tenant_id"], "instance_id": inst["id"],
        "display_name": inst.get("display_name"), "host": inst["public_ip"],
        "username": username, "client": client,
    }
    _audit("tg.ssh_connect", f"TG 机器人 SSH 连接实例 {inst['id']}（{username}@{inst['public_ip']}）")
    _send(token, chat_id,
          f"✅ 已连接 <b>{_esc(inst.get('display_name'))}</b>（{username}@{_esc(inst['public_ip'])}）\n"
          "发送 /ssh &lt;命令&gt; 执行命令，点菜单断开连接。")


def _ssh_exec(token: str, chat_id: str, command: str) -> bool:
    sess = _session(chat_id)
    conn = sess.get("ssh") or {}
    client = conn.get("client")
    if not conn.get("connected") or client is None:
        _send(token, chat_id, "SSH 未连接，请先从菜单「SSH 管理」选择实例连接。")
        return True
    if _write_blocked(token, chat_id):
        return True
    if not command.strip():
        _send(token, chat_id, "用法：/ssh <命令>")
        return True
    try:
        _stdin, stdout, stderr = client.exec_command(command, timeout=30)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        text = (out + ("\n" + err if err else "")).strip()
        if not text:
            text = "（无输出）"
        _send(token, chat_id, f"$ {_esc(command)}\n{_esc(text[:3500])}")
    except Exception as exc:
        _send(token, chat_id, f"命令执行失败：{_esc(str(exc))[:200]}")
        try:
            client.close()
        except Exception:
            pass
        sess["ssh"] = None
    return True


def _ssh_disconnect(token: str, chat_id: str, message_id: int | None) -> None:
    sess = _session(chat_id)
    conn = sess.get("ssh") or {}
    client = conn.get("client")
    if client is not None:
        try:
            client.close()
        except Exception:
            pass
    sess["ssh"] = None
    _send(token, chat_id, "🔌 SSH 已断开")


# ================= MFA / VNC / 备份 / 黑名单 / 防御 =================

def _admin_user():
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.is_admin.is_(True)).order_by(models.User.id).first()
        if user is None:
            user = db.query(models.User).order_by(models.User.id).first()
        if user is not None:
            db.expunge(user)
        return user
    finally:
        db.close()


def _mfa_menu(token: str, chat_id: str, message_id: int | None) -> None:
    user = _admin_user()
    if user is None:
        _send(token, chat_id, "暂无用户")
        return
    if user.mfa_enabled and user.mfa_secret:
        try:
            code = pyotp.TOTP(user.mfa_secret).now()
        except Exception:
            code = "（密钥无效）"
        text = f"🔐 <b>MFA 管理</b>\n用户：{_esc(user.username)}\n状态：已启用\n当前验证码：<b>{code}</b>（30 秒有效）"
        kb = _kb([
            [("🔄 刷新验证码", "mfa"), ("🔴 关闭 MFA", "mfa_off")],
            [("◀️ 返回主菜单", "menu")],
        ])
    else:
        text = f"🔐 <b>MFA 管理</b>\n用户：{_esc(user.username)}\n状态：未启用\n开启后，TG 里可随时查看登录验证码。"
        kb = _kb([
            [("🟢 开启 MFA", "mfa_on")],
            [("◀️ 返回主菜单", "menu")],
        ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _mfa_on(token: str, chat_id: str, message_id: int | None) -> None:
    if _write_blocked(token, chat_id):
        return
    user = _admin_user()
    if user is None:
        return
    secret = pyotp.random_base32()
    sess = _session(chat_id)
    sess["awaiting"] = "mfa_code"
    sess["ctx"]["mfa_pending"] = {"user_id": user.id, "secret": secret}
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="zy-panel")
    _send(token, chat_id,
          "请用验证器 App 添加以下密钥（或直接导入链接）：\n"
          f"<code>{secret}</code>\n{uri}\n\n"
          "添加后请回复 6 位验证码完成绑定，或发送 /exit 取消。")


def _mfa_code_verify(token: str, chat_id: str, code: str) -> None:
    pending = _session(chat_id)["ctx"].get("mfa_pending") or {}
    secret = pending.get("secret")
    if not secret:
        _send(token, chat_id, "没有待绑定的 MFA，请从菜单重新开启。")
        return
    if not re.fullmatch(r"\d{6}", code.strip()):
        _send(token, chat_id, "验证码应为 6 位数字，请重新输入。")
        return
    if not pyotp.TOTP(secret).verify(code.strip(), valid_window=1):
        _send(token, chat_id, "验证码不正确，请重新输入。")
        return
    db = SessionLocal()
    try:
        user = db.get(models.User, pending["user_id"])
        if user is None:
            _send(token, chat_id, "用户不存在")
            return
        user.mfa_secret = secret
        user.mfa_enabled = True
        db.commit()
        _audit("tg.mfa_enable", f"TG 机器人为用户 {user.username} 开启 MFA")
        _session(chat_id)["awaiting"] = None
        _send(token, chat_id, "✅ MFA 已开启，TG 菜单里可随时查看验证码。")
    finally:
        db.close()


def _mfa_off(token: str, chat_id: str, message_id: int | None) -> None:
    if _write_blocked(token, chat_id):
        return
    user = _admin_user()
    if user is None:
        return
    db = SessionLocal()
    try:
        u = db.get(models.User, user.id)
        u.mfa_enabled = False
        db.commit()
        _audit("tg.mfa_disable", f"TG 机器人为用户 {user.username} 关闭 MFA")
        _send(token, chat_id, "MFA 已关闭（密钥已保留，再次开启无需重新绑定）。")
    finally:
        db.close()


def _vnc_menu(token: str, chat_id: str, message_id: int | None) -> None:
    url = _setting(VNC_URL)
    text = "🖥️ <b>VNC 配置</b>\n" + (f"当前 VNC URL：{url}" if url else "未配置 VNC URL。")
    kb = _kb([
        [("✏️ 设置 VNC URL", "vnc_set"), ("🗑 清除", "vnc_clear")],
        [("◀️ 返回主菜单", "menu")],
    ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _backup_menu(token: str, chat_id: str, message_id: int | None) -> None:
    text = "💾 <b>备份恢复</b>\n导出会把加密备份文件发到本聊天；恢复请直接发送 .bin 备份文件。"
    kb = _kb([
        [("📤 导出备份", "bk_exp"), ("📥 恢复备份", "bk_imp")],
        [("◀️ 返回主菜单", "menu")],
    ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _backup_export(token: str, chat_id: str) -> None:
    db = SessionLocal()
    try:
        data = backup_service.export_all(db)
        payload = backup_service.encrypt_payload(data)
    finally:
        db.close()
    filename = f"zy-panel-backup-{datetime.now():%Y%m%d-%H%M}.bin"
    r = _send_document(token, chat_id, filename, payload, caption="zy-panel 加密备份（请妥善保管）")
    if r.get("ok"):
        _audit("tg.backup_export", "TG 机器人导出加密备份")
    else:
        _send(token, chat_id, "备份发送失败，请重试")


def _backup_import(token: str, chat_id: str, doc: dict) -> bool:
    if _write_blocked(token, chat_id):
        return True
    file_id = doc.get("file_id")
    raw = _download_file(token, file_id) if file_id else None
    if not raw:
        _send(token, chat_id, "备份文件下载失败，请重试")
        return True
    try:
        data = backup_service.decrypt_payload(raw)
        db = SessionLocal()
        try:
            counts = backup_service.import_all(db, data)
        finally:
            db.close()
        total = sum(counts.values()) if isinstance(counts, dict) else 0
        _send(token, chat_id, f"✅ 备份恢复成功，共 {total} 条记录：{counts}")
        _audit("tg.backup_import", f"TG 机器人从备份恢复 {total} 条记录")
    except Exception as exc:
        _send(token, chat_id, f"恢复失败：{_esc(str(exc))[:200]}（请确认是本面板导出的 .bin 备份）")
    _session(chat_id)["awaiting"] = None
    return True


def _ipbl_menu(token: str, chat_id: str, message_id: int | None) -> None:
    entries = _ip_blacklist()
    lines = ["🚫 <b>IP 黑名单</b>（黑名单 IP 无法登录面板）"]
    rows: list[list[tuple[str, str]]] = []
    for e in entries[:20]:
        ref = _put_ref(chat_id, {"entry": e})
        rows.append([(f"{e}", f"ipbl_del:{ref}")])
    if len(entries) > 20:
        lines.append(f"…等共 {len(entries)} 条（点条目删除）")
    if not entries:
        lines.append("当前为空。点条目可删除对应 IP。")
    rows.append([("➕ 添加 IP", "ipbl_add"), ("🗑 清空", "ipbl_clear")])
    rows.append([("◀️ 返回主菜单", "menu")])
    text = "\n".join(lines)
    if message_id:
        _edit(token, chat_id, message_id, text, _kb(rows))
    else:
        _send(token, chat_id, text, _kb(rows))


def _defense_menu(token: str, chat_id: str, message_id: int | None) -> None:
    on = _defense_on()
    text = (
        "🛡️ <b>防御模式</b>\n"
        f"状态：{'已开启（所有 IP 均无法登录面板，TG 写操作已冻结）' if on else '未开启'}\n"
        "开启后只能从 TG 关闭，请谨慎操作。"
    )
    kb = _kb([
        [("🔴 关闭防御模式", "def_off")] if on else [("🟢 开启防御模式", "def_on")],
        [("◀️ 返回主菜单", "menu")],
    ])
    if message_id:
        _edit(token, chat_id, message_id, text, kb)
    else:
        _send(token, chat_id, text, kb)


def _defense_set(token: str, chat_id: str, on: bool) -> None:
    _set_setting(DEFENSE_KEY, "1" if on else "0")
    _audit("tg.defense_mode", f"TG 机器人{'开启' if on else '关闭'}防御模式")
    _send(token, chat_id, "🛡️ 防御模式已开启：面板登录已全部冻结，TG 写操作已冻结。" if on else "🛡️ 防御模式已关闭，面板登录恢复正常。")


# ================= 创建实例向导 =================

def _create_tenant_pick(token: str, chat_id: str, message_id: int | None) -> None:
    _tenant_pick(token, chat_id, message_id, "create_t", "➕ <b>创建实例</b>\n请选择租户（仅 OCI）：")


def _create_plan_pick(token: str, chat_id: str, message_id: int | None, tenant_id: int) -> None:
    sess = _session(chat_id)
    sess["ctx"]["create"] = {"tenant_id": tenant_id}
    rows = [[(f"{name}", f"create_p:{key}")] for key, name, _s, _o, _m in CREATE_PLANS]
    rows.append([("◀️ 返回主菜单", "menu")])
    text = "➕ <b>创建实例</b>\n请选择规格方案："
    if message_id:
        _edit(token, chat_id, message_id, text, _kb(rows))
    else:
        _send(token, chat_id, text, _kb(rows))


def _create_ad_pick(token: str, chat_id: str, message_id: int | None, plan_key: str) -> None:
    ctx = _session(chat_id)["ctx"].get("create") or {}
    ctx["plan"] = plan_key
    tenant_id = ctx.get("tenant_id")
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        ads = meta_service.list_availability_domains(tenant)
    except Exception as exc:
        _send(token, chat_id, f"查询可用域失败：{_esc(str(exc))[:150]}")
        return
    if not ads:
        _send(token, chat_id, "该租户下无可用域")
        return
    ctx["ads"] = [a.get("name") or a.get("id") for a in ads]
    rows = [[(f"{a}", f"create_ad:{i}")] for i, a in enumerate(ctx["ads"])]
    rows.append([("◀️ 返回主菜单", "menu")])
    if message_id:
        _edit(token, chat_id, message_id, "请选择可用域：", _kb(rows))
    else:
        _send(token, chat_id, "请选择可用域：", _kb(rows))


def _create_img_pick(token: str, chat_id: str, message_id: int | None, ad_idx: int) -> None:
    ctx = _session(chat_id)["ctx"].get("create") or {}
    ads = ctx.get("ads") or []
    if ad_idx >= len(ads):
        _send(token, chat_id, "可用域选择已过期，请重新开始")
        return
    ctx["ad"] = ads[ad_idx]
    tenant_id = ctx.get("tenant_id")
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        images = meta_service.list_images(tenant, limit=100)
    except Exception as exc:
        _send(token, chat_id, f"查询镜像失败：{_esc(str(exc))[:150]}")
        return
    ubuntu = [i for i in images if "Ubuntu" in (i.get("display_name") or "")]
    picks = (ubuntu or images)[:5]
    if not picks:
        _send(token, chat_id, "该租户下无可用镜像")
        return
    ctx["images"] = picks
    rows = []
    for i, img in enumerate(picks):
        name = (img.get("display_name") or img.get("id", ""))[:28]
        rows.append([(f"{name}", f"create_img:{i}")])
    rows.append([("◀️ 返回主菜单", "menu")])
    if message_id:
        _edit(token, chat_id, message_id, "请选择镜像：", _kb(rows))
    else:
        _send(token, chat_id, "请选择镜像：", _kb(rows))


def _create_sn_pick(token: str, chat_id: str, message_id: int | None, img_idx: int) -> None:
    ctx = _session(chat_id)["ctx"].get("create") or {}
    images = ctx.get("images") or []
    if img_idx >= len(images):
        _send(token, chat_id, "镜像选择已过期，请重新开始")
        return
    ctx["image_id"] = images[img_idx].get("id")
    ctx["image_name"] = images[img_idx].get("display_name") or images[img_idx].get("id")
    tenant_id = ctx.get("tenant_id")
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        db.expunge(tenant)
    finally:
        db.close()
    try:
        subnets = meta_service.list_subnets(tenant)
    except Exception as exc:
        _send(token, chat_id, f"查询子网失败：{_esc(str(exc))[:150]}")
        return
    if not subnets:
        _send(token, chat_id, "该租户下无可用子网")
        return
    ctx["subnets"] = subnets[:5]
    rows = []
    for i, sn in enumerate(ctx["subnets"]):
        name = (sn.get("display_name") or sn.get("id", ""))[:24]
        rows.append([(f"{name}", f"create_sn:{i}")])
    rows.append([("◀️ 返回主菜单", "menu")])
    if message_id:
        _edit(token, chat_id, message_id, "请选择子网：", _kb(rows))
    else:
        _send(token, chat_id, "请选择子网：", _kb(rows))


def _create_ssh_ask(token: str, chat_id: str, message_id: int | None, sn_idx: int) -> None:
    ctx = _session(chat_id)["ctx"].get("create") or {}
    subnets = ctx.get("subnets") or []
    if sn_idx >= len(subnets):
        _send(token, chat_id, "子网选择已过期，请重新开始")
        return
    ctx["subnet_id"] = subnets[sn_idx].get("id")
    sess = _session(chat_id)
    sess["awaiting"] = "create_ssh"
    _send(token, chat_id,
          "请回复 SSH 公钥（ssh-rsa / ssh-ed25519 开头的一行），实例将注入该密钥；\n"
          "不需要可发送 /skip 跳过。")


def _create_confirm(token: str, chat_id: str, message_id: int | None) -> None:
    ctx = _session(chat_id)["ctx"].get("create") or {}
    plan = PLAN_MAP.get(ctx.get("plan") or "")
    if not plan:
        _send(token, chat_id, "创建信息已过期，请从菜单重新开始")
        return
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, ctx.get("tenant_id"))
        tname = tenant.name if tenant else "?"
    finally:
        db.close()
    text = (
        "➕ <b>确认创建实例</b>\n"
        f"租户：{_esc(tname)}\n规格：{plan[1]}\n可用域：{_esc(ctx.get('ad'))}\n"
        f"镜像：{_esc((ctx.get('image_name') or '')[:40])}\n"
        f"SSH 公钥：{'已提供' if ctx.get('ssh_key') else '未提供（只能走串行控制台）'}"
    )
    kb = _kb([
        [("✅ 确认创建", "create_go"), ("❌ 取消", "menu")],
    ])
    _send(token, chat_id, text, kb)


def _create_go(token: str, chat_id: str, message_id: int | None) -> None:
    if _write_blocked(token, chat_id):
        return
    ctx = _session(chat_id)["ctx"].get("create") or {}
    plan = PLAN_MAP.get(ctx.get("plan") or "")
    if not plan or not ctx.get("tenant_id"):
        _send(token, chat_id, "创建信息已过期，请从菜单重新开始")
        return
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, ctx["tenant_id"])
        if tenant is None:
            _send(token, chat_id, "租户不存在")
            return
        try:
            compartments = meta_service.list_compartments(tenant)
            compartment_id = (compartments[0].get("id") if compartments else None) or tenant.tenancy_ocid
        except Exception:
            compartment_id = tenant.tenancy_ocid
        task = models.SnatchTask(
            tenant_id=tenant.id, name=f"TG创建-{plan[0]}", shape=plan[2],
            compartment_id=compartment_id, image_id=ctx.get("image_id") or "",
            subnet_id=ctx.get("subnet_id") or "", availability_domain=ctx.get("ad") or "",
            ocpus=plan[3], memory_in_gbs=plan[4],
            display_name=f"tg-{plan[0]}-{datetime.now():%m%d%H%M}",
            assign_public_ip=True, ssh_public_key=ctx.get("ssh_key") or None,
            status="running",
        )
        db.add(task)
        db.commit()
        task_id = task.id
        _audit("tg.create_instance", f"TG 机器人创建实例任务 #{task_id}（{plan[2]}，租户 {tenant.name}）")
    finally:
        db.close()
    _send(token, chat_id, "正在向 OCI 提交创建请求…")
    try:
        asyncio.run(snatch_worker.attempt_create(task_id))
    except Exception as exc:
        _send(token, chat_id, f"创建尝试异常：{_esc(str(exc))[:200]}")
        return
    db = SessionLocal()
    try:
        t = db.get(models.SnatchTask, task_id)
        if t is None:
            return
        if t.status == "success":
            _send(token, chat_id, f"✅ 创建成功！实例 {_esc(t.created_instance_id or '')}")
        elif t.status == "failed":
            _send(token, chat_id, f"❌ 创建失败：{_esc((t.last_error or '')[:200])}")
        else:
            _send(token, chat_id,
                   f"⏳ 暂无库存，已转为抢机任务（#{task_id}）继续轮询；\n"
                   f"最近错误：{_esc((t.last_error or '')[:150])}")
    finally:
        db.close()


# ================= 总分发 =================

def handle_text(token: str, chat_id: str, text: str) -> bool:
    """处理文本消息。返回 True 表示已消费，调用方不再走旧命令分发。"""
    sess = _session(chat_id)
    if text == "/exit":
        sess["awaiting"] = None
        sess["ctx"].pop("mfa_pending", None)
        _send(token, chat_id, "已退出当前输入。")
        return True
    if text.startswith("/ssh"):
        cmd = text[4:].strip()
        return _ssh_exec(token, chat_id, cmd)
    awaiting = sess.get("awaiting")
    if awaiting == "ai":
        if text.startswith("/"):
            return False
        _ai_chat(token, chat_id, text)
        return True
    if awaiting == "ipbl_add":
        entry = text.strip()
        try:
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            _send(token, chat_id, "格式不对，应为单个 IP（如 1.2.3.4）或 CIDR（如 1.2.3.0/24），请重新输入。")
            return True
        entries = _ip_blacklist()
        if entry not in entries:
            entries.append(entry)
            _save_ip_blacklist(entries)
            _audit("tg.ip_blacklist_add", f"TG 机器人添加 IP 黑名单 {entry}")
        sess["awaiting"] = None
        _send(token, chat_id, f"✅ 已加入黑名单：{entry}")
        return True
    if awaiting == "vnc_set":
        url = text.strip()
        if not url.startswith(("http://", "https://")):
            _send(token, chat_id, "URL 应以 http:// 或 https:// 开头，请重新输入。")
            return True
        _set_setting(VNC_URL, url)
        sess["awaiting"] = None
        _audit("tg.vnc_set", f"TG 机器人设置 VNC URL：{url}")
        _send(token, chat_id, f"✅ VNC URL 已保存：{url}")
        return True
    if awaiting == "boot_resize":
        ctx = sess["ctx"].get("boot_resize") or {}
        try:
            size = int(text.strip())
        except ValueError:
            _send(token, chat_id, "请输入整数 GB 数。")
            return True
        if size <= int(ctx.get("current") or 0):
            _send(token, chat_id, f"新大小必须大于当前 {ctx.get('current')} GB，请重新输入。")
            return True
        ctx["size"] = size
        sess["awaiting"] = None
        kb = _kb([[("✅ 确认调整", "bvr_go"), ("❌ 取消", "menu")]])
        _send(token, chat_id, f"确认把引导卷 {_esc(ctx.get('name'))} 从 {ctx.get('current')} GB 调整为 {size} GB？", kb)
        return True
    if awaiting == "mfa_code":
        _mfa_code_verify(token, chat_id, text.strip())
        return True
    if awaiting == "create_ssh":
        ctx = sess["ctx"].get("create") or {}
        if text.strip() == "/skip":
            ctx["ssh_key"] = ""
        elif text.strip().startswith(("ssh-rsa ", "ssh-ed25519 ", "ecdsa-sha2-")):
            ctx["ssh_key"] = text.strip()
        else:
            _send(token, chat_id, "公钥格式不对（应以 ssh-rsa / ssh-ed25519 开头），请重新发送，或发送 /skip 跳过。")
            return True
        sess["awaiting"] = None
        _create_confirm(token, chat_id, None)
        return True
    if awaiting == "backup_import":
        _send(token, chat_id, "请直接发送 .bin 备份文件（不是文字）。")
        return True
    return False


def handle_document(token: str, chat_id: str, doc: dict) -> bool:
    sess = _session(chat_id)
    if sess.get("awaiting") == "backup_import":
        return _backup_import(token, chat_id, doc)
    return False


def handle_callback(token: str, chat_id: str, cb: dict) -> bool:
    """处理回调。返回 True 表示已处理。"""
    data = (cb.get("data") or "")
    cb_id = cb.get("id", "")
    msg = cb.get("message") or {}
    message_id = msg.get("message_id")
    _answer(token, cb_id)
    parts = data.split(":")
    head = parts[0]

    try:
        if data == "menu":
            sess = _session(chat_id)
            sess["awaiting"] = None
            _edit(token, chat_id, message_id, MAIN_TEXT, _main_kb())
        elif data == "close":
            _tg_api(token, "deleteMessage", chat_id=chat_id, message_id=message_id)
        elif data == "cancel":
            _edit(token, chat_id, message_id, "已取消", _back_kb())
        elif data == "noop":
            pass
        elif head == "cfg" and len(parts) == 1:
            _tenant_pick(token, chat_id, message_id, "cfg", "🔧 <b>配置列表</b>")
        elif head == "cfg":
            _instance_list(token, chat_id, message_id, int(parts[1]))
        elif head == "inst":
            _instance_detail(token, chat_id, message_id, parts[1])
        elif head == "iop":
            _instance_op(token, chat_id, message_id, parts[1], parts[2])
        elif head == "cf":
            action = parts[1]
            payload = _get_ref(chat_id, parts[2]) or {}
            if "instance_id" not in payload and payload.get("idx") is not None:
                # 菜单引用只存了 idx，反查实例 ID
                insts = _session(chat_id)["ctx"].get("inst_list", [])
                inst = insts[payload["idx"]] if payload["idx"] < len(insts) else None
                if inst:
                    payload = {"tenant_id": payload.get("tenant_id"), "instance_id": inst["id"]}
            execute_confirm(token, chat_id, action, payload)
        elif head == "bvd":
            _bootvol_detail(token, chat_id, message_id, parts[1])
        elif head == "bvr":
            _bootvol_resize_ask(token, chat_id, message_id, parts[1])
        elif data == "bvr_go":
            _bootvol_resize_do(token, chat_id)
        elif data == "tasks":
            _task_list(token, chat_id, message_id)
        elif head == "task":
            _task_detail(token, chat_id, message_id, parts[1])
        elif head == "top":
            _task_op(token, chat_id, message_id, parts[1], parts[2])
        elif data == "alive":
            _alive(token, chat_id, message_id)
        elif head == "traffic" and len(parts) == 1:
            _tenant_pick(token, chat_id, message_id, "tfc", "🌐 <b>流量统计</b>")
        elif head == "tfc":
            _traffic_menu(token, chat_id, message_id, int(parts[1]))
        elif data == "metrics":
            _metrics(token, chat_id, message_id)
        elif data == "logs":
            _logs(token, chat_id, message_id)
        elif data == "version":
            _version(token, chat_id, message_id)
        elif data == "ai":
            _ai_menu(token, chat_id, message_id)
        elif data == "ai_models":
            _ai_models(token, chat_id, message_id)
        elif head == "ai_set":
            sess = _session(chat_id)
            sess["ai_model"] = parts[1]
            sess["ai_history"] = []
            _ai_menu(token, chat_id, message_id)
        elif data == "ssh":
            _ssh_menu(token, chat_id, message_id)
        elif head == "ssh_t":
            _instance_list(token, chat_id, message_id, int(parts[1]), prefix="ssh_i")
        elif head == "ssh_i":
            _ssh_connect(token, chat_id, message_id, parts[1])
        elif data == "ssh_off":
            _ssh_disconnect(token, chat_id, message_id)
        elif data == "mfa":
            _mfa_menu(token, chat_id, message_id)
        elif data == "mfa_on":
            _mfa_on(token, chat_id, message_id)
        elif data == "mfa_off":
            _mfa_off(token, chat_id, message_id)
        elif data == "vnc":
            _vnc_menu(token, chat_id, message_id)
        elif data == "vnc_set":
            sess = _session(chat_id)
            sess["awaiting"] = "vnc_set"
            _send(token, chat_id, "请回复 VNC URL（以 http:// 或 https:// 开头），或发送 /exit 取消。")
        elif data == "vnc_clear":
            _set_setting(VNC_URL, "")
            _audit("tg.vnc_clear", "TG 机器人清除 VNC URL")
            _send(token, chat_id, "VNC URL 已清除。")
        elif data == "backup":
            _backup_menu(token, chat_id, message_id)
        elif data == "bk_exp":
            _backup_export(token, chat_id)
        elif data == "bk_imp":
            sess = _session(chat_id)
            sess["awaiting"] = "backup_import"
            _send(token, chat_id, "请直接发送 .bin 备份文件，或发送 /exit 取消。")
        elif data == "ipbl":
            _ipbl_menu(token, chat_id, message_id)
        elif data == "ipbl_add":
            sess = _session(chat_id)
            sess["awaiting"] = "ipbl_add"
            _send(token, chat_id, "请回复要拉黑的 IP 或 CIDR（如 1.2.3.4 或 1.2.3.0/24），或发送 /exit 取消。")
        elif head == "ipbl_del":
            payload = _get_ref(chat_id, parts[1]) or {}
            entries = _ip_blacklist()
            if payload.get("entry") in entries:
                entries.remove(payload["entry"])
                _save_ip_blacklist(entries)
                _audit("tg.ip_blacklist_del", f"TG 机器人移除 IP 黑名单 {payload['entry']}")
                _send(token, chat_id, f"✅ 已移除：{payload['entry']}")
        elif data == "ipbl_clear":
            kb = _kb([[("✅ 确认清空", "ipbl_clear_do"), ("❌ 取消", "menu")]])
            _send(token, chat_id, "确认清空全部 IP 黑名单？", kb)
        elif data == "ipbl_clear_do":
            if _write_blocked(token, chat_id):
                return True
            _save_ip_blacklist([])
            _audit("tg.ip_blacklist_clear", "TG 机器人清空 IP 黑名单")
            _send(token, chat_id, "✅ 黑名单已清空。")
        elif data == "defense":
            _defense_menu(token, chat_id, message_id)
        elif data == "def_on":
            kb = _kb([[("✅ 确认开启", "def_on_do"), ("❌ 取消", "menu")]])
            _send(token, chat_id,
                  "⚠️ 开启防御模式后，所有 IP 都无法登录面板，TG 写操作也会冻结，只能从 TG 关闭。确认开启？", kb)
        elif data == "def_on_do":
            _defense_set(token, chat_id, True)
        elif data == "def_off":
            _defense_set(token, chat_id, False)
        elif data == "create":
            _create_tenant_pick(token, chat_id, message_id)
        elif head == "create_t":
            _create_plan_pick(token, chat_id, message_id, int(parts[1]))
        elif head == "create_p":
            _create_ad_pick(token, chat_id, message_id, parts[1])
        elif head == "create_ad":
            _create_img_pick(token, chat_id, message_id, int(parts[1]))
        elif head == "create_img":
            _create_sn_pick(token, chat_id, message_id, int(parts[1]))
        elif head == "create_sn":
            _create_ssh_ask(token, chat_id, message_id, int(parts[1]))
        elif data == "create_go":
            _create_go(token, chat_id, message_id)
        else:
            return False
        return True
    except Exception as exc:
        log.exception("TG 菜单回调处理失败: %s", data)
        _send(token, chat_id, f"操作失败：{_esc(str(exc))[:200]}")
        return True
