"""认证路由：登录（bcrypt 验密 + JWT + MFA 二次校验）、MFA 绑定管理、当前用户信息、改密码。"""
import base64
import io
import time

import pyotp
import qrcode
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..core.security import create_access_token, hash_password, verify_password
from ..db import models

router = APIRouter(prefix="/auth", tags=["认证"])

MFA_REQUIRED_MSG = "需要 MFA 验证码"

# 登录防爆破：{ip: [失败时间戳]}，15 分钟内失败 5 次则锁定 15 分钟
_login_failures: dict[str, list[float]] = {}
_FAIL_WINDOW_SEC = 900
_FAIL_LIMIT = 5


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_locked(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _login_failures.get(ip, []) if now - t < _FAIL_WINDOW_SEC]
    _login_failures[ip] = hits
    return len(hits) >= _FAIL_LIMIT


def _record_login_failure(ip: str) -> None:
    _login_failures.setdefault(ip, []).append(time.time())


class LoginIn(BaseModel):
    username: str
    password: str
    mfa_code: str | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class MfaCodeIn(BaseModel):
    code: str


def _verify_totp(secret: str, code: str) -> bool:
    """TOTP 验证码校验（允许前后 30s 时钟漂移）。"""
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def _qr_data_uri(content: str) -> str:
    """把文本渲染成 PNG 二维码的 base64 data URI，前端可直接 <img src>。"""
    img = qrcode.make(content)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


@router.post("/login", summary="登录，返回 JWT")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _client_ip(request)
    if _login_locked(ip):
        return err(1003, "登录失败次数过多，请 15 分钟后再试", status=429)
    user = db.query(models.User).filter(models.User.username == body.username).first()
    if user is None or not verify_password(body.password, user.password_hash):
        _record_login_failure(ip)
        return err(1001, "用户名或密码错误", status=401)
    # MFA 二次校验：已启用的用户必须提供正确的 TOTP 验证码
    # 注意：这里用 HTTP 200 + 业务码 1002（而非 401），因为前端 axios 拦截器
    # 会把任何 401 当作"登录过期"清 token 并跳转，会破坏 MFA 接力流程。
    if user.mfa_enabled:
        if not body.mfa_code or not user.mfa_secret or not _verify_totp(user.mfa_secret, body.mfa_code):
            _record_login_failure(ip)
            return err(1002, MFA_REQUIRED_MSG, status=200)
    _login_failures.pop(ip, None)
    token = create_access_token(user.username)
    write_log(db, user.id, "auth.login", f"用户 {user.username} 登录")
    return ok({"token": token, "token_type": "bearer", "username": user.username})


@router.post("/mfa/setup", summary="MFA 绑定：生成密钥与二维码（需登录）")
def mfa_setup(user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    user.mfa_enabled = False  # 必须走 /mfa/verify 校验通过后才真正启用
    db.commit()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(name=user.username, issuer_name="OCI Panel")
    write_log(db, user.id, "auth.mfa_setup", f"用户 {user.username} 生成 MFA 绑定二维码")
    return ok({"secret": secret, "otpauth_uri": uri, "qr_data_uri": _qr_data_uri(uri)})


@router.post("/mfa/verify", summary="MFA 绑定确认：验证码正确则启用")
def mfa_verify(
    body: MfaCodeIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.mfa_secret:
        return err(1004, "尚未生成 MFA 密钥，请先调用 /mfa/setup", status=400)
    if not _verify_totp(user.mfa_secret, body.code):
        return err(1003, "验证码错误", status=400)
    user.mfa_enabled = True
    db.commit()
    write_log(db, user.id, "auth.mfa_verify", f"用户 {user.username} 启用 MFA")
    return ok(msg="MFA 已启用")


@router.post("/mfa/disable", summary="关闭 MFA：验证码正确则解绑")
def mfa_disable(
    body: MfaCodeIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not user.mfa_enabled or not user.mfa_secret:
        return err(1004, "MFA 未启用", status=400)
    if not _verify_totp(user.mfa_secret, body.code):
        return err(1003, "验证码错误", status=400)
    user.mfa_enabled = False
    user.mfa_secret = None
    db.commit()
    write_log(db, user.id, "auth.mfa_disable", f"用户 {user.username} 关闭 MFA")
    return ok(msg="MFA 已关闭")


@router.get("/mfa/status", summary="当前用户 MFA 状态")
def mfa_status(user: models.User = Depends(get_current_user)):
    return ok({"mfa_enabled": bool(user.mfa_enabled), "has_secret": bool(user.mfa_secret)})


@router.get("/me", summary="当前登录用户信息")
def me(user: models.User = Depends(get_current_user)):
    return ok(
        {
            "username": user.username,
            "is_admin": user.is_admin,
            "mfa_enabled": bool(user.mfa_enabled),
        }
    )


@router.post("/change-password", summary="修改当前用户密码")
def change_password(
    body: ChangePasswordIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(body.old_password, user.password_hash):
        return err(1005, "原密码不正确", status=400)
    user.password_hash = hash_password(body.new_password)
    db.commit()
    write_log(db, user.id, "auth.change_password", f"用户 {user.username} 修改密码")
    return ok(msg="密码修改成功")
