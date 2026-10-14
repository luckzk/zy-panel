"""账号类型启发式检测。

OCI 没有"免费号/付费号"的官方 API。本模块用反向启发式判断：
- 只要出现免费号建不出来的东西（超免费额度资源、付费 shape、非零账单），就一定是付费号；
- 反之只能判"疑似免费号"，因为付费号也可能只用免费资源。

结论仅供参考，用户可手动修改。
"""
import logging

from oci.exceptions import ServiceError

from ..db import models
from . import oci_factory
from .instance_service import _paginate
from . import usage_service

log = logging.getLogger(__name__)

# 免费 shape 白名单（超出此范围的 running 实例 => 付费号）
FREE_SHAPES = {"VM.Standard.E2.1.Micro", "VM.Standard.A1.Flex"}


def detect_account_type(tenant: models.Tenant) -> dict:
    """返回 {"detected": "free"|"paid"|"unknown", "reasons": [...]}。"""
    reasons: list[str] = []
    paid_signals: list[str] = []

    comp_ids = [tenant.tenancy_ocid]
    try:
        identity = oci_factory.get_identity_client(tenant)
        for c in _paginate(identity.list_compartments, compartment_id=tenant.tenancy_ocid,
                           compartment_id_in_subtree=True):
            if c.lifecycle_state == "ACTIVE" and c.id not in comp_ids:
                comp_ids.append(c.id)
    except Exception:
        pass

    # 1. 实例：超免费额度 / 付费 shape
    try:
        compute = oci_factory.get_compute_client(tenant)
        instances = []
        for cid in comp_ids:
            try:
                instances.extend(_paginate(compute.list_instances, compartment_id=cid))
            except ServiceError:
                continue
        live = [i for i in instances if (i.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING")]
        micro = sum(1 for i in live if (i.shape or "") == "VM.Standard.E2.1.Micro")
        if micro > 2:
            paid_signals.append(f"AMD Micro 实例 {micro} 台，超过免费上限 2 台")
        a1_ocpu = 0.0
        for i in live:
            if "A1.Flex" in (i.shape or ""):
                sc = getattr(i, "shape_config", None)
                a1_ocpu += float(getattr(sc, "ocpus", 0) or 0) if sc else 0
        if a1_ocpu > 4:
            paid_signals.append(f"ARM 算力 {a1_ocpu} OCPU，超过免费上限 4 OCPU")
        paid_shapes = sorted({i.shape for i in live if (i.shape or "") not in FREE_SHAPES})
        if paid_shapes:
            paid_signals.append(f"存在付费机型实例：{', '.join(paid_shapes[:3])}")
        reasons.append(f"检查 {len(live)} 台实例")
    except Exception as exc:
        reasons.append(f"实例检查失败：{exc}")

    # 2. 块存储总量
    try:
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
        if total_gb > 200:
            paid_signals.append(f"块存储 {total_gb}GB，超过免费上限 200GB")
        reasons.append(f"块存储 {total_gb}GB")
    except Exception as exc:
        reasons.append(f"块存储检查失败：{exc}")

    # 3. 自治数据库数量
    try:
        db_client = oci_factory.get_database_client(tenant)
        count = 0
        for cid in comp_ids:
            try:
                dbs = _paginate(db_client.list_autonomous_databases, compartment_id=cid)
                count += sum(1 for d in dbs if (d.lifecycle_state or "").upper() not in ("TERMINATED", "TERMINATING"))
            except ServiceError:
                continue
        if count > 2:
            paid_signals.append(f"自治数据库 {count} 个，超过免费上限 2 个")
        reasons.append(f"自治数据库 {count} 个")
    except Exception as exc:
        reasons.append(f"数据库检查失败：{exc}")

    # 4. 近 90 天是否有非零账单
    try:
        summary = usage_service.monthly_summary(tenant, days=90)
        if (summary.get("total") or 0) > 0:
            paid_signals.append(f"近 90 天产生费用 {summary['total']} {summary.get('currency', '')}")
        else:
            reasons.append("近 90 天无费用")
    except Exception as exc:
        reasons.append(f"账单检查失败：{exc}")

    if paid_signals:
        return {"detected": "paid", "reasons": paid_signals + reasons}
    return {"detected": "free", "reasons": reasons + ["未发现超出免费额度的资源或费用，疑似免费号（付费号也可能只用免费资源，仅供参考）"]}
