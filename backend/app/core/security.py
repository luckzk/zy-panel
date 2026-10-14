"""安全相关：bcrypt 密码哈希、JWT 发放/校验、MFA 预留接口。"""
import logging
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from .config import get_settings

log = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """明文密码 -> bcrypt 哈希。"""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配。"""
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    """签发 JWT，subject 为用户名。"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    return jwt.encode({"sub": subject, "exp": expire}, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str | None:
    """校验 JWT，返回 subject（用户名），失败返回 None。"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        return payload.get("sub")
    except jwt.PyJWTError as exc:  # 过期 / 签名错误等
        log.debug("JWT 校验失败: %s", exc)
        return None


def verify_mfa(secret: str, code: str) -> bool:
    """MFA 校验预留接口。

    TODO: 接入 pyotp 做 TOTP 校验。目前 User.mfa_secret 字段已预留，
    前端可在「系统设置」里展示二维码绑定流程。
    """
    raise NotImplementedError("MFA 尚未实现（TODO：引入 pyotp 做 TOTP 校验）")
