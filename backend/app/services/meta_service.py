"""元数据服务：Region / Compartment / AD / Shape / 镜像 / 子网 / 引导卷的下拉选项。

原则：能从 SDK 或 OCI 实时接口拿的，绝不写死。
- regions：OCI SDK 自带的 oci.regions.REGIONS（无需租户），过滤掉政府云/专有云
- 其余：按租户实时调 OCI 接口查询
"""
import logging

import oci

from ..db import models
from .instance_service import OciApiError, _paginate, _translate
from .oci_factory import get_blockstorage_client, get_compute_client, get_identity_client, get_network_client
from oci.exceptions import ServiceError

log = logging.getLogger(__name__)

# 非商业区：政府云、专有云、美军区（SDK 列表里混在一起，前端不需要）
_EXCLUDED_REGION_SUBSTR = ("gov", "dcc")
_EXCLUDED_REGIONS = {"us-langley-1", "us-luke-1"}


def list_regions() -> list[dict]:
    """全部商业 Region（SDK 权威列表），按 id 排序。"""
    regions = [
        r for r in sorted(set(oci.regions.REGIONS))
        if r not in _EXCLUDED_REGIONS
        and not any(s in r for s in _EXCLUDED_REGION_SUBSTR)
    ]
    return [{"id": r} for r in regions]


def _root_compartment(tenant: models.Tenant, compartment_id: str | None) -> str:
    return compartment_id or tenant.tenancy_ocid


def _all_compartment_ids(tenant: models.Tenant) -> list[str]:
    """全租户 compartment id 列表（含 root，去重保序）。

    OCI 的 list_subnets / list_boot_volumes / list_images 只查指定
    compartment 下直接的资源（不支持 in_subtree），而用户的子网、引导卷
    可能建在任意 compartment 里，所以这里递归全租户查。
    """
    ids = [tenant.tenancy_ocid]
    try:
        for c in list_compartments(tenant):
            if c["id"] not in ids:
                ids.append(c["id"])
    except OciApiError:
        pass
    return ids


def _dedup_by_id(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        if it["id"] not in seen:
            seen.add(it["id"])
            out.append(it)
    return out


def list_compartments(tenant: models.Tenant, compartment_id: str | None = None) -> list[dict]:
    """某租户下（含子级）的全部可用 compartment，首位为根 compartment（tenancy 自身）。

    OCI 的 list_compartments 只返回子级不含自身，但实例/网络等资源经常建在
    根 compartment 里，所以这里把 tenancy 本身插到首位。
    """
    client = get_identity_client(tenant)
    try:
        items = _paginate(
            client.list_compartments,
            compartment_id=_root_compartment(tenant, compartment_id),
            compartment_id_in_subtree=True,
        )
    except ServiceError as exc:
        raise _translate(exc, "查询 Compartment 列表") from exc
    out = []
    # 根 compartment（tenancy 自身）
    try:
        ten = client.get_tenancy(tenant.tenancy_ocid).data
        ten_name = ten.name or "根 Compartment"
    except ServiceError:
        ten_name = "根 Compartment"
    out.append({"id": tenant.tenancy_ocid, "name": ten_name, "description": "根 Compartment（tenancy 自身）"})
    seen = {tenant.tenancy_ocid}
    for c in items:
        # 注意：Compartment 的正常状态是 ACTIVE（不是 AVAILABLE，别写错）
        if c.lifecycle_state == "ACTIVE" and c.id not in seen:
            seen.add(c.id)
            out.append({"id": c.id, "name": c.name, "description": c.description or ""})
    return out


def list_availability_domains(tenant: models.Tenant) -> list[dict]:
    """租户 home region 的可用域（完整名，如 abcd:AP-TOKYO-1-AD-1）。"""
    client = get_identity_client(tenant)
    try:
        resp = client.list_availability_domains(compartment_id=tenant.tenancy_ocid)
    except ServiceError as exc:
        raise _translate(exc, "查询可用域") from exc
    return [{"name": ad.name} for ad in resp.data]


def list_shapes(tenant: models.Tenant, compartment_id: str | None = None) -> list[dict]:
    """某 compartment 下可用的全部 Shape（含 Flex 的 OCPU/内存选项范围）。"""
    client = get_compute_client(tenant)
    try:
        items = _paginate(client.list_shapes, compartment_id=_root_compartment(tenant, compartment_id))
    except ServiceError as exc:
        raise _translate(exc, "查询 Shape 列表") from exc
    out = []
    for s in items:
        out.append({
            "shape": s.shape,
            "ocpus": getattr(s, "ocpus", None),
            "memory_in_gbs": getattr(s, "memory_in_gbs", None),
            "networking_bandwidth_in_gbps": getattr(s, "networking_bandwidth_in_gbps", None),
            "is_flex": "Flex" in (s.shape or ""),
        })
    # 去重保序
    seen, uniq = set(), []
    for s in out:
        if s["shape"] not in seen:
            seen.add(s["shape"])
            uniq.append(s)
    return uniq


def list_images(tenant: models.Tenant, compartment_id: str | None = None, limit: int = 100) -> list[dict]:
    """全租户可用的镜像（按创建时间倒序）。

    镜像可能在任意 compartment，递归全租户查（compartment_id 参数保留兼容，实际全查）。
    """
    client = get_compute_client(tenant)
    out = []
    for cid in _all_compartment_ids(tenant):
        try:
            resp = client.list_images(
                compartment_id=cid,
                sort_by="TIMECREATED",
                sort_order="DESC",
                limit=limit,
            )
        except ServiceError as exc:
            raise _translate(exc, "查询镜像列表") from exc
        out.extend(
            {
                "id": img.id,
                "display_name": img.display_name,
                "operating_system": img.operating_system,
                "operating_system_version": img.operating_system_version,
                "compartment_id": cid,
            }
            for img in resp.data if img.lifecycle_state == "AVAILABLE"
        )
    # 按创建时间倒序已在单 compartment 内保证，合并后按 id 去重
    return _dedup_by_id(out)


def list_subnets(tenant: models.Tenant, compartment_id: str | None = None) -> list[dict]:
    """全租户可用的子网（实例的 compartment 和子网的 compartment 可以不同）。"""
    client = get_network_client(tenant)
    out = []
    for cid in _all_compartment_ids(tenant):
        try:
            items = _paginate(client.list_subnets, compartment_id=cid)
        except ServiceError as exc:
            raise _translate(exc, "查询子网列表") from exc
        out.extend(
            {
                "id": s.id,
                "display_name": s.display_name,
                "cidr_block": s.cidr_block,
                "availability_domain": s.availability_domain,
                "compartment_id": cid,
            }
            for s in items if s.lifecycle_state == "AVAILABLE"
        )
    return _dedup_by_id(out)


def list_boot_volumes(tenant: models.Tenant, compartment_id: str | None = None,
                      availability_domain: str | None = None) -> list[dict]:
    """全租户可用的引导卷（供抢机时从现有引导卷启动）。

    只返回 AVAILABLE 状态的；可按 AD 过滤（从引导卷起实例必须同 AD）。
    引导卷可能在任意 compartment，递归全租户查。
    """
    client = get_blockstorage_client(tenant)
    out = []
    for cid in _all_compartment_ids(tenant):
        kwargs: dict = {"compartment_id": cid}
        if availability_domain:
            kwargs["availability_domain"] = availability_domain
        try:
            items = _paginate(client.list_boot_volumes, **kwargs)
        except ServiceError as exc:
            raise _translate(exc, "查询引导卷列表") from exc
        out.extend(
            {
                "id": v.id,
                "display_name": v.display_name,
                "size_in_gbs": v.size_in_gbs,
                "availability_domain": v.availability_domain,
                "lifecycle_state": v.lifecycle_state,
                "compartment_id": cid,
                "time_created": v.time_created.isoformat() if v.time_created else None,
            }
            for v in items if v.lifecycle_state == "AVAILABLE"
        )
    return _dedup_by_id(out)
