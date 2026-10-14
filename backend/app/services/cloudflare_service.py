"""Cloudflare DNS 同步服务。

- API Token 加密存 system_settings（key="cloudflare_api_token"，is_secret=True，
  value 经 Fernet 加密），Fernet key 取自 settings.fernet_key。
- 封装 Cloudflare v4 DNS API：单条同步（创建/更新）、删除、整 zone 拉取。
- sync_record_to_cloudflare(db, record) 是换 IP worker 调用的入口，签名保持稳定。
"""
import logging
import os
from functools import lru_cache

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..db import models

log = logging.getLogger(__name__)

CF_API_BASE = "https://api.cloudflare.com/client/v4"
TOKEN_SETTING_KEY = "cloudflare_api_token"


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    """与 oci_factory 独立的 Fernet 实例（不改动 oci_factory）。"""
    key = get_settings().fernet_key or os.getenv("FERNET_KEY")
    if not key:
        log.warning("未设置 FERNET_KEY，已生成临时密钥（重启后旧数据无法解密）！")
        return Fernet(Fernet.generate_key())
    return Fernet(key.encode() if isinstance(key, str) else key)


class CloudflareApiError(Exception):
    """Cloudflare v4 API 调用失败。"""


def set_token(db: Session, token: str) -> None:
    """保存（加密）Cloudflare API Token。"""
    cipher = _get_fernet().encrypt(token.encode()).decode()
    row = db.get(models.SystemSetting, TOKEN_SETTING_KEY)
    if row is None:
        row = models.SystemSetting(key=TOKEN_SETTING_KEY, value=cipher, is_secret=True)
        db.add(row)
    else:
        row.value = cipher
        row.is_secret = True
    db.commit()


def has_token(db: Session) -> bool:
    """是否已配置 Token（不解密）。"""
    row = db.get(models.SystemSetting, TOKEN_SETTING_KEY)
    return row is not None and bool(row.value)


def get_token(db: Session) -> str:
    """解密返回 Token；未配置时抛 ValueError。"""
    row = db.get(models.SystemSetting, TOKEN_SETTING_KEY)
    if row is None or not row.value:
        raise ValueError("未配置 Cloudflare API Token")
    try:
        return _get_fernet().decrypt(row.value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Cloudflare Token 解密失败：FERNET_KEY 与加密时不一致") from exc


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=CF_API_BASE,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=20.0,
    )


def _check(resp: httpx.Response, action: str):
    """校验 Cloudflare 响应 success 字段，失败抛 CloudflareApiError。"""
    try:
        payload = resp.json()
    except Exception as exc:
        raise CloudflareApiError(f"{action}失败：返回非 JSON（HTTP {resp.status_code}）") from exc
    if not payload.get("success"):
        errors = payload.get("errors") or []
        detail = "; ".join(f"[{e.get('code')}] {e.get('message')}" for e in errors)
        raise CloudflareApiError(f"{action}失败：{detail or f'HTTP {resp.status_code}'}")
    return payload.get("result")


def _get_zone_id(client: httpx.Client, zone_name: str) -> str:
    resp = client.get("/zones", params={"name": zone_name})
    zones = _check(resp, f"查询 zone({zone_name})")
    if not zones:
        raise CloudflareApiError(f"未找到 zone：{zone_name}，请确认域名已接入 Cloudflare")
    return zones[0]["id"]


def sync_record_to_cloudflare(db: Session, record: models.DnsRecord) -> models.DnsRecord:
    """同步单条本地记录到 Cloudflare（存在则更新，不存在则创建），回填 cf_record_id 落库。

    换 IP worker 的调用入口，签名保持稳定。
    token 未配置时抛 ValueError("未配置 Cloudflare API Token")。
    """
    token = get_token(db)  # 未配置直接抛 ValueError
    payload = {
        "type": record.type,
        "name": record.name,
        "content": record.content,
        "ttl": record.ttl,
        "proxied": bool(record.proxied),
    }
    with _client(token) as client:
        zone_id = _get_zone_id(client, record.zone_name)
        record_id = record.cf_record_id
        if record_id:
            try:
                result = _check(
                    client.put(f"/zones/{zone_id}/dns_records/{record_id}", json=payload),
                    "更新 DNS 记录",
                )
            except CloudflareApiError as exc:
                # 远端记录可能已被手动删除：降级为重新创建
                log.warning("远端记录 %s 更新失败，尝试重新创建：%s", record_id, exc)
                record_id = None
        if not record_id:
            # 按 name+type 先查，避免重复创建
            resp = client.get(
                f"/zones/{zone_id}/dns_records",
                params={"name": record.name, "type": record.type},
            )
            existing = _check(resp, "查询 DNS 记录")
            if existing:
                result = _check(
                    client.put(f"/zones/{zone_id}/dns_records/{existing[0]['id']}", json=payload),
                    "更新 DNS 记录",
                )
            else:
                result = _check(
                    client.post(f"/zones/{zone_id}/dns_records", json=payload),
                    "创建 DNS 记录",
                )
        record.cf_record_id = result["id"]
        # 以远端返回为准回填
        record.content = result.get("content", record.content)
        record.ttl = result.get("ttl", record.ttl)
        record.proxied = bool(result.get("proxied", record.proxied))
        db.commit()
        db.refresh(record)
    log.info("DNS 记录 %s(%s) 已同步到 Cloudflare", record.name, record.type)
    return record


def delete_remote_record(db: Session, record: models.DnsRecord) -> bool:
    """删除远端记录；无 cf_record_id 时返回 False。远端已不存在视为成功。"""
    token = get_token(db)
    if not record.cf_record_id:
        return False
    with _client(token) as client:
        zone_id = _get_zone_id(client, record.zone_name)
        resp = client.delete(f"/zones/{zone_id}/dns_records/{record.cf_record_id}")
        try:
            _check(resp, "删除 DNS 记录")
        except CloudflareApiError as exc:
            if resp.status_code == 404 or "81044" in str(exc):
                log.info("远端记录 %s 已不存在，视为删除成功", record.cf_record_id)
            else:
                raise
    return True


def fetch_remote_records(db: Session, zone_name: str) -> list[dict]:
    """拉取 zone 下全部 DNS 记录（自动翻页），返回本地字段格式的 dict 列表。"""
    token = get_token(db)
    out: list[dict] = []
    with _client(token) as client:
        zone_id = _get_zone_id(client, zone_name)
        page = 1
        while True:
            resp = client.get(
                f"/zones/{zone_id}/dns_records",
                params={"per_page": 100, "page": page},
            )
            raw = resp.json()
            items = _check(resp, "拉取 DNS 记录")
            for it in items:
                out.append(
                    {
                        "zone_name": zone_name,
                        "name": it["name"],
                        "type": it["type"],
                        "content": it.get("content", ""),
                        "ttl": it.get("ttl", 1),
                        "proxied": bool(it.get("proxied", False)),
                        "cf_record_id": it["id"],
                    }
                )
            info = raw.get("result_info") or {}
            if page >= info.get("total_pages", 1):
                break
            page += 1
    return out
