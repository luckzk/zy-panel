"""元数据路由：Region / Compartment / AD / Shape / 镜像 / 子网下拉选项。

全部来自 OCI SDK 或实时接口，不写死。"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import meta_service
from ..services.instance_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/meta", tags=["元数据"])


def _tenant_or_404(db: Session, tenant_id: int) -> models.Tenant | None:
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()


@router.get("/regions", summary="全部商业 Region（OCI SDK 权威列表）")
def get_regions(_user: models.User = Depends(get_current_user)):
    """无需租户。返回 [{id}]，前端按中文名映射展示。"""
    return ok(meta_service.list_regions())


def _wrap(fn, *args):
    try:
        return ok(fn(*args))
    except OciApiError as e:
        return err(e.code, e.message, e.http_status)


@router.get("/compartments", summary="Compartment 列表（实时）")
def get_compartments(
    tenant_id: int = Query(description="租户 ID"),
    compartment_id: str | None = Query(default=None, description="父 Compartment OCID（默认租户根）"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_compartments, t, compartment_id)


@router.get("/availability-domains", summary="可用域 AD 列表（实时）")
def get_availability_domains(
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_availability_domains, t)


@router.get("/shapes", summary="Shape 列表（实时）")
def get_shapes(
    tenant_id: int = Query(description="租户 ID"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根）"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_shapes, t, compartment_id)


@router.get("/images", summary="镜像列表（实时）")
def get_images(
    tenant_id: int = Query(description="租户 ID"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根）"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_images, t, compartment_id)


@router.get("/subnets", summary="子网列表（实时）")
def get_subnets(
    tenant_id: int = Query(description="租户 ID"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根）"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_subnets, t, compartment_id)


@router.get("/boot-volumes", summary="引导卷列表（实时，供从现有引导卷抢机）")
def get_boot_volumes(
    tenant_id: int = Query(description="租户 ID"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根）"),
    availability_domain: str | None = Query(default=None, description="可用域（可选，从引导卷起实例必须同 AD）"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t = _tenant_or_404(db, tenant_id)
    if not t:
        return err(1004, "租户不存在", 404)
    return _wrap(meta_service.list_boot_volumes, t, compartment_id, availability_domain)
