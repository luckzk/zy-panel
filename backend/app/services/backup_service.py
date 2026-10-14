"""加密备份服务：全表导出 / Fernet 加密 / 解密 / 恢复。

备份文件格式（加密前）：
{
  "meta": {"app": "oci-panel", "version": "0.1.0", "exported_at": "<iso8601>"},
  "tables": {"users": [...], "tenants": [...], ...}
}
每行是列名 -> 值的 dict，datetime 已转 isoformat 字符串。
"""
import json
import logging
import os
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import DateTime, inspect
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db import models

log = logging.getLogger(__name__)

# 导出/恢复的表顺序：被外键引用的表在前，便于恢复时重建 id 映射
_TABLES: list[tuple[str, type]] = [
    ("users", models.User),
    ("tenants", models.Tenant),
    ("notification_configs", models.NotificationConfig),
    ("dns_records", models.DnsRecord),
    ("system_settings", models.SystemSetting),
    ("snatch_tasks", models.SnatchTask),
    ("ip_tasks", models.IpTask),
    ("operation_logs", models.OperationLog),
]

_TABLE_MAP = dict(_TABLES)

BACKUP_VERSION = "0.1.0"


def _get_fernet() -> Fernet:
    """备份加解密用的 Fernet（与 oci_factory 的实现一致，独立一份不互相依赖）。"""
    key = get_settings().fernet_key or os.getenv("FERNET_KEY")
    if not key:
        log.warning("未设置 FERNET_KEY，已生成临时密钥（重启后备份文件将无法解密）！")
        return Fernet(Fernet.generate_key())
    return Fernet(key.encode() if isinstance(key, str) else key)


def _serialize_row(model_cls: type, row) -> dict:
    cols = inspect(model_cls).columns.keys()
    out = {}
    for name in cols:
        v = getattr(row, name)
        out[name] = v.isoformat() if isinstance(v, datetime) else v
    return out


def export_all(db: Session) -> dict:
    """导出全部表，返回 JSON 可序列化的 dict。"""
    tables = {}
    for name, model_cls in _TABLES:
        rows = db.query(model_cls).all()
        tables[name] = [_serialize_row(model_cls, r) for r in rows]
    return {
        "meta": {
            "app": "oci-panel",
            "version": BACKUP_VERSION,
            "exported_at": datetime.now().isoformat(),
        },
        "tables": tables,
    }


def encrypt_payload(data: dict) -> bytes:
    """dict -> JSON -> Fernet 加密，返回可直接落盘的 bytes。"""
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
    return _get_fernet().encrypt(raw)


def decrypt_payload(raw: bytes) -> dict:
    """解密备份文件并解析 JSON，失败抛 ValueError。"""
    try:
        plain = _get_fernet().decrypt(raw)
        data = json.loads(plain.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("备份文件无效或密钥不匹配") from exc
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise ValueError("备份文件无效或密钥不匹配")
    return data


def _coerce_row(model_cls: type, row: dict) -> dict:
    """把备份行转回模型构造参数：未知列丢弃，datetime 字符串解析。"""
    cols = inspect(model_cls).columns
    out = {}
    for name, value in row.items():
        if name not in cols:
            continue
        if value is None:
            out[name] = None
            continue
        if isinstance(cols[name].type, DateTime) and isinstance(value, str):
            try:
                out[name] = datetime.fromisoformat(value)
            except ValueError:
                log.warning("无法解析 datetime 列 %s=%r，已置空", name, value)
                out[name] = None
        else:
            out[name] = value
    return out


def import_all(db: Session, data: dict) -> dict[str, int]:
    """按表恢复备份。

    - users：password_hash 为空的行跳过；按 username 去重（已存在跳过）
    - tenants：按 name 去重（已存在跳过）
    - system_settings：按 key 去重（key 是主键，已存在跳过）
    - 其余表：去掉 id 后直接插入（自增主键，避免冲突）
    - 外键（snatch_tasks/ip_tasks.tenant_id、operation_logs.user_id）按新旧 id
      映射重建；引用目标不存在的行跳过
    返回 {表名: 恢复行数}。
    """
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise ValueError("备份数据格式错误")
    tables: dict = data["tables"]

    counts: dict[str, int] = {}
    user_id_map: dict[int, int | None] = {}
    tenant_id_map: dict[int, int] = {}

    def _rows(name: str) -> list:
        rows = tables.get(name) or []
        return rows if isinstance(rows, list) else []

    def _insert(model_cls: type, kwargs: dict):
        obj = model_cls(**kwargs)
        db.add(obj)
        db.flush()  # 拿到自增 id
        return obj

    # ---- users ----
    n = 0
    for row in _rows("users"):
        old_id = row.get("id")
        kw = _coerce_row(models.User, row)
        kw.pop("id", None)
        if not kw.get("password_hash"):
            log.info("跳过无 password_hash 的用户行: %r", kw.get("username"))
            if old_id is not None:
                user_id_map[old_id] = None
            continue
        existing = db.query(models.User).filter(models.User.username == kw["username"]).first()
        if existing:
            if old_id is not None:
                user_id_map[old_id] = existing.id
            continue
        obj = _insert(models.User, kw)
        if old_id is not None:
            user_id_map[old_id] = obj.id
        n += 1
    counts["users"] = n

    # ---- tenants ----
    n = 0
    for row in _rows("tenants"):
        old_id = row.get("id")
        kw = _coerce_row(models.Tenant, row)
        kw.pop("id", None)
        existing = db.query(models.Tenant).filter(models.Tenant.name == kw["name"]).first()
        if existing:
            if old_id is not None:
                tenant_id_map[old_id] = existing.id
            continue
        obj = _insert(models.Tenant, kw)
        if old_id is not None:
            tenant_id_map[old_id] = obj.id
        n += 1
    counts["tenants"] = n

    # ---- notification_configs / dns_records：直接插入 ----
    for tname in ("notification_configs", "dns_records"):
        model_cls = _TABLE_MAP[tname]
        n = 0
        for row in _rows(tname):
            kw = _coerce_row(model_cls, row)
            kw.pop("id", None)
            _insert(model_cls, kw)
            n += 1
        counts[tname] = n

    # ---- system_settings：按 key 去重（key 是主键）----
    n = 0
    for row in _rows("system_settings"):
        kw = _coerce_row(models.SystemSetting, row)
        if not kw.get("key"):
            continue
        if db.query(models.SystemSetting).filter(models.SystemSetting.key == kw["key"]).first():
            continue
        _insert(models.SystemSetting, kw)
        n += 1
    counts["system_settings"] = n

    # ---- snatch_tasks / ip_tasks：重建 tenant_id 外键 ----
    for tname in ("snatch_tasks", "ip_tasks"):
        model_cls = _TABLE_MAP[tname]
        n = 0
        for row in _rows(tname):
            kw = _coerce_row(model_cls, row)
            kw.pop("id", None)
            old_tid = kw.get("tenant_id")
            if old_tid not in tenant_id_map:
                log.warning("跳过 %s 行：租户 id %r 在备份中不存在", tname, old_tid)
                continue
            kw["tenant_id"] = tenant_id_map[old_tid]
            _insert(model_cls, kw)
            n += 1
        counts[tname] = n

    # ---- operation_logs：重建 user_id 外键（可空）----
    n = 0
    for row in _rows("operation_logs"):
        kw = _coerce_row(models.OperationLog, row)
        kw.pop("id", None)
        old_uid = kw.get("user_id")
        if old_uid is not None:
            if old_uid not in user_id_map:
                log.warning("跳过 operation_logs 行：用户 id %r 在备份中不存在", old_uid)
                continue
            kw["user_id"] = user_id_map[old_uid]
        _insert(models.OperationLog, kw)
        n += 1
    counts["operation_logs"] = n

    db.commit()
    return counts
