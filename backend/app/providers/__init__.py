"""Provider 注册表：加厂商 = 新建模块 + 在这里注册一行。"""
from __future__ import annotations

import json
import logging

from .base import CloudProvider, ProviderError

log = logging.getLogger(__name__)

_REGISTRY: dict[str, type[CloudProvider]] = {}


def register(provider_cls: type[CloudProvider]) -> type[CloudProvider]:
    _REGISTRY[provider_cls.provider_id] = provider_cls
    return provider_cls


def get_provider_class(provider_id: str) -> type[CloudProvider] | None:
    return _REGISTRY.get(provider_id)


def list_providers() -> list[dict]:
    """返回已注册厂商元信息（给前端下拉用）。"""
    return [
        {"id": cls.provider_id, "name": cls.display_name,
         "capabilities": sorted(c.value for c in cls.capabilities)}
        for cls in _REGISTRY.values()
    ]


def encrypt_credentials(creds: dict) -> str:
    """凭证 dict -> Fernet 加密 JSON 字符串（复用 oci_factory 的密钥体系）。"""
    from ..services.oci_factory import _get_fernet
    return _get_fernet().encrypt(json.dumps(creds).encode()).decode()


def decrypt_credentials(ciphertext: str) -> dict:
    from cryptography.fernet import InvalidToken

    from ..services.oci_factory import _get_fernet
    try:
        return json.loads(_get_fernet().decrypt(ciphertext.encode()).decode())
    except InvalidToken as exc:
        raise ProviderError(3101, f"租户凭证解密失败（FERNET_KEY 可能已更换）：{exc}", 502)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProviderError(3101, f"租户凭证格式异常：{exc}", 502)


def get_tenant_credentials(tenant) -> dict:
    """统一读取租户凭证：优先 credentials_enc；老 OCI 租户自动从明文字段组装。"""
    provider_id = getattr(tenant, "provider", None) or "oci"
    enc = getattr(tenant, "credentials_enc", None)
    if enc:
        return decrypt_credentials(enc)
    if provider_id == "oci":
        # 老数据兼容：从原有字段组装
        from ..services.oci_factory import decrypt_private_key
        return {
            "tenancy_ocid": tenant.tenancy_ocid,
            "user_ocid": tenant.user_ocid,
            "fingerprint": tenant.fingerprint,
            "private_key": decrypt_private_key(tenant.private_key_ciphertext),
            "region": tenant.region,
        }
    raise ProviderError(3101, "该租户未配置凭证", 502)


def get_provider(tenant) -> CloudProvider:
    """按 tenant.provider 分发 Provider 实例。"""
    provider_id = getattr(tenant, "provider", None) or "oci"
    cls = get_provider_class(provider_id)
    if cls is None:
        raise ProviderError(3502, f"未知的云厂商：{provider_id}", 400)
    inst = cls(tenant)
    inst.credentials = get_tenant_credentials(tenant)
    return inst


# 注册内置厂商（import 即注册）
from . import aliyun as _aliyun  # noqa: E402,F401
from . import oci as _oci  # noqa: E402,F401
