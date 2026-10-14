"""免费额度（Always Free）使用情况汇总。

OCI 没有"免费额度用量"的统一 API，这里按官方 Always Free 标准，
用各服务的实时查询拼出 已用/上限：
- AMD 实例：VM.Standard.E2.1.Micro 上限 2 台
- ARM 实例：VM.Standard.A1.Flex 上限 4 OCPU / 24 GB 内存
- 块存储（引导卷+数据卷）：上限 200 GB
- 对象存储：上限 20 GB
- Autonomous Database：上限 2 个
- 出站流量：上限 10 TB/月（按实例 VNIC 出向流量累加，取当月）

全部只读查询，不做任何修改。
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import oci
from oci.exceptions import ServiceError

from ..db import models
from . import oci_factory
from .instance_service import _paginate, _translate
from .security_service import OciApiError

log = logging.getLogger(__name__)

# Always Free 上限（2026 年标准）；limit 为 None 表示仅统计用量、无明确免费上限
LIMITS = {
    "amd_micro_count": {"limit": 2, "unit": "台", "name": "AMD 实例（E2.1.Micro）"},
    "arm_ocpus": {"limit": 4, "unit": "OCPU", "name": "ARM 算力（A1.Flex）"},
    "arm_memory_gbs": {"limit": 24, "unit": "GB", "name": "ARM 内存（A1.Flex）"},
    "block_volume_gbs": {"limit": 200, "unit": "GB", "name": "块存储总量"},
    "object_storage_gbs": {"limit": 20, "unit": "GB", "name": "对象存储"},
    "autonomous_db_count": {"limit": 2, "unit": "个", "name": "Autonomous Database"},
    "outbound_tb_month": {"limit": 10, "unit": "TB", "name": "出站流量（本月）"},
    "load_balancer_count": {"limit": 1, "unit": "个", "name": "负载均衡器（历史免费上限 1 个）"},
    "vcn_count": {"limit": None, "unit": "个", "name": "VCN（本身免费）"},
    "public_ip_count": {"limit": None, "unit": "个", "name": "保留公网 IP"},
    "dns_zone_count": {"limit": None, "unit": "个", "name": "DNS Zone"},
    "file_system_count": {"limit": None, "unit": "个", "name": "文件系统（FSS）"},
}


def _all_compartment_ids(tenant: models.Tenant) -> list[str]:
    ids = [tenant.tenancy_ocid]
    try:
        identity = oci_factory.get_identity_client(tenant)
        items = _paginate(
            identity.list_compartments,
            compartment_id=tenant.tenancy_ocid,
            compartment_id_in_subtree=True,
        )
        for c in items:
            if c.lifecycle_state == "ACTIVE" and c.id not in ids:
                ids.append(c.id)
    except Exception:
        pass
    return ids


def get_free_tier_summary(tenant: models.Tenant) -> dict:
    """汇总免费额度使用情况。单项查询失败时该项标记 unknown，不影响其他项。"""
    comp_ids = _all_compartment_ids(tenant)
    items: dict = {}

    def put(key: str, used, extra: dict | None = None):
        cfg = LIMITS[key]
        d = {"key": key, "name": cfg["name"], "limit": cfg["limit"], "unit": cfg["unit"],
             "used": used, "unknown": used is None}
        if extra:
            d.update(extra)
        items[key] = d

    # ---- 计算实例 ----
    try:
        compute = oci_factory.get_compute_client(tenant)
        instances = []
        for cid in comp_ids:
            try:
                instances.extend(_paginate(compute.list_instances, compartment_id=cid))
            except ServiceError:
                continue
        instances = [i for i in instances if (i.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING")]
        amd_count = sum(1 for i in instances if (i.shape or "") == "VM.Standard.E2.1.Micro")
        arm_ocpus = 0.0
        arm_mem = 0.0
        arm_instances = []
        for i in instances:
            if "A1.Flex" in (i.shape or ""):
                sc = getattr(i, "shape_config", None)
                oc = getattr(sc, "ocpus", None) if sc else None
                mem = getattr(sc, "memory_in_gbs", None) if sc else None
                arm_ocpus += float(oc or 0)
                arm_mem += float(mem or 0)
                arm_instances.append({
                    "name": getattr(i, "display_name", "") or "",
                    "ocpus": oc, "memory_in_gbs": mem,
                    "state": i.lifecycle_state,
                })
        put("amd_micro_count", amd_count)
        put("arm_ocpus", round(arm_ocpus, 2), {"detail": arm_instances})
        put("arm_memory_gbs", round(arm_mem, 2))
    except Exception as exc:
        log.warning("免费额度-实例统计失败: %s", exc)
        put("amd_micro_count", None)
        put("arm_ocpus", None)
        put("arm_memory_gbs", None)

    # ---- 块存储 ----
    try:
        bs = oci_factory.get_blockstorage_client(tenant)
        total_gb = 0
        for cid in comp_ids:
            try:
                for v in _paginate(bs.list_boot_volumes, compartment_id=cid):
                    if v.lifecycle_state == "AVAILABLE" or True:
                        total_gb += v.size_in_gbs or 0
                for v in _paginate(bs.list_volumes, compartment_id=cid):
                    if (v.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"):
                        total_gb += v.size_in_gbs or 0
            except ServiceError:
                continue
        put("block_volume_gbs", total_gb)
    except Exception as exc:
        log.warning("免费额度-块存储统计失败: %s", exc)
        put("block_volume_gbs", None)

    # ---- 对象存储 ----
    try:
        oss = oci_factory.get_object_storage_client(tenant)
        ns = oss.get_namespace().data
        total_bytes = 0
        bucket_count = 0
        for cid in comp_ids:
            try:
                buckets = _paginate(oss.list_buckets, namespace_name=ns, compartment_id=cid)
            except ServiceError:
                continue
            for b in buckets:
                bucket_count += 1
                try:
                    # 用桶的 approximate_count/size（list_buckets 已带）
                    total_bytes += getattr(b, "approximate_size", 0) or 0
                except Exception:
                    pass
        put("object_storage_gbs", round(total_bytes / (1024 ** 3), 2), {"detail": {"buckets": bucket_count}})
    except Exception as exc:
        log.warning("免费额度-对象存储统计失败: %s", exc)
        put("object_storage_gbs", None)

    # ---- Autonomous Database ----
    try:
        db_client = oci_factory.get_database_client(tenant)
        count = 0
        for cid in comp_ids:
            try:
                dbs = _paginate(db_client.list_autonomous_databases, compartment_id=cid)
                count += sum(1 for d in dbs if (d.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"))
            except ServiceError:
                continue
        put("autonomous_db_count", count)
    except Exception as exc:
        log.warning("免费额度-数据库统计失败: %s", exc)
        put("autonomous_db_count", None)

    # ---- 本月出站流量（实例 VNIC 出向累加）----    try:
        from . import monitoring_service
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        hours = max(int((now - month_start).total_seconds() // 3600), 1)
        total_out_bytes = 0
        compute = oci_factory.get_compute_client(tenant)
        for cid in comp_ids:
            try:
                instances = _paginate(compute.list_instances, compartment_id=cid)
            except ServiceError:
                continue
            for inst in instances:
                if (inst.lifecycle_state or "").upper() != "RUNNING":
                    continue
                try:
                    vnic_id = monitoring_service.get_primary_vnic_id(tenant, inst.id)
                    if not vnic_id:
                        continue
                    # 1h 粒度：bytes = mbps * 1e6 / 8 * 3600
                    pts = monitoring_service.query_vnic_traffic(
                        tenant, vnic_id, hours=min(hours, 720), resolution="1h")
                    for p in pts:
                        total_out_bytes += p["outbound_mbps"] * 1e6 / 8 * 3600
                except Exception:
                    continue
        put("outbound_tb_month", round(total_out_bytes / (1024 ** 4), 3))
    except Exception as exc:
        log.warning("免费额度-出站流量统计失败: %s", exc)
        put("outbound_tb_month", None)

    # ---- 负载均衡器（传统 LB + NLB）----
    try:
        lb_count = 0
        try:
            lb_client = oci_factory.get_load_balancer_client(tenant)
            for cid in comp_ids:
                try:
                    lbs = _paginate(lb_client.list_load_balancers, compartment_id=cid)
                    lb_count += sum(1 for l in lbs if (l.lifecycle_state or "").upper() not in ("DELETED", "DELETING"))
                except ServiceError:
                    continue
        except Exception:
            pass
        try:
            nlb_client = oci_factory.get_network_load_balancer_client(tenant)
            for cid in comp_ids:
                try:
                    nlbs = _paginate(nlb_client.list_network_load_balancers, compartment_id=cid)
                    lb_count += sum(1 for l in nlbs if (l.lifecycle_state or "").upper() not in ("DELETED", "DELETING"))
                except ServiceError:
                    continue
        except Exception:
            pass
        put("load_balancer_count", lb_count)
    except Exception as exc:
        log.warning("免费额度-负载均衡统计失败: %s", exc)
        put("load_balancer_count", None)

    # ---- VCN ----
    try:
        network = oci_factory.get_network_client(tenant)
        vcn_count = 0
        for cid in comp_ids:
            try:
                vcns = _paginate(network.list_vcns, compartment_id=cid)
                vcn_count += sum(1 for v in vcns if (v.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"))
            except ServiceError:
                continue
        put("vcn_count", vcn_count)
    except Exception as exc:
        log.warning("免费额度-VCN 统计失败: %s", exc)
        put("vcn_count", None)

    # ---- 保留公网 IP ----
    try:
        network = oci_factory.get_network_client(tenant)
        ip_count = 0
        for cid in comp_ids:
            try:
                ips = _paginate(network.list_public_ips, scope="REGION", compartment_id=cid)
                ip_count += sum(1 for ip in ips if (ip.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"))
            except ServiceError:
                continue
        put("public_ip_count", ip_count)
    except Exception as exc:
        log.warning("免费额度-公网 IP 统计失败: %s", exc)
        put("public_ip_count", None)

    # ---- DNS Zone ----
    try:
        dns_client = oci_factory.get_dns_client(tenant)
        zone_count = 0
        for cid in comp_ids:
            try:
                zones = _paginate(dns_client.list_zones, compartment_id=cid)
                zone_count += sum(1 for z in zones if (z.lifecycle_state or "").upper() not in ("DELETED", "DELETING"))
            except ServiceError:
                continue
        put("dns_zone_count", zone_count)
    except Exception as exc:
        log.warning("免费额度-DNS Zone 统计失败: %s", exc)
        put("dns_zone_count", None)

    # ---- 文件系统（FSS） ----
    try:
        fs_client = oci_factory.get_file_storage_client(tenant)
        fs_count = 0
        for cid in comp_ids:
            try:
                # FSS 按 AD 查
                identity = oci_factory.get_identity_client(tenant)
                ads = _paginate(identity.list_availability_domains, compartment_id=tenant.tenancy_ocid)
                for ad in ads:
                    try:
                        fss = _paginate(fs_client.list_file_systems, compartment_id=cid,
                                        availability_domain=ad.name)
                        fs_count += sum(1 for f in fss if (f.lifecycle_state or "").upper() not in ("DELETED", "DELETING"))
                    except ServiceError:
                        continue
            except ServiceError:
                continue
        put("file_system_count", fs_count)
    except Exception as exc:
        log.warning("免费额度-文件系统统计失败: %s", exc)
        put("file_system_count", None)

    return {"tenant_id": tenant.id, "items": list(items.values()),
            "generated_at": datetime.now(timezone.utc).isoformat()}
