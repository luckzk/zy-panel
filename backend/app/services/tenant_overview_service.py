"""租户详情页总览（仅 OCI，只读）：一次调用汇总多处租户信息。

各小节独立 try/except，某一节失败不影响其他节返回（失败的节为 None，
前端显示“获取失败”）。不含账单（账单接口有时很慢，费用卡走独立接口）。
"""
import logging

from oci.exceptions import ConnectTimeout, RequestException, ServiceError

from ..db import models
from . import meta_service, oci_factory
from .account_detect_service import FREE_SHAPES, MICRO_LIMIT_NAME, PAID_CORE_LIMITS
from .instance_service import _paginate

log = logging.getLogger(__name__)

# 配额快照要展示的 compute 配额名（与账号检测共用同一口径）
_QUOTA_NAMES = {
    "micro_limit": MICRO_LIMIT_NAME,
    "a1_core_limit": "standard-a1-core-count",
    "e2_core_limit": "standard-e2-core-count",
    "e3_core_limit": "standard-e3-core-count",
    "e4_core_limit": "standard-e4-core-count",
    "e5_core_limit": "standard-e5-core-count",
    "e6_core_limit": "standard-e6-core-count",
}


def _short_ad(ad: str | None) -> str:
    """'abcd:AP-TOKYO-1-AD-1' -> 'AD-1'。"""
    if not ad:
        return ""
    return "AD-" + ad.split(":")[-1].split("-")[-1]


def _compartment_ids(tenant: models.Tenant) -> list[str]:
    comp_ids = [tenant.tenancy_ocid]
    try:
        identity = oci_factory.get_identity_client(tenant)
        for c in _paginate(
            identity.list_compartments,
            compartment_id=tenant.tenancy_ocid,
            compartment_id_in_subtree=True,
        ):
            if c.lifecycle_state == "ACTIVE" and c.id not in comp_ids:
                comp_ids.append(c.id)
    except (ConnectTimeout, RequestException, ServiceError):
        pass
    return comp_ids


def _section(fn):
    """小节包装：失败记日志并返回 None，不阻断整单。"""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - 总览允许局部失败
        log.warning("租户总览小节失败 %s: %s", fn.__name__, str(exc)[:150])
        return None


def get_overview(tenant: models.Tenant) -> dict:
    """返回 {tenancy_name, availability_domains, compartments, resources, quotas, iam}。"""

    def _tenancy_name():
        ten = oci_factory.get_identity_client(tenant).get_tenancy(tenant.tenancy_ocid).data
        return ten.name or None

    def _availability_domains():
        ads = meta_service.list_availability_domains(tenant)
        return [_short_ad(a.get("name")) for a in ads if a.get("name")]

    def _compartments():
        return [
            {"id": c["id"], "name": c["name"]}
            for c in meta_service.list_compartments(tenant)
        ]

    def _resources():
        comp_ids = _compartment_ids(tenant)
        compute = oci_factory.get_compute_client(tenant)
        instances = []
        for cid in comp_ids:
            try:
                instances.extend(_paginate(compute.list_instances, compartment_id=cid))
            except ServiceError:
                continue
        live = [i for i in instances if (i.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING")]
        micro = sum(1 for i in live if (i.shape or "") == "VM.Standard.E2.1.Micro")
        a1_ocpu = 0.0
        a1_mem = 0.0
        for i in live:
            if "A1.Flex" in (i.shape or ""):
                sc = getattr(i, "shape_config", None)
                if sc:
                    a1_ocpu += float(getattr(sc, "ocpus", 0) or 0)
                    a1_mem += float(getattr(sc, "memory_in_gbs", 0) or 0)
        paid_shapes = sorted({i.shape for i in live if (i.shape or "") not in FREE_SHAPES})

        bs = oci_factory.get_blockstorage_client(tenant)
        total_gb = 0
        for cid in comp_ids:
            try:
                for v in _paginate(bs.list_boot_volumes, compartment_id=cid):
                    total_gb += v.size_in_gbs or 0
                for v in _paginate(bs.list_volumes, compartment_id=cid):
                    if (v.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"):
                        total_gb += v.size_in_gbs or 0
            except ServiceError:
                continue

        db_client = oci_factory.get_database_client(tenant)
        adb = 0
        for cid in comp_ids:
            try:
                dbs = _paginate(db_client.list_autonomous_databases, compartment_id=cid)
                adb += sum(1 for d in dbs if (d.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"))
            except ServiceError:
                continue

        network = oci_factory.get_network_client(tenant)
        vcn = 0
        for cid in comp_ids:
            try:
                vcn += len(_paginate(network.list_vcns, compartment_id=cid))
            except ServiceError:
                continue

        return {
            "instances_total": len(live),
            "micro_count": micro,
            "a1_ocpu": round(a1_ocpu, 2),
            "a1_memory_gb": round(a1_mem, 2),
            "paid_shapes": paid_shapes,
            "block_storage_gb": total_gb,
            "adb_count": adb,
            "vcn_count": vcn,
        }

    def _quotas():
        lc = oci_factory.get_limits_client(tenant)
        values = _paginate(
            lc.list_limit_values,
            compartment_id=tenant.tenancy_ocid, service_name="compute",
        )
        by_name: dict[str, int] = {}
        for lv in values:
            v = int(lv.value or 0)
            by_name[lv.name] = max(by_name.get(lv.name, 0), v)
        out = {key: by_name.get(name) for key, name in _QUOTA_NAMES.items()}
        try:
            region_vals = _paginate(
                lc.list_limit_values,
                compartment_id=tenant.tenancy_ocid, service_name="regions",
            )
            for lv in region_vals:
                if lv.name == "subscribed-region-count":
                    out["subscribed_region_limit"] = int(lv.value or 0)
        except (ConnectTimeout, RequestException, ServiceError):
            out["subscribed_region_limit"] = None
        return out

    def _iam():
        identity = oci_factory.get_identity_client(tenant)
        users = _paginate(identity.list_users, compartment_id=tenant.tenancy_ocid)
        groups = _paginate(identity.list_groups, compartment_id=tenant.tenancy_ocid)
        return {"users": len(users), "groups": len(groups)}

    return {
        "tenancy_name": _section(_tenancy_name),
        "availability_domains": _section(_availability_domains),
        "compartments": _section(_compartments),
        "resources": _section(_resources),
        "quotas": _section(_quotas),
        "iam": _section(_iam),
    }
