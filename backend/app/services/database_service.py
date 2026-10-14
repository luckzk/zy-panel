"""数据库服务：Oracle Autonomous Database（自治数据库）管理。

全部走 oci.database.DatabaseClient 实时接口。Always Free 免费账号可创建
最多 2 个免费自治库（每库 20GB）。写操作记审计日志（由路由层记），
ADMIN 密码仅在请求中透传，绝不落库。
"""
import logging

import oci
from oci.exceptions import ServiceError

from ..db import models
from .instance_service import OciApiError, _paginate, _translate
from .oci_factory import get_database_client

log = logging.getLogger(__name__)

#: 自治库工作负载类型（中文名展示用）
WORKLOAD_CN = {
    "OLTP": "事务处理",
    "DW": "数据仓库",
    "AJD": "JSON 数据库",
    "APEX": "APEX 低代码",
}

#: 免费版允许的工作负载
FREE_TIER_WORKLOADS = ("OLTP", "DW", "AJD", "APEX")

#: 自治库名规则：1-14 字符，字母开头，只能字母数字
DB_NAME_MAX_LEN = 14


def _client(tenant: models.Tenant):
    return get_database_client(tenant)


def _summary(db) -> dict:
    cs = db.connection_strings or None
    return {
        "id": db.id,
        "display_name": db.display_name,
        "db_name": db.db_name,
        "db_workload": db.db_workload,
        "db_workload_cn": WORKLOAD_CN.get(db.db_workload, db.db_workload or ""),
        "db_version": db.db_version,
        "lifecycle_state": db.lifecycle_state,
        "lifecycle_details": db.lifecycle_details,
        "is_free_tier": bool(db.is_free_tier),
        "compute_model": db.compute_model,
        "compute_count": db.compute_count,
        "ocpu_count": db.ocpu_count,
        "data_storage_size_in_tbs": db.data_storage_size_in_tbs,
        "actual_used_data_storage_size_in_tbs": db.actual_used_data_storage_size_in_tbs,
        "allocated_storage_size_in_tbs": db.allocated_storage_size_in_tbs,
        "license_model": db.license_model,
        "time_created": db.time_created.isoformat() if db.time_created else None,
        "service_console_url": getattr(db, "service_console_url", None),
        "connection_strings": {
            "high": cs.profiles[0].value if cs and getattr(cs, "profiles", None) else None,
        } if cs else None,
    }


def list_databases(tenant: models.Tenant, compartment_id: str) -> list[dict]:
    """列出 compartment 下的自治数据库（含子 compartment 不做，只查本级）。"""
    client = _client(tenant)
    try:
        items = _paginate(client.list_autonomous_databases, compartment_id=compartment_id)
    except ServiceError as exc:
        raise _translate(exc, "查询自治数据库列表") from exc
    return [_summary(d) for d in items]


def get_database(tenant: models.Tenant, db_id: str) -> dict:
    """自治库详情（含连接串、控制台 URL）。"""
    client = _client(tenant)
    try:
        db = client.get_autonomous_database(db_id).data
    except ServiceError as exc:
        raise _translate(exc, "查询自治数据库详情") from exc
    d = _summary(db)
    cs = db.connection_strings
    if cs:
        profiles = {}
        for p in (getattr(cs, "profiles", None) or []):
            profiles[p.display_name or p.consumer_group or "default"] = p.value
        d["connection_profiles"] = profiles
        d["all_connection_strings"] = {
            k: v for k, v in vars(cs).items()
            if k not in ("swagger_types", "attribute_map") and isinstance(v, str) and v
        }
    return d


def create_database(
    tenant: models.Tenant,
    compartment_id: str,
    db_name: str,
    display_name: str,
    db_workload: str,
    admin_password: str,
    is_free_tier: bool = True,
    db_version: str = "26ai",
) -> dict:
    """创建自治数据库。免费版固定 is_free_tier=True、存储 1TB（实际可用 20GB）。

    注意：Always Free 库 CPU/存储不可扩缩，db_workload 仅限 OLTP/DW/AJD/APEX。
    """
    db_name = (db_name or "").strip().upper()
    if not (1 <= len(db_name) <= DB_NAME_MAX_LEN) or not db_name[0].isalpha() or not db_name.isalnum():
        raise OciApiError(4101, "库名须为 1-14 个字符、字母开头、仅含字母数字", 400)
    db_workload = (db_workload or "OLTP").upper()
    if is_free_tier and db_workload not in FREE_TIER_WORKLOADS:
        raise OciApiError(4102, f"免费版仅支持 {', '.join(FREE_TIER_WORKLOADS)} 四种工作负载", 400)
    if len(admin_password or "") < 12:
        raise OciApiError(4103, "ADMIN 密码至少 12 位（须含大小写字母、数字）", 400)

    client = _client(tenant)
    details = oci.database.models.CreateAutonomousDatabaseDetails(
        compartment_id=compartment_id,
        db_name=db_name,
        display_name=display_name or db_name,
        db_workload=db_workload,
        db_version=db_version,
        is_free_tier=is_free_tier,
        admin_password=admin_password,
        data_storage_size_in_tbs=1,
        license_model="LICENSE_INCLUDED" if not is_free_tier else None,
    )
    try:
        db = client.create_autonomous_database(details).data
    except ServiceError as exc:
        raise _translate(exc, "创建自治数据库") from exc
    return _summary(db)


def delete_database(tenant: models.Tenant, db_id: str) -> dict:
    client = _client(tenant)
    try:
        client.delete_autonomous_database(db_id)
    except ServiceError as exc:
        raise _translate(exc, "删除自治数据库") from exc
    return {"id": db_id, "deleted": True}


def start_database(tenant: models.Tenant, db_id: str) -> dict:
    client = _client(tenant)
    try:
        client.start_autonomous_database(db_id)
    except ServiceError as exc:
        raise _translate(exc, "启动自治数据库") from exc
    return {"id": db_id, "op": "start"}


def stop_database(tenant: models.Tenant, db_id: str) -> dict:
    client = _client(tenant)
    try:
        client.stop_autonomous_database(db_id)
    except ServiceError as exc:
        raise _translate(exc, "停止自治数据库") from exc
    return {"id": db_id, "op": "stop"}


def restart_database(tenant: models.Tenant, db_id: str) -> dict:
    client = _client(tenant)
    try:
        client.restart_autonomous_database(db_id)
    except ServiceError as exc:
        raise _translate(exc, "重启自治数据库") from exc
    return {"id": db_id, "op": "restart"}


def change_admin_password(tenant: models.Tenant, db_id: str, new_password: str) -> dict:
    """修改 ADMIN 密码（密码仅透传，不落库）。"""
    if len(new_password or "") < 12:
        raise OciApiError(4103, "ADMIN 密码至少 12 位（须含大小写字母、数字）", 400)
    client = _client(tenant)
    details = oci.database.models.UpdateAutonomousDatabaseDetails(admin_password=new_password)
    try:
        client.update_autonomous_database(db_id, details)
    except ServiceError as exc:
        raise _translate(exc, "修改数据库 ADMIN 密码") from exc
    return {"id": db_id, "password_changed": True}


def download_wallet(tenant: models.Tenant, db_id: str, wallet_password: str) -> bytes:
    """下载数据库连接 Wallet（zip 字节流），用于 SQL Developer / 客户端连接。"""
    if len(wallet_password or "") < 8:
        raise OciApiError(4104, "Wallet 密码至少 8 位", 400)
    client = _client(tenant)
    details = oci.database.models.GenerateAutonomousDatabaseWalletDetails(
        password=wallet_password, generate_type="SINGLE",
    )
    try:
        resp = client.generate_autonomous_database_wallet(db_id, details)
    except ServiceError as exc:
        raise _translate(exc, "下载数据库 Wallet") from exc
    data = resp.data
    if hasattr(data, "read"):
        return data.read()
    return bytes(data)
