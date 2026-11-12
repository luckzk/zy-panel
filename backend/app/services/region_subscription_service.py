"""OCI 区域订阅：查询已订阅区域、订阅新区域。

升级（PAYG）账号可订阅 home 区域以外的区域；免费号订阅后也只能在
home 区域用 Always Free 资源。订阅本身不收费，调用后状态先为
IN_PROGRESS，几分钟后变为 READY，期间该区域尚不可用。
"""
import logging

import oci
from oci.exceptions import ConnectTimeout, RequestException, ServiceError

from ..db import models
from . import oci_factory
from .instance_service import OciApiError, _translate

log = logging.getLogger(__name__)

# 不开放订阅的区域（政府/专有云，与 meta_service 保持一致的排除口径）
_EXCLUDED_SUBSTR = ("-gov-", "-dcc-")
_EXCLUDED_REGIONS = {"us-langley-1", "us-luke-1"}


def _usable(region_key: str) -> bool:
    return region_key not in _EXCLUDED_REGIONS and not any(
        s in region_key for s in _EXCLUDED_SUBSTR
    )


def list_region_subscriptions(tenant: models.Tenant) -> dict:
    """返回 {"subscribed": [...], "available": [...]}。"""
    identity = oci_factory.get_identity_client(tenant)
    try:
        subs = identity.list_region_subscriptions(tenant.tenancy_ocid).data
        all_regions = identity.list_regions().data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "查询区域订阅")
    subscribed = [
        {
            "region_key": s.region_key,
            "region_name": s.region_name,
            "status": s.status,
            "is_home_region": bool(s.is_home_region),
        }
        for s in subs
    ]
    sub_keys = {s["region_key"] for s in subscribed}
    available = [
        {"region_key": r.key, "region_name": r.name}
        for r in all_regions
        if r.key not in sub_keys and _usable(r.key)
    ]
    return {"subscribed": subscribed, "available": available}


def subscribe_region(tenant: models.Tenant, region_key: str) -> dict:
    """订阅一个新区域，返回订阅记录（初始状态多为 IN_PROGRESS）。"""
    identity = oci_factory.get_identity_client(tenant)
    details = oci.identity.models.CreateRegionSubscriptionDetails(region_key=region_key)
    try:
        sub = identity.create_region_subscription(details, tenant.tenancy_ocid).data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, f"订阅区域 {region_key}")
    return {
        "region_key": sub.region_key,
        "region_name": sub.region_name,
        "status": sub.status,
        "is_home_region": bool(sub.is_home_region),
    }
