"""IAM 路由：OCI 用户 / API 密钥 / 用户组 / 令牌凭证 / MFA 设备管理（真实 OCI 调用）。

写操作全部记审计日志。删用户、删密钥等危险操作前端二次确认。
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import iam_service
from ..services.instance_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/iam", tags=["IAM 用户管理"])


def _tenant_or_404(db: Session, tenant_id: int) -> models.Tenant | None:
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()


def _need_tenant(db: Session, tenant_id: int):
    t = _tenant_or_404(db, tenant_id)
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
    except Exception:  # noqa: BLE001 审计失败不影响主流程
        log.warning("审计日志写入失败: %s", action, exc_info=True)


# ---------------- 用户 ----------------

class UserIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    email: str = ""


class UserUpdateIn(BaseModel):
    description: str = ""
    email: str = ""


@router.get("/users", summary="用户列表")
def list_users(
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(iam_service.list_users, t)


@router.post("/users", summary="创建用户")
def create_user(
    tenant_id: int = Query(description="租户 ID"),
    body: UserIn = ...,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.create_user, t, body.name, body.description, body.email)
    _audit(db, _user.id, "创建 IAM 用户", f"租户 {t.name} / 用户 {body.name}")
    return r


@router.put("/users/{user_id}", summary="更新用户（描述/邮箱）")
def update_user(
    user_id: str,
    tenant_id: int = Query(description="租户 ID"),
    body: UserUpdateIn = ...,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.update_user, t, user_id, body.description, body.email)
    _audit(db, _user.id, "更新 IAM 用户", f"租户 {t.name} / {user_id}")
    return r


@router.delete("/users/{user_id}", summary="删除用户（不可逆）")
def delete_user(
    user_id: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_user, t, user_id)
    _audit(db, _user.id, "删除 IAM 用户", f"租户 {t.name} / {user_id}")
    return r


# ---------------- API 密钥 ----------------

class ApiKeyIn(BaseModel):
    public_key_pem: str = Field(min_length=50, description="PEM 格式公钥")


@router.get("/users/{user_id}/api-keys", summary="某用户的 API 密钥列表")
def list_api_keys(
    user_id: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(iam_service.list_api_keys, t, user_id)


@router.post("/users/{user_id}/api-keys", summary="上传 API 公钥")
def upload_api_key(
    user_id: str,
    tenant_id: int = Query(description="租户 ID"),
    body: ApiKeyIn = ...,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.upload_api_key, t, user_id, body.public_key_pem)
    _audit(db, _user.id, "上传 IAM API 密钥", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.delete("/users/{user_id}/api-keys/{fingerprint}", summary="删除 API 密钥")
def delete_api_key(
    user_id: str,
    fingerprint: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_api_key, t, user_id, fingerprint)
    _audit(db, _user.id, "删除 IAM API 密钥", f"租户 {t.name} / 用户 {user_id} / {fingerprint[:16]}…")
    return r


# ---------------- 用户组 ----------------

class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""


class GroupMemberIn(BaseModel):
    user_id: str


@router.get("/groups", summary="用户组列表")
def list_groups(
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(iam_service.list_groups, t)


@router.post("/groups", summary="创建用户组")
def create_group(
    tenant_id: int = Query(description="租户 ID"),
    body: GroupIn = ...,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.create_group, t, body.name, body.description)
    _audit(db, _user.id, "创建 IAM 用户组", f"租户 {t.name} / 组 {body.name}")
    return r


@router.delete("/groups/{group_id}", summary="删除用户组")
def delete_group(
    group_id: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_group, t, group_id)
    _audit(db, _user.id, "删除 IAM 用户组", f"租户 {t.name} / {group_id}")
    return r


@router.get("/groups/{group_id}/members", summary="组成员列表")
def list_group_members(
    group_id: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(iam_service.list_group_members, t, group_id)


@router.post("/groups/{group_id}/members", summary="添加组成员")
def add_group_member(
    group_id: str,
    tenant_id: int = Query(description="租户 ID"),
    body: GroupMemberIn = ...,  # type: ignore[assignment]
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.add_user_to_group, t, body.user_id, group_id)
    _audit(db, _user.id, "添加 IAM 组成员", f"租户 {t.name} / 组 {group_id}")
    return r


@router.delete("/groups/{group_id}/members/{membership_id}", summary="移除组成员")
def remove_group_member(
    group_id: str,
    membership_id: str,
    tenant_id: int = Query(description="租户 ID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.remove_user_from_group, t, membership_id)
    _audit(db, _user.id, "移除 IAM 组成员", f"租户 {t.name} / 组 {group_id}")
    return r


# ---------------- 令牌与凭证 ----------------

class TokenIn(BaseModel):
    description: str = ""
    display_name: str = ""


def _cred_list(fn_name: str, db: Session, tenant_id: int, user_id: str):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    return _wrap(getattr(iam_service, fn_name), t, user_id)


@router.get("/users/{user_id}/auth-tokens", summary="Auth Token 列表")
def list_auth_tokens(user_id: str, tenant_id: int = Query(description="租户 ID"),
                     db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _cred_list("list_auth_tokens", db, tenant_id, user_id)


@router.post("/users/{user_id}/auth-tokens", summary="创建 Auth Token（明文只返回一次）")
def create_auth_token(user_id: str, tenant_id: int = Query(description="租户 ID"),
                      body: TokenIn = ...,  # type: ignore[assignment]
                      db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.create_auth_token, t, user_id, body.description)
    _audit(db, _user.id, "创建 IAM Auth Token", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.delete("/users/{user_id}/auth-tokens/{token_id}", summary="删除 Auth Token")
def delete_auth_token(user_id: str, token_id: str, tenant_id: int = Query(description="租户 ID"),
                      db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_auth_token, t, user_id, token_id)
    _audit(db, _user.id, "删除 IAM Auth Token", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.get("/users/{user_id}/secret-keys", summary="Customer Secret Key 列表")
def list_secret_keys(user_id: str, tenant_id: int = Query(description="租户 ID"),
                     db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _cred_list("list_customer_secret_keys", db, tenant_id, user_id)


@router.post("/users/{user_id}/secret-keys", summary="创建 Customer Secret Key（明文只返回一次）")
def create_secret_key(user_id: str, tenant_id: int = Query(description="租户 ID"),
                      body: TokenIn = ...,  # type: ignore[assignment]
                      db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.create_customer_secret_key, t, user_id, body.display_name)
    _audit(db, _user.id, "创建 IAM Secret Key", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.delete("/users/{user_id}/secret-keys/{key_id}", summary="删除 Customer Secret Key")
def delete_secret_key(user_id: str, key_id: str, tenant_id: int = Query(description="租户 ID"),
                      db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_customer_secret_key, t, user_id, key_id)
    _audit(db, _user.id, "删除 IAM Secret Key", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.get("/users/{user_id}/smtp-credentials", summary="SMTP 凭证列表")
def list_smtp_credentials(user_id: str, tenant_id: int = Query(description="租户 ID"),
                          db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _cred_list("list_smtp_credentials", db, tenant_id, user_id)


@router.post("/users/{user_id}/smtp-credentials", summary="创建 SMTP 凭证（密码只返回一次）")
def create_smtp_credential(user_id: str, tenant_id: int = Query(description="租户 ID"),
                           body: TokenIn = ...,  # type: ignore[assignment]
                           db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.create_smtp_credential, t, user_id, body.description)
    _audit(db, _user.id, "创建 IAM SMTP 凭证", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.delete("/users/{user_id}/smtp-credentials/{cred_id}", summary="删除 SMTP 凭证")
def delete_smtp_credential(user_id: str, cred_id: str, tenant_id: int = Query(description="租户 ID"),
                           db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_smtp_credential, t, user_id, cred_id)
    _audit(db, _user.id, "删除 IAM SMTP 凭证", f"租户 {t.name} / 用户 {user_id}")
    return r


@router.get("/users/{user_id}/mfa-devices", summary="MFA TOTP 设备列表")
def list_mfa_devices(user_id: str, tenant_id: int = Query(description="租户 ID"),
                     db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _cred_list("list_mfa_totp_devices", db, tenant_id, user_id)


@router.delete("/users/{user_id}/mfa-devices/{device_id}", summary="删除 MFA TOTP 设备")
def delete_mfa_device(user_id: str, device_id: str, tenant_id: int = Query(description="租户 ID"),
                      db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    t, e = _need_tenant(db, tenant_id)
    if e:
        return e
    r = _wrap(iam_service.delete_mfa_totp_device, t, user_id, device_id)
    _audit(db, _user.id, "删除 IAM MFA 设备", f"租户 {t.name} / 用户 {user_id}")
    return r
