"""对象存储路由：Bucket 与对象的管理（真实 OCI 查询）。"""
import logging

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import object_storage_service
from ..services.object_storage_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/object-storage", tags=["对象存储"])

# 上传单文件上限 50MB
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


class BucketCreateIn(BaseModel):
    tenant_id: int
    compartment_id: str
    name: str


def _tenant_or_404(db: Session, tenant_id: int):
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()


def _handle(exc: OciApiError, op: str, tenant_id: int):
    return err(exc.code, exc.message, status=exc.http_status)


@router.get("/namespace", summary="获取对象存储 namespace")
def get_namespace(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok({"namespace": object_storage_service.get_namespace(tenant)})
    except OciApiError as exc:
        return _handle(exc, "namespace", tenant_id)
    except Exception as exc:
        log.exception("获取 namespace 未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"获取 namespace 失败：{str(exc)[:200]}", status=500)


@router.get("/buckets", summary="Bucket 列表（真实 OCI 查询）")
def list_buckets(
    tenant_id: int = Query(description="租户 ID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = object_storage_service.list_buckets(tenant, compartment_id or tenant.tenancy_ocid)
    except OciApiError as exc:
        return _handle(exc, "buckets", tenant_id)
    except Exception as exc:
        log.exception("查询 Bucket 未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询 Bucket 失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})


@router.post("/buckets", summary="创建 Bucket")
def create_bucket(
    body: BucketCreateIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if not body.name or not body.name.strip():
        return err(3002, "Bucket 名称不能为空", status=400)
    try:
        return ok(object_storage_service.create_bucket(tenant, body.compartment_id, body.name.strip()))
    except OciApiError as exc:
        return _handle(exc, "buckets", body.tenant_id)
    except Exception as exc:
        log.exception("创建 Bucket 未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, f"创建 Bucket 失败：{str(exc)[:200]}", status=500)


@router.delete("/buckets/{name}", summary="删除 Bucket（需为空）")
def delete_bucket(
    name: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.delete_bucket(tenant, namespace, name))
    except OciApiError as exc:
        return _handle(exc, "buckets", tenant_id)
    except Exception as exc:
        log.exception("删除 Bucket 未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"删除 Bucket 失败：{str(exc)[:200]}", status=500)


@router.get("/objects", summary="对象列表（真实 OCI 查询）")
def list_objects(
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    bucket: str = Query(description="Bucket 名称（必填）"),
    prefix: str = Query(default="", description="对象名前缀过滤"),
    limit: int = Query(default=100, ge=1, le=1000),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = object_storage_service.list_objects(tenant, namespace, bucket, prefix=prefix, limit=limit)
    except OciApiError as exc:
        return _handle(exc, "objects", tenant_id)
    except Exception as exc:
        log.exception("查询对象未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询对象失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})


@router.post("/objects/upload", summary="上传对象（单文件上限 50MB）")
async def upload_object(
    tenant_id: int = Form(description="租户 ID"),
    namespace: str = Form(description="namespace"),
    bucket: str = Form(description="Bucket 名称"),
    prefix: str = Form(default=""),
    file: UploadFile = File(description="上传文件"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if not file.filename:
        return err(3002, "未选择文件", status=400)
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return err(3002, f"文件过大：单文件上限 50MB（当前 {len(data) / 1024 / 1024:.1f}MB）", status=400)
    object_name = f"{prefix.rstrip('/')}/{file.filename}" if prefix else file.filename
    try:
        return ok(object_storage_service.upload_object(tenant, namespace, bucket, object_name, data))
    except OciApiError as exc:
        return _handle(exc, "objects", tenant_id)
    except Exception as exc:
        log.exception("上传对象未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"上传对象失败：{str(exc)[:200]}", status=500)


@router.get("/objects/download", summary="下载对象")
def download_object(
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    bucket: str = Query(description="Bucket 名称（必填）"),
    name: str = Query(description="对象名（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        data = object_storage_service.download_object(tenant, namespace, bucket, name)
    except OciApiError as exc:
        return _handle(exc, "objects", tenant_id)
    except Exception as exc:
        log.exception("下载对象未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"下载对象失败：{str(exc)[:200]}", status=500)
    filename = name.rsplit("/", 1)[-1] or "download"
    return StreamingResponse(
        iter([data]),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.delete("/objects", summary="删除对象")
def delete_object(
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    bucket: str = Query(description="Bucket 名称（必填）"),
    name: str = Query(description="对象名（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.delete_object(tenant, namespace, bucket, name))
    except OciApiError as exc:
        return _handle(exc, "objects", tenant_id)
    except Exception as exc:
        log.exception("删除对象未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"删除对象失败：{str(exc)[:200]}", status=500)


# ---------------- 预签名 URL / 版本控制 / 生命周期 ----------------

class ParCreateIn(BaseModel):
    tenant_id: int
    namespace: str
    bucket: str
    object_name: str = ""
    expires_hours: int = 24
    access_type: str = "ObjectRead"


class VersioningIn(BaseModel):
    tenant_id: int
    namespace: str
    bucket: str
    enabled: bool


class LifecycleRuleIn(BaseModel):
    name: str = ""
    action: str = "ARCHIVE"  # ARCHIVE | DELETE
    prefix: str = ""
    days: int = 30


class LifecycleIn(BaseModel):
    tenant_id: int
    namespace: str
    bucket: str
    rules: list[LifecycleRuleIn] = []


@router.post("/preauth", summary="创建预签名 URL（限时分享下载链接）")
def create_preauth(
    body: ParCreateIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.create_preauthenticated_url(
            tenant, body.namespace, body.bucket, body.object_name,
            body.expires_hours, body.access_type))
    except OciApiError as exc:
        return _handle(exc, "preauth", body.tenant_id)


@router.get("/preauth", summary="预签名 URL 列表")
def list_preauth(
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    bucket: str = Query(description="Bucket 名称（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.list_preauthenticated_requests(tenant, namespace, bucket))
    except OciApiError as exc:
        return _handle(exc, "preauth", tenant_id)


@router.delete("/preauth/{par_id}", summary="吊销预签名 URL")
def delete_preauth(
    par_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    bucket: str = Query(description="Bucket 名称（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.delete_preauthenticated_request(tenant, namespace, bucket, par_id))
    except OciApiError as exc:
        return _handle(exc, "preauth", tenant_id)


@router.get("/buckets/{name}/detail", summary="Bucket 详情（含版本控制状态）")
def bucket_detail(
    name: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.get_bucket_detail(tenant, namespace, name))
    except OciApiError as exc:
        return _handle(exc, "buckets", tenant_id)


@router.post("/buckets/{name}/versioning", summary="开关 Bucket 版本控制")
def set_versioning(
    name: str,
    body: VersioningIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.set_bucket_versioning(tenant, body.namespace, name, body.enabled))
    except OciApiError as exc:
        return _handle(exc, "buckets", body.tenant_id)


@router.get("/buckets/{name}/lifecycle", summary="查询 Bucket 生命周期规则")
def get_lifecycle(
    name: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    namespace: str = Query(description="namespace（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.get_lifecycle_policy(tenant, namespace, name))
    except OciApiError as exc:
        return _handle(exc, "lifecycle", tenant_id)


@router.put("/buckets/{name}/lifecycle", summary="设置 Bucket 生命周期规则（覆盖）")
def put_lifecycle(
    name: str,
    body: LifecycleIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(object_storage_service.put_lifecycle_policy(
            tenant, body.namespace, name, [r.model_dump() for r in body.rules]))
    except OciApiError as exc:
        return _handle(exc, "lifecycle", body.tenant_id)
