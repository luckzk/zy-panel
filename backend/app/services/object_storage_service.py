"""对象存储服务：真实 OCI Object Storage 调用。"""
import logging

import oci
from oci.exceptions import ConnectTimeout, ServiceError

from . import oci_factory

log = logging.getLogger(__name__)


class OciApiError(Exception):
    """可直接映射为接口错误码的 OCI 调用异常。"""

    def __init__(self, code: int, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _translate(exc: ServiceError, op: str) -> OciApiError:
    """把 OCI ServiceError 翻译为面向用户的错误码（与其他 service 保持一致）。"""
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    if status == 409:
        return OciApiError(3103, f"{op}失败：资源冲突 ({exc.code}) {exc.message}", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {exc.message}", 502)


def _client(tenant):
    try:
        return oci_factory.get_object_storage_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502) from exc


def get_namespace(tenant) -> str:
    """获取租户的对象存储 namespace。"""
    client = _client(tenant)
    try:
        return client.get_namespace().data
    except (ConnectTimeout,) as exc:
        raise OciApiError(3104, f"获取 namespace 超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "获取 namespace") from exc


def list_buckets(tenant, compartment_id: str) -> list[dict]:
    """列出 compartment 下的所有 bucket。"""
    client = _client(tenant)
    try:
        ns = client.get_namespace().data
        buckets = client.list_buckets(ns, compartment_id).data or []
        return [
            {
                "name": b.name,
                "created": b.time_created.isoformat() if getattr(b, "time_created", None) else None,
            }
            for b in buckets
        ]
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询 Bucket 列表超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询 Bucket 列表") from exc


def create_bucket(tenant, compartment_id: str, name: str) -> dict:
    """创建 bucket。"""
    client = _client(tenant)
    try:
        ns = client.get_namespace().data
        details = oci.object_storage.models.CreateBucketDetails(name=name, compartment_id=compartment_id)
        b = client.create_bucket(ns, details).data
        return {"name": b.name, "created": b.time_created.isoformat() if getattr(b, "time_created", None) else None}
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"创建 Bucket 超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "创建 Bucket") from exc


def delete_bucket(tenant, namespace: str, name: str) -> dict:
    """删除 bucket（OCI 要求 bucket 为空，非空会报 409 并转为友好错误）。"""
    client = _client(tenant)
    try:
        client.delete_bucket(namespace, name)
        return {"name": name, "deleted": True}
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"删除 Bucket 超时：{exc}", 502) from exc
    except ServiceError as exc:
        if (exc.status or 0) == 409:
            raise OciApiError(3103, "删除失败：Bucket 非空，请先删除其中的对象", 502) from exc
        raise _translate(exc, "删除 Bucket") from exc


def list_objects(tenant, namespace: str, bucket: str, prefix: str = "", limit: int = 100) -> list[dict]:
    """列出 bucket 中的对象（支持前缀过滤）。"""
    client = _client(tenant)
    try:
        resp = client.list_objects(namespace, bucket, prefix=prefix or None, limit=min(max(limit, 1), 1000))
        objects = (resp.data.objects or []) if resp.data else []
        return [
            {
                "name": o.name,
                "size": o.size or 0,
                "time_created": o.time_created.isoformat() if getattr(o, "time_created", None) else None,
            }
            for o in objects
        ]
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询对象列表超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询对象列表") from exc


def upload_object(tenant, namespace: str, bucket: str, object_name: str, data: bytes) -> dict:
    """上传对象（put_object）。"""
    client = _client(tenant)
    try:
        client.put_object(namespace, bucket, object_name, data)
        return {"name": object_name, "size": len(data)}
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"上传对象超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "上传对象") from exc


def download_object(tenant, namespace: str, bucket: str, object_name: str) -> bytes:
    """下载对象，返回字节内容。"""
    client = _client(tenant)
    try:
        resp = client.get_object(namespace, bucket, object_name)
        raw = resp.data.raw
        # raw 可能是 stream 或 bytes
        if hasattr(raw, "stream"):
            chunks = [chunk for chunk in raw.stream(1024 * 1024, decode_content=False)]
            return b"".join(chunks)
        if isinstance(raw, (bytes, bytearray)):
            return bytes(raw)
        return raw.read()
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"下载对象超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "下载对象") from exc


def delete_object(tenant, namespace: str, bucket: str, object_name: str) -> dict:
    """删除对象。"""
    client = _client(tenant)
    try:
        client.delete_object(namespace, bucket, object_name)
        return {"name": object_name, "deleted": True}
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"删除对象超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "删除对象") from exc


# ---------------- 预签名 URL / 版本控制 / 生命周期 ----------------

def create_preauthenticated_url(tenant, namespace: str, bucket: str,
                                object_name: str, expires_hours: int = 24,
                                access_type: str = "ObjectRead") -> dict:
    """创建预签名 URL（限时可分享的下载链接，无需登录）。

    access_type: ObjectRead / ObjectWrite / ObjectReadWrite / AnyObjectWrite
    """
    from datetime import datetime, timedelta, timezone
    client = _client(tenant)
    try:
        details = oci.object_storage.models.CreatePreauthenticatedRequestDetails(
            name=f"panel-{object_name[:32]}",
            object_name=object_name or None,
            access_type=access_type,
            time_expires=datetime.now(timezone.utc) + timedelta(hours=max(expires_hours, 1)),
        )
        par = client.create_preauthenticated_request(namespace, bucket, details).data
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"创建预签名 URL 超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "创建预签名 URL") from exc
    region = getattr(tenant, "region", "") or ""
    url = f"https://objectstorage.{region}.oraclecloud.com{par.full_path}" if region else par.full_path
    return {
        "id": par.id, "name": par.name, "url": url,
        "access_type": par.access_type,
        "time_expires": par.time_expires.isoformat() if par.time_expires else None,
    }


def list_preauthenticated_requests(tenant, namespace: str, bucket: str) -> list[dict]:
    """列出 bucket 的预签名请求。"""
    client = _client(tenant)
    try:
        items = client.list_preauthenticated_requests(namespace, bucket).data or []
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询预签名 URL 超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询预签名 URL") from exc
    region = getattr(tenant, "region", "") or ""
    return [
        {
            "id": p.id, "name": p.name, "object_name": p.object_name,
            "access_type": p.access_type,
            "url": f"https://objectstorage.{region}.oraclecloud.com{p.full_path}" if region else p.full_path,
            "time_created": p.time_created.isoformat() if p.time_created else None,
            "time_expires": p.time_expires.isoformat() if p.time_expires else None,
        }
        for p in items
    ]


def delete_preauthenticated_request(tenant, namespace: str, bucket: str, par_id: str) -> dict:
    """删除（吊销）预签名 URL。"""
    client = _client(tenant)
    try:
        client.delete_preauthenticated_request(namespace, bucket, par_id)
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"删除预签名 URL 超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "删除预签名 URL") from exc
    return {"id": par_id, "deleted": True}


def get_bucket_detail(tenant, namespace: str, bucket: str) -> dict:
    """桶详情（含版本控制状态、公开访问类型）。"""
    client = _client(tenant)
    try:
        b = client.get_bucket(namespace, bucket).data
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询 Bucket 详情超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询 Bucket 详情") from exc
    return {
        "name": b.name, "namespace": b.namespace,
        "versioning": b.versioning or "Disabled",
        "public_access_type": b.public_access_type or "NoPublicAccess",
        "storage_tier": b.storage_tier,
        "auto_tiering": b.auto_tiering,
        "approximate_size": b.approximate_size,
        "approximate_count": b.approximate_count,
        "time_created": b.time_created.isoformat() if b.time_created else None,
    }


def set_bucket_versioning(tenant, namespace: str, bucket: str, enabled: bool) -> dict:
    """开关桶版本控制。"""
    client = _client(tenant)
    try:
        details = oci.object_storage.models.UpdateBucketDetails(
            versioning="Enabled" if enabled else "Suspended")
        client.update_bucket(namespace, bucket, details)
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"设置版本控制超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "设置 Bucket 版本控制") from exc
    return {"name": bucket, "versioning": "Enabled" if enabled else "Suspended"}


def get_lifecycle_policy(tenant, namespace: str, bucket: str) -> list[dict]:
    """查询桶生命周期规则（无规则时返回空列表，不抛错）。"""
    client = _client(tenant)
    try:
        policy = client.get_object_lifecycle_policy(namespace, bucket).data
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询生命周期规则超时：{exc}", 502) from exc
    except ServiceError as exc:
        if (exc.status or 0) == 404:
            return []
        raise _translate(exc, "查询生命周期规则") from exc
    return [
        {
            "name": r.name, "action": r.action, "is_enabled": r.is_enabled,
            "prefix": (r.object_name_filter or {}).get("prefix", "") if isinstance(r.object_name_filter, dict) else getattr(r.object_name_filter, "prefix", ""),
            "time_amount": r.time_amount, "time_unit": r.time_unit, "target": r.target,
        }
        for r in (policy.items or [])
    ]


def put_lifecycle_policy(tenant, namespace: str, bucket: str, rules: list[dict]) -> dict:
    """覆盖设置桶生命周期规则。

    rules 每项: {name, action: ARCHIVE|DELETE, prefix, days}
    """
    client = _client(tenant)
    items = []
    for r in rules or []:
        action = (r.get("action") or "ARCHIVE").upper()
        if action not in ("ARCHIVE", "DELETE"):
            raise OciApiError(3105, f"不支持的生命周期动作: {action}", 400)
        items.append(oci.object_storage.models.ObjectLifecycleRule(
            name=r.get("name") or f"rule-{action.lower()}",
            action=action,
            object_name_filter=oci.object_storage.models.ObjectNameFilter(prefix=r.get("prefix") or ""),
            time_amount=int(r.get("days") or 30),
            time_unit="DAYS",
            is_enabled=True,
        ))
    try:
        client.put_object_lifecycle_policy(
            namespace, bucket,
            oci.object_storage.models.PutObjectLifecyclePolicyDetails(items=items))
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"设置生命周期规则超时：{exc}", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "设置生命周期规则") from exc
    return {"name": bucket, "rules": len(items)}
