"""引导卷路由：列表/详情/扩容/救援（真实 OCI 调用）。"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import volume_service
from ..services.volume_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/volumes", tags=["引导卷"])


class ResizeIn(BaseModel):
    size_in_gbs: int


class RescueVolumeIn(BaseModel):
    tenant_id: int
    rescue_instance_id: str


class UnrescueVolumeIn(BaseModel):
    tenant_id: int


def _tenant_or_404(db: Session, tenant_id: int):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    return tenant


@router.get("", summary="引导卷列表（真实 OCI 查询）")
def list_volumes(
    tenant_id: int = Query(description="租户 ID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = volume_service.list_boot_volumes(tenant, compartment_id or tenant.tenancy_ocid)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询引导卷未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询引导卷失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})


@router.get("/block", summary="数据卷列表（真实 OCI 查询）")
def list_block_volumes(
    tenant_id: int = Query(description="租户 ID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = volume_service.list_block_volumes(tenant, compartment_id or tenant.tenancy_ocid)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询数据卷未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询数据卷失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})

@router.get("/{volume_id}", summary="引导卷详情（真实 OCI 查询）")
def get_volume(
    volume_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(volume_service.get_boot_volume(tenant, volume_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询引导卷详情未知异常 volume_id=%s", volume_id)
        return err(3100, f"查询引导卷详情失败：{str(exc)[:200]}", status=500)


@router.post("/{volume_id}/resize", summary="引导卷扩容（真实 OCI 调用）")
def resize_volume(
    volume_id: str,
    body: ResizeIn,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(volume_service.resize_boot_volume(tenant, volume_id, body.size_in_gbs))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("扩容引导卷未知异常 volume_id=%s", volume_id)
        return err(3100, f"扩容引导卷失败：{str(exc)[:200]}", status=500)


@router.post("/block/{volume_id}/resize", summary="数据卷扩容（真实 OCI 调用）")
def resize_block_volume(
    volume_id: str,
    body: ResizeIn,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(volume_service.resize_block_volume(tenant, volume_id, body.size_in_gbs))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("扩容数据卷未知异常 volume_id=%s", volume_id)
        return err(3100, f"扩容数据卷失败：{str(exc)[:200]}", status=500)


@router.post("/{volume_id}/rescue", summary="救援：挂载引导卷到救援实例")
def rescue_volume(
    volume_id: str,
    body: RescueVolumeIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(volume_service.rescue_boot_volume(tenant, volume_id, body.rescue_instance_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("救援引导卷未知异常 volume_id=%s", volume_id)
        return err(3100, f"救援引导卷失败：{str(exc)[:200]}", status=500)


@router.post("/{volume_id}/unrescue", summary="解除救援：卸载引导卷的全部挂载")
def unrescue_volume(
    volume_id: str,
    body: UnrescueVolumeIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(volume_service.unrescue_volume(tenant, volume_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("解除救援未知异常 volume_id=%s", volume_id)
        return err(3100, f"解除救援失败：{str(exc)[:200]}", status=500)
