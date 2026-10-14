"""OCI SDK 客户端工厂。

- 按租户配置构建 OCI SDK 所需的 config 字典
- 租户私钥 PEM 只以 Fernet 密文存库，用时解密进内存
- client 按 (tenant_id, 服务类型) 做内存缓存，租户配置变更后调用
  invalidate_tenant_cache() 失效
- 密钥来源：环境变量 FERNET_KEY（或 .env），未设置时生成临时密钥并告警
"""
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from ..core.config import get_settings
from ..db import models

log = logging.getLogger(__name__)

# client 缓存：key=(tenant_id, 服务类型)
_client_cache: dict[tuple[int, str], object] = {}


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = get_settings().fernet_key or os.getenv("FERNET_KEY")
    if not key:
        # 脚手架阶段的兜底：生成临时密钥。注意重启后旧加密数据将无法解密，
        # 生产环境务必设置 FERNET_KEY。
        log.warning("未设置 FERNET_KEY，已生成临时密钥（重启后旧数据无法解密）！")
        return Fernet(Fernet.generate_key())
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_private_key(plain_pem: str) -> str:
    """私钥 PEM 明文 -> Fernet 密文（入库用）。"""
    return _get_fernet().encrypt(plain_pem.encode()).decode()


def decrypt_private_key(ciphertext: str) -> str:
    """Fernet 密文 -> 私钥 PEM 明文（内存中使用，用完即弃）。"""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("私钥解密失败：FERNET_KEY 与加密时不一致") from exc


def build_oci_config(tenant: models.Tenant) -> dict:
    """由租户行构建 oci SDK config（key_content 方式，无需写文件）。"""
    return {
        "user": tenant.user_ocid,
        "tenancy": tenant.tenancy_ocid,
        "fingerprint": tenant.fingerprint,
        "key_content": decrypt_private_key(tenant.private_key_ciphertext),
        "region": tenant.region,
    }


def _get_client(tenant: models.Tenant, kind: str):
    """延迟导入 oci，按需构建并缓存指定服务的 client。"""
    cache_key = (tenant.id, kind)
    if cache_key in _client_cache:
        return _client_cache[cache_key]

    import oci  # 延迟导入：无依赖时不影响应用基础启动

    config = build_oci_config(tenant)
    constructors = {
        "compute": oci.core.ComputeClient,
        "network": oci.core.VirtualNetworkClient,
        "identity": oci.identity.IdentityClient,
        "blockstorage": oci.core.BlockstorageClient,
        "objectstorage": oci.object_storage.ObjectStorageClient,
        "usage": oci.usage_api.UsageapiClient,
        "nlb": oci.network_load_balancer.NetworkLoadBalancerClient,
        "lb": oci.load_balancer.LoadBalancerClient,
        "dns": oci.dns.DnsClient,
        "filestorage": oci.file_storage.FileStorageClient,
        "database": oci.database.DatabaseClient,
    }
    if kind not in constructors:
        raise ValueError(f"未知的 OCI 服务类型: {kind}")
    client = constructors[kind](config)
    _client_cache[cache_key] = client
    return client


def get_compute_client(tenant: models.Tenant):
    """实例管理用 client。"""
    return _get_client(tenant, "compute")


def get_network_client(tenant: models.Tenant):
    """VCN / 安全列表 / 公网 IP 用 client。"""
    return _get_client(tenant, "network")


def get_identity_client(tenant: models.Tenant):
    """租户 / 配额校验用 client。"""
    return _get_client(tenant, "identity")


def get_blockstorage_client(tenant: models.Tenant):
    """引导卷用 client。"""
    return _get_client(tenant, "blockstorage")


def get_network_load_balancer_client(tenant: models.Tenant):
    """网络负载均衡器用 client（一键 500M）。"""
    return _get_client(tenant, "nlb")


def get_database_client(tenant: models.Tenant):
    """Autonomous Database 用 client。"""
    return _get_client(tenant, "database")


def invalidate_tenant_cache(tenant_id: int) -> None:
    """租户配置变更/删除后失效其缓存的 client。"""
    for key in [k for k in _client_cache if k[0] == tenant_id]:
        del _client_cache[key]


# ============ 以下为监控模块追加（不改动上方已有函数） ============


def get_monitoring_client(tenant: models.Tenant):
    """监控指标（流量）用 client。"""
    import oci  # 延迟导入：无依赖时不影响应用基础启动

    cache_key = (tenant.id, "monitoring")
    if cache_key not in _client_cache:
        _client_cache[cache_key] = oci.monitoring.MonitoringClient(build_oci_config(tenant))
    return _client_cache[cache_key]


def get_limits_client(tenant: models.Tenant):
    """服务配额用 client。"""
    import oci  # 延迟导入：无依赖时不影响应用基础启动

    cache_key = (tenant.id, "limits")
    if cache_key not in _client_cache:
        _client_cache[cache_key] = oci.limits.LimitsClient(build_oci_config(tenant))
    return _client_cache[cache_key]


def get_object_storage_client(tenant: models.Tenant):
    """对象存储用 client。"""
    return _get_client(tenant, "objectstorage")


def get_usage_client(tenant: models.Tenant):
    """费用用量用 client。"""
    return _get_client(tenant, "usage")


def get_load_balancer_client(tenant: models.Tenant):
    """传统负载均衡器用 client。"""
    return _get_client(tenant, "lb")


def get_dns_client(tenant: models.Tenant):
    """DNS 用 client。"""
    return _get_client(tenant, "dns")


def get_file_storage_client(tenant: models.Tenant):
    """文件存储用 client。"""
    return _get_client(tenant, "filestorage")
