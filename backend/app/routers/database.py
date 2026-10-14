"""数据库路由：Oracle Autonomous Database（自治数据库）管理。

全部为真实 OCI 调用。ADMIN / Wallet 密码仅在请求中透传，不落库。
"""
import io
import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import database_service
from ..services.instance_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/databases", tags=["数据库管理"])


def _need_tenant(db: Session, tenant_id: int):
    t = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if not t:
        return None, err(1004, "租户不存在", 404)
    return t, None


def _wrap(fn, *args):
    try:
        return ok(fn(*args))
    except OciApiError as e:
        return err(e.code, e.message, e.http_status)


def _audit(db: Session, user_id: int, action: str, detail: str = ""):
    try:
        write_log(db, user_id, action, detail)
    except Exception:  # noqa: BLE001
        log.warning("审计日志写入失败: %s", action, exc_info=True)


class CreateDbIn(BaseModel):
    tenant_id: int
    compartment_id: str
    db_name: str = Field(min_length=1, max_length=14, description="库名：1-14 字符，字母开头")
    display_name: str = ""
    db_workload: str = Field(default="OLTP", description="OLTP/DW/AJD/APEX")
    admin_password: str = Field(min_length=12, description="ADMIN 密码，至少 12 位")
    is_free_tier: bool = True
    db_version: str = "26ai"


class ChangePwdIn(BaseModel):
    new_password: str = Field(min_length=12)


class WalletIn(BaseModel):
    wallet_password: str = Field(min_length=8, description="Wallet 压缩包密码，至少 8 位")


@router.get("")
def list_dbs(tenant_id: int = Query(...), compartment_id: str = Query(""),
             db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(database_service.list_databases, t, compartment_id or t.tenancy_ocid)


@router.get("/{db_id}")
def get_db_detail(db_id: str, tenant_id: int = Query(...),
                  db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(database_service.get_database, t, db_id)


@router.post("")
def create_db(body: CreateDbIn, db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, body.tenant_id)
    if e:
        return e
    r = _wrap(database_service.create_database, t, body.compartment_id, body.db_name,
              body.display_name, body.db_workload, body.admin_password,
              body.is_free_tier, body.db_version)
    _audit(db, _user.id, "创建自治数据库", f"租户 {t.name} / 库 {body.db_name}（密码未记录）")
    return r


@router.delete("/{db_id}")
def delete_db(db_id: str, tenant_id: int = Query(...),
              db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(database_service.delete_database, t, db_id)
    _audit(db, _user.id, "删除自治数据库", f"租户 {t.name} / {db_id[:32]}…")
    return r


@router.post("/{db_id}/start")
def start_db(db_id: str, tenant_id: int = Query(...),
             db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(database_service.start_database, t, db_id)
    _audit(db, _user.id, "启动自治数据库", f"租户 {t.name} / {db_id[:32]}…")
    return r


@router.post("/{db_id}/stop")
def stop_db(db_id: str, tenant_id: int = Query(...),
            db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(database_service.stop_database, t, db_id)
    _audit(db, _user.id, "停止自治数据库", f"租户 {t.name} / {db_id[:32]}…")
    return r


@router.post("/{db_id}/restart")
def restart_db(db_id: str, tenant_id: int = Query(...),
               db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(database_service.restart_database, t, db_id)
    _audit(db, _user.id, "重启自治数据库", f"租户 {t.name} / {db_id[:32]}…")
    return r


@router.post("/{db_id}/change-password")
def change_pwd(db_id: str, body: ChangePwdIn, tenant_id: int = Query(...),
               db: Session = Depends(get_db), _user=Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(database_service.change_admin_password, t, db_id, body.new_password)
    _audit(db, _user.id, "修改自治数据库 ADMIN 密码", f"租户 {t.name} / {db_id[:32]}…（密码未记录）")
    return r


@router.post("/{db_id}/wallet")
def download_wallet(db_id: str, body: WalletIn, tenant_id: int = Query(...),
                    db: Session = Depends(get_db), _user=Depends(get_current_user)):
    """下载 Wallet zip（文件流）。"""
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    try:
        blob = database_service.download_wallet(t, db_id, body.wallet_password)
    except OciApiError as ex:
        return err(ex.code, ex.message, ex.http_status)
    _audit(db, _user.id, "下载自治数据库 Wallet", f"租户 {t.name} / {db_id[:32]}…")
    return StreamingResponse(
        io.BytesIO(blob), media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=wallet_{db_id[:8]}.zip"},
    )
