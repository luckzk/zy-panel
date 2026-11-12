"""账号类型检测（启发式 + 配额）。

OCI 没有"免费号/付费号"的官方 API。实测结论（2026-11-12，迪拜免费号）：
- OneSubscription 的 list_subscriptions 直接 404，不可用；
- Limits 的 list_limit_values 可用，是最接近"官方判定"的信号：
  免费号的配额特征是 vm-standard-e2-1-micro-count=2，且 E2/E3/E4/E5/E6
  等付费 Flex 机型的 core-count 全为 0；PAYG 账号默认就有 E4 等配额（>0）。
  因此：任一付费机型配额 >0 => 一定是付费号（空账号也能判定）；
  Micro=2 且付费机型配额全 0 => 符合免费版配额特征。
- 其余仍用反向启发式：超免费额度的已有资源、非零账单 => 付费号。
- 试用期费用（2026-11-12，悉尼号实测）：试用期的用量费会原样计入
  COST 总额，CREDIT 查询查不到任何抵扣、overages_flag 全为空、
  OneSubscription 同样 404，无法从单条用量区分。唯一可靠特征是
  时间形状：费用集中在连续 <=31 天内（30 天试用期），之后长期
  归零。悉尼号：8-14 至 9-11 共 29 天、每天约 13.7 SGD、最后一天
  仅 0.55（额度当天耗尽），之后 62 天零费用。因此账单信号改为：
  费用集中在 <=31 天的 burst 内且配额为免费版特征 => 试用期消耗，
  不计为付费信号；其余有费用的情况仍判付费。

结论仅供参考，用户可手动修改。
"""
import logging
from datetime import date

from oci.exceptions import ServiceError

from ..db import models
from . import oci_factory
from .instance_service import _paginate
from . import usage_service

log = logging.getLogger(__name__)

# 免费 shape 白名单（超出此范围的 running 实例 => 付费号）
FREE_SHAPES = {"VM.Standard.E2.1.Micro", "VM.Standard.A1.Flex"}

# 付费 Flex 机型的配额名：免费号这些值全为 0（迪拜免费号实测），
# PAYG 账号默认即有配额（E4 默认 >0）。任一 >0 即为付费号铁证。
PAID_CORE_LIMITS = (
    "standard-e2-core-count",
    "standard-e3-core-count",
    "standard-e4-core-count",
    "standard-e5-core-count",
    "standard-e6-core-count",
)
# 免费版 Micro 上限
MICRO_LIMIT_NAME = "vm-standard-e2-1-micro-count"


def detect_account_type(tenant: models.Tenant) -> dict:
    """返回 {"detected": "free"|"paid"|"unknown", "reasons": [...]}。"""
    reasons: list[str] = []
    paid_signals: list[str] = []

    # 0. 配额（Limits）：空账号也能判定，是最强的信号
    free_profile = False
    try:
        limits_client = oci_factory.get_limits_client(tenant)
        values = _paginate(
            limits_client.list_limit_values,
            compartment_id=tenant.tenancy_ocid, service_name="compute",
        )
        by_name: dict[str, int] = {}
        for lv in values:
            v = int(lv.value or 0)
            by_name[lv.name] = max(by_name.get(lv.name, 0), v)
        paid_quotas = {n: by_name[n] for n in PAID_CORE_LIMITS if by_name.get(n, 0) > 0}
        if paid_quotas:
            paid_signals.append(
                "付费机型配额已开通：" + "、".join(f"{n}={v}" for n, v in sorted(paid_quotas.items()))
            )
        micro_limit = by_name.get(MICRO_LIMIT_NAME)
        if micro_limit == 2 and not paid_quotas:
            free_profile = True
            reasons.append("配额符合免费版特征（Micro 上限 2 台，E2/E3/E4/E5/E6 付费机型配额为 0）")
        elif not paid_quotas:
            reasons.append(f"配额未见付费机型（Micro 上限 {micro_limit}，E2/E3/E4/E5/E6 均为 0）")
    except Exception as exc:
        reasons.append(f"配额检查失败（可能无 inspect limits 权限）：{exc}")

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

    # 4. 近 90 天账单：只看总额会把试用期消耗误判为付费，需看时间形状
    try:
        summary = usage_service.monthly_summary(tenant, days=90)
        total = summary.get("total") or 0
        currency = summary.get("currency", "")
        if total > 0:
            cost_days = sorted(
                d["date"] for d in (summary.get("daily") or []) if (d.get("amount") or 0) > 0
            )
            trial_like = False
            if len(cost_days) >= 1:
                first, last = cost_days[0], cost_days[-1]
                span = (date.fromisoformat(last) - date.fromisoformat(first)).days
                trial_like = span <= 31
            if trial_like and free_profile:
                reasons.append(
                    f"近 90 天用量费用 {total} {currency}，集中在 {first} 至 {last}"
                    f"（{span + 1} 天，符合 30 天试用期特征），配额为免费版特征，未计为付费信号"
                )
            else:
                paid_signals.append(f"近 90 天产生费用 {total} {currency}")
        else:
            reasons.append("近 90 天无费用")
    except Exception as exc:
        reasons.append(f"账单检查失败：{exc}")

    if paid_signals:
        return {"detected": "paid", "reasons": paid_signals + reasons}
    if free_profile:
        return {"detected": "free", "reasons": reasons + ["未发现超出免费额度的资源或费用，配额特征与免费版一致"]}
    return {"detected": "free", "reasons": reasons + ["未发现超出免费额度的资源或费用，疑似免费号（付费号也可能只用免费资源，仅供参考）"]}
