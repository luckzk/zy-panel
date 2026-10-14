"""DNS 路由：Cloudflare DNS 记录本地 CRUD + 远端同步 + Token 配置。

- 本地 CRUD 落库后尝试远端同步；远端失败不回滚本地，返回 note 说明。
- Token 经 Fernet 加密存 system_settings，不回显。
"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import cloudflare_service
from ..services.cloudflare_service import CloudflareApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/dns", tags=["DNS"])


class DnsRecordCreate(BaseModel):
    zone_name: str
    name: str
    type: str = "A"
    content: str = ""
    ttl: int = 1
    proxied: bool = False


class DnsRecordUpdate(BaseModel):
    name: str | None = None
    type: str | None = None
    content: str | None = None
    ttl: int | None = None
    proxied: bool | None = None


class SyncIpIn(BaseModel):
    new_ip: str


class CloudflareTokenIn(BaseModel):
    api_token: str


class PullIn(BaseModel):
    zone_name: str


def _to_out(r: models.DnsRecord) -> dict:
    return {
        "id": r.id,
        "zone_name": r.zone_name,
        "name": r.name,
        "type": r.type,
        "content": r.content,
        "ttl": r.ttl,
        "proxied": r.proxied,
        "cf_record_id": r.cf_record_id,
    }


def _try_sync(db: Session, record: models.DnsRecord) -> str | None:
    """尝试同步到 Cloudflare；返回失败原因（成功返回 None）。"""
    try:
        cloudflare_service.sync_record_to_cloudflare(db, record)
        return None
    except ValueError as exc:  # 未配置 token 等
        log.info("DNS 记录 %s 未同步到 Cloudflare：%s", record.name, exc)
        return str(exc)
    except (CloudflareApiError, Exception) as exc:
        log.warning("DNS 记录 %s 同步到 Cloudflare 失败：%s", record.name, exc)
        return str(exc)


@router.get("/records", summary="DNS 记录列表")
def list_records(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    records = db.query(models.DnsRecord).order_by(models.DnsRecord.id.desc()).all()
    return ok([_to_out(r) for r in records])


@router.post("/records", summary="新增 DNS 记录（本地落库 + 尝试同步 Cloudflare）")
def create_record(body: DnsRecordCreate, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    record = models.DnsRecord(**body.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    fail = _try_sync(db, record)
    note = "已同步到 Cloudflare" if fail is None else f"已落库，同步到 Cloudflare 失败：{fail}"
    return ok({**_to_out(record), "note": note})


@router.put("/records/{record_id}", summary="更新 DNS 记录（本地 + 尝试同步 Cloudflare）")
def update_record(
    record_id: int,
    body: DnsRecordUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    record = db.get(models.DnsRecord, record_id)
    if record is None:
        return err(7001, "记录不存在", status=404)
    for key, value in body.model_dump(exclude_unset=True).items():
        setattr(record, key, value)
    db.commit()
    fail = _try_sync(db, record)
    note = "已同步到 Cloudflare" if fail is None else f"已更新本地，同步到 Cloudflare 失败：{fail}"
    return ok({**_to_out(record), "note": note})


@router.delete("/records/{record_id}", summary="删除 DNS 记录（本地 + 尝试删除远端）")
def delete_record(record_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    record = db.get(models.DnsRecord, record_id)
    if record is None:
        return err(7001, "记录不存在", status=404)
    remote_note = ""
    try:
        if cloudflare_service.has_token(db) and record.cf_record_id:
            cloudflare_service.delete_remote_record(db, record)
            remote_note = "，远端记录已删除"
    except (CloudflareApiError, ValueError, Exception) as exc:
        log.warning("删除远端 DNS 记录 %s 失败：%s", record.name, exc)
        remote_note = f"，删除远端记录失败：{exc}"
    db.delete(record)
    db.commit()
    return ok(msg=f"删除成功{remote_note}")


@router.post("/records/{record_id}/sync", summary="手动同步单条记录到 Cloudflare")
def sync_record(record_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    record = db.get(models.DnsRecord, record_id)
    if record is None:
        return err(7001, "记录不存在", status=404)
    try:
        cloudflare_service.sync_record_to_cloudflare(db, record)
    except ValueError as exc:
        return err(7003, str(exc), status=400)
    except CloudflareApiError as exc:
        return err(7002, f"Cloudflare 同步失败：{exc}", status=502)
    return ok({**_to_out(record), "note": "已同步到 Cloudflare"})


@router.post("/records/pull", summary="从 Cloudflare 拉取 zone 记录并落库（按 name+type 去重）")
def pull_records(body: PullIn, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    try:
        remote = cloudflare_service.fetch_remote_records(db, body.zone_name)
    except ValueError as exc:
        return err(7003, str(exc), status=400)
    except CloudflareApiError as exc:
        return err(7002, f"拉取失败：{exc}", status=502)
    created, updated = 0, 0
    for item in remote:
        local = (
            db.query(models.DnsRecord)
            .filter(
                models.DnsRecord.zone_name == item["zone_name"],
                models.DnsRecord.name == item["name"],
                models.DnsRecord.type == item["type"],
            )
            .first()
        )
        if local is None:
            db.add(models.DnsRecord(**item))
            created += 1
        else:
            local.content = item["content"]
            local.ttl = item["ttl"]
            local.proxied = item["proxied"]
            local.cf_record_id = item["cf_record_id"]
            updated += 1
    db.commit()
    return ok({"pulled": len(remote), "created": created, "updated": updated})


@router.post("/records/{record_id}/sync-after-ip-change", summary="换 IP 后更新 DNS（本地 + 同步 Cloudflare）")
def sync_after_ip_change(
    record_id: int,
    body: SyncIpIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """换 IP worker 的联动入口：本地更新 content 后同步到 Cloudflare。"""
    record = db.get(models.DnsRecord, record_id)
    if record is None:
        return err(7001, "记录不存在", status=404)
    record.content = body.new_ip
    db.commit()
    fail = _try_sync(db, record)
    note = "已同步到 Cloudflare" if fail is None else f"已更新本地，同步到 Cloudflare 失败：{fail}"
    return ok({**_to_out(record), "note": note})


@router.get("/settings/cloudflare", summary="Cloudflare Token 配置状态（不回显 token）")
def cf_status(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return ok({"configured": cloudflare_service.has_token(db)})


@router.put("/settings/cloudflare", summary="保存 Cloudflare API Token（加密存储）")
def cf_save_token(body: CloudflareTokenIn, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    token = (body.api_token or "").strip()
    if not token:
        return err(7004, "api_token 不能为空", status=400)
    cloudflare_service.set_token(db, token)
    return ok({"configured": True}, msg="Token 已保存（加密存储）")
