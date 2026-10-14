"""IAM 服务：OCI 用户 / API 密钥 / 用户组 / 令牌凭证 / MFA 设备管理。

全部走 oci.identity.IdentityClient 实时接口。危险操作（删用户、删密钥）
由路由层要求二次确认，前端弹窗警示。
"""
import logging

import oci
from oci.exceptions import ServiceError

from ..db import models
from .instance_service import OciApiError, _paginate, _translate
from .oci_factory import get_identity_client

log = logging.getLogger(__name__)


def _client(tenant: models.Tenant):
    return get_identity_client(tenant)


def _tenancy(tenant: models.Tenant) -> str:
    return tenant.tenancy_ocid


# ---------------- 用户 ----------------

def list_users(tenant: models.Tenant) -> list[dict]:
    client = _client(tenant)
    try:
        items = _paginate(client.list_users, compartment_id=_tenancy(tenant))
    except ServiceError as exc:
        raise _translate(exc, "查询用户列表") from exc
    return [
        {
            "id": u.id, "name": u.name, "description": u.description or "",
            "email": u.email or "", "lifecycle_state": u.lifecycle_state,
            "time_created": u.time_created.isoformat() if u.time_created else None,
            "is_mfa_activated": u.is_mfa_activated,
        }
        for u in items
    ]


def create_user(tenant: models.Tenant, name: str, description: str = "", email: str = "") -> dict:
    client = _client(tenant)
    details = oci.identity.models.CreateUserDetails(
        compartment_id=_tenancy(tenant), name=name,
        description=description or None, email=email or None,
    )
    try:
        resp = client.create_user(details)
    except ServiceError as exc:
        raise _translate(exc, "创建用户") from exc
    u = resp.data
    return {"id": u.id, "name": u.name, "lifecycle_state": u.lifecycle_state}


def update_user(tenant: models.Tenant, user_id: str, description: str = "", email: str = "") -> dict:
    client = _client(tenant)
    details = oci.identity.models.UpdateUserDetails(
        description=description or None, email=email or None,
    )
    try:
        resp = client.update_user(user_id, details)
    except ServiceError as exc:
        raise _translate(exc, "更新用户") from exc
    return {"id": resp.data.id, "name": resp.data.name}


def delete_user(tenant: models.Tenant, user_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_user(user_id)
    except ServiceError as exc:
        raise _translate(exc, "删除用户") from exc


# ---------------- API 密钥 ----------------

def list_api_keys(tenant: models.Tenant, user_id: str) -> list[dict]:
    client = _client(tenant)
    try:
        resp = client.list_api_keys(user_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 API 密钥") from exc
    return [
        {
            "fingerprint": k.fingerprint, "key_id": k.key_id,
            "time_created": k.time_created.isoformat() if k.time_created else None,
            "lifecycle_state": k.lifecycle_state,
        }
        for k in resp.data
    ]


def upload_api_key(tenant: models.Tenant, user_id: str, public_key_pem: str) -> dict:
    pem = public_key_pem.strip()
    if "BEGIN PUBLIC KEY" not in pem:
        raise OciApiError(3201, "公钥格式不正确，需要 PEM 格式的公钥（-----BEGIN PUBLIC KEY-----）", 400)
    client = _client(tenant)
    details = oci.identity.models.CreateApiKeyDetails(key=pem)
    try:
        resp = client.upload_api_key(user_id, details)
    except ServiceError as exc:
        raise _translate(exc, "上传 API 密钥") from exc
    return {"fingerprint": resp.data.fingerprint}


def delete_api_key(tenant: models.Tenant, user_id: str, fingerprint: str) -> None:
    client = _client(tenant)
    try:
        client.delete_api_key(user_id, fingerprint)
    except ServiceError as exc:
        raise _translate(exc, "删除 API 密钥") from exc


# ---------------- 用户组 ----------------

def list_groups(tenant: models.Tenant) -> list[dict]:
    client = _client(tenant)
    try:
        items = _paginate(client.list_groups, compartment_id=_tenancy(tenant))
    except ServiceError as exc:
        raise _translate(exc, "查询用户组") from exc
    return [
        {
            "id": g.id, "name": g.name, "description": g.description or "",
            "lifecycle_state": g.lifecycle_state,
            "time_created": g.time_created.isoformat() if g.time_created else None,
        }
        for g in items
    ]


def create_group(tenant: models.Tenant, name: str, description: str = "") -> dict:
    client = _client(tenant)
    details = oci.identity.models.CreateGroupDetails(
        compartment_id=_tenancy(tenant), name=name, description=description or None,
    )
    try:
        resp = client.create_group(details)
    except ServiceError as exc:
        raise _translate(exc, "创建用户组") from exc
    return {"id": resp.data.id, "name": resp.data.name}


def delete_group(tenant: models.Tenant, group_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_group(group_id)
    except ServiceError as exc:
        raise _translate(exc, "删除用户组") from exc


def list_group_members(tenant: models.Tenant, group_id: str) -> list[dict]:
    """某组的成员（返回 membership_id 供移除用）。"""
    client = _client(tenant)
    try:
        items = _paginate(
            client.list_user_group_memberships,
            compartment_id=_tenancy(tenant), group_id=group_id,
        )
    except ServiceError as exc:
        raise _translate(exc, "查询组成员") from exc
    return [
        {"membership_id": m.id, "user_id": m.user_id, "group_id": m.group_id,
         "lifecycle_state": m.lifecycle_state}
        for m in items if m.lifecycle_state == "ACTIVE"
    ]


def add_user_to_group(tenant: models.Tenant, user_id: str, group_id: str) -> dict:
    client = _client(tenant)
    details = oci.identity.models.AddUserToGroupDetails(
        compartment_id=_tenancy(tenant), group_id=group_id, user_id=user_id,
    )
    try:
        resp = client.add_user_to_group(details)
    except ServiceError as exc:
        raise _translate(exc, "添加组成员") from exc
    return {"membership_id": resp.data.id}


def remove_user_from_group(tenant: models.Tenant, membership_id: str) -> None:
    client = _client(tenant)
    try:
        client.remove_user_from_group(membership_id)
    except ServiceError as exc:
        raise _translate(exc, "移除组成员") from exc


# ---------------- Auth Token（对象存储等用） ----------------

def list_auth_tokens(tenant: models.Tenant, user_id: str) -> list[dict]:
    client = _client(tenant)
    try:
        resp = client.list_auth_tokens(user_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 Auth Token") from exc
    return [
        {"id": t.id, "description": t.description or "",
         "time_created": t.time_created.isoformat() if t.time_created else None,
         "time_expires": t.time_expires.isoformat() if t.time_expires else None,
         "lifecycle_state": t.lifecycle_state}
        for t in resp.data
    ]


def create_auth_token(tenant: models.Tenant, user_id: str, description: str = "") -> dict:
    """创建后 token 明文只返回一次，前端必须当场展示并提醒保存。"""
    client = _client(tenant)
    details = oci.identity.models.CreateAuthTokenDetails(description=description or None)
    try:
        resp = client.create_auth_token(details, user_id)
    except ServiceError as exc:
        raise _translate(exc, "创建 Auth Token") from exc
    return {"id": resp.data.id, "token": resp.data.token}


def delete_auth_token(tenant: models.Tenant, user_id: str, token_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_auth_token(user_id, token_id)
    except ServiceError as exc:
        raise _translate(exc, "删除 Auth Token") from exc


# ---------------- Customer Secret Key（S3 兼容密钥） ----------------

def list_customer_secret_keys(tenant: models.Tenant, user_id: str) -> list[dict]:
    client = _client(tenant)
    try:
        resp = client.list_customer_secret_keys(user_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 Customer Secret Key") from exc
    return [
        {"id": k.id, "display_name": k.display_name or "",
         "time_created": k.time_created.isoformat() if k.time_created else None,
         "time_expires": k.time_expires.isoformat() if k.time_expires else None,
         "lifecycle_state": k.lifecycle_state}
        for k in resp.data
    ]


def create_customer_secret_key(tenant: models.Tenant, user_id: str, display_name: str = "") -> dict:
    """key 明文只返回一次，前端必须当场展示并提醒保存。"""
    client = _client(tenant)
    details = oci.identity.models.CreateCustomerSecretKeyDetails(display_name=display_name or None)
    try:
        resp = client.create_customer_secret_key(details, user_id)
    except ServiceError as exc:
        raise _translate(exc, "创建 Customer Secret Key") from exc
    return {"id": resp.data.id, "key": resp.data.key}


def delete_customer_secret_key(tenant: models.Tenant, user_id: str, key_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_customer_secret_key(user_id, key_id)
    except ServiceError as exc:
        raise _translate(exc, "删除 Customer Secret Key") from exc


# ---------------- SMTP 凭证 ----------------

def list_smtp_credentials(tenant: models.Tenant, user_id: str) -> list[dict]:
    client = _client(tenant)
    try:
        resp = client.list_smtp_credentials(user_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 SMTP 凭证") from exc
    return [
        {"id": c.id, "username": c.username, "description": c.description or "",
         "time_created": c.time_created.isoformat() if c.time_created else None,
         "time_expires": c.time_expires.isoformat() if c.time_expires else None,
         "lifecycle_state": c.lifecycle_state}
        for c in resp.data
    ]


def create_smtp_credential(tenant: models.Tenant, user_id: str, description: str = "") -> dict:
    """password 明文只返回一次，前端必须当场展示并提醒保存。"""
    client = _client(tenant)
    details = oci.identity.models.CreateSmtpCredentialDetails(description=description or None)
    try:
        resp = client.create_smtp_credential(details, user_id)
    except ServiceError as exc:
        raise _translate(exc, "创建 SMTP 凭证") from exc
    return {"id": resp.data.id, "username": resp.data.username, "password": resp.data.password}


def delete_smtp_credential(tenant: models.Tenant, user_id: str, cred_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_smtp_credential(user_id, cred_id)
    except ServiceError as exc:
        raise _translate(exc, "删除 SMTP 凭证") from exc


# ---------------- MFA TOTP 设备 ----------------

def list_mfa_totp_devices(tenant: models.Tenant, user_id: str) -> list[dict]:
    client = _client(tenant)
    try:
        resp = client.list_mfa_totp_devices(user_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 MFA 设备") from exc
    return [
        {"id": d.id,
         "time_created": d.time_created.isoformat() if d.time_created else None,
         "lifecycle_state": d.lifecycle_state}
        for d in resp.data
    ]


def delete_mfa_totp_device(tenant: models.Tenant, user_id: str, device_id: str) -> None:
    client = _client(tenant)
    try:
        client.delete_mfa_totp_device(user_id, device_id)
    except ServiceError as exc:
        raise _translate(exc, "删除 MFA 设备") from exc
