"""费用用量服务：OCI Usage API（request_summarized_usages）封装。

注意：无真实凭据可验证，所有返回字段均防御性取值（getattr 兜底），
异常向上抛由 router 转为友好错误。
"""
import logging
from datetime import datetime, timedelta, timezone

from . import oci_factory

log = logging.getLogger(__name__)

_GRANULARITY_MAP = {
    "DAILY": "DAILY",
    "MONTHLY": "MONTHLY",
    "TOTAL": "TOTAL",
}


def _details_class():
    import oci.usage_api.models as m

    return m.RequestSummarizedUsagesDetails


def _build_details(tenant_id: str, start: datetime, end: datetime, granularity: str, with_group_by: bool):
    cls = _details_class()
    kwargs = {
        "tenant_id": tenant_id,
        "time_usage_started": start,
        "time_usage_ended": end,
        "granularity": _GRANULARITY_MAP.get(granularity, "DAILY"),
    }
    if with_group_by:
        kwargs["group_by"] = ["resourceId"]
    return cls(**kwargs)


def _item_to_dict(item) -> dict:
    """UsageSummary -> 前端友好的 dict，全部防御性取值。"""
    t = getattr(item, "time_usage_started", None)
    if hasattr(t, "isoformat"):
        time_str = t.isoformat()
    else:
        time_str = str(t) if t else ""
    amount = getattr(item, "computed_amount", 0) or 0
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        amount = 0.0
    quantity = getattr(item, "computed_quantity", 0) or 0
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        quantity = 0.0
    resource_id = getattr(item, "resource_id", "") or ""
    service = getattr(item, "service", "") or "" or _infer_service(resource_id)
    currency = (getattr(item, "currency", "") or "").strip()
    return {
        "time": time_str,
        "service": service,
        "resource_id": resource_id,
        "resource_name": getattr(item, "resource_name", "") or _short_resource_name(resource_id),
        "amount": round(amount, 4),
        "quantity": quantity,
        "currency": currency,
    }


# OCID 前缀 -> 服务名（OCI 对零费用条目不返回 service 元数据，只能从 resource_id 推断）
_OCID_SERVICE_MAP: list[tuple[str, str]] = [
    ("ocid1.instance", "计算实例"),
    ("ocid1.bootvolume", "块存储·引导卷"),
    ("ocid1.volume", "块存储·数据卷"),
    ("ocid1.volumebackup", "块存储·备份"),
    ("ocid1.bootvolumebackup", "块存储·备份"),
    ("ocid1.vnic", "虚拟网络·VNIC"),
    ("ocid1.publicip", "虚拟网络·公网 IP"),
    ("ocid1.subnet", "虚拟网络·子网"),
    ("ocid1.vcn", "虚拟网络·VCN"),
    ("ocid1.natgateway", "虚拟网络·NAT 网关"),
    ("ocid1.internetgateway", "虚拟网络·网关"),
    ("ocid1.loadbalancer", "负载均衡"),
    ("ocid1.autonomousdatabase", "自治数据库"),
    ("ocid1.database", "数据库"),
    ("ocid1.bucket", "对象存储"),
    ("ocid1.dns", "DNS"),
    ("ocid1.vault", "密钥管理"),
    ("oci_computeagent", "计算·监控代理"),
]


def _infer_service(resource_id: str) -> str:
    """从 resource_id 推断服务名。"""
    rid = (resource_id or "").lower()
    for prefix, name in _OCID_SERVICE_MAP:
        if rid.startswith(prefix):
            return name
    return ""


def _short_resource_name(resource_id: str) -> str:
    """resource_id 的可读短展示：类型后缀 + 短 ID。"""
    rid = resource_id or ""
    if not rid:
        return ""
    # ocid1.xxx.oc1.region.xxxxx -> 取最后一段
    short = rid.split(".")[-1][-12:]
    for prefix, name in _OCID_SERVICE_MAP:
        if rid.lower().startswith(prefix):
            return f"{name} …{short}"
    return f"…{short}"


def query_usage(tenant, days: int = 30, granularity: str = "DAILY") -> list[dict]:
    """查询租户用量明细。group_by 不支持时自动降级为不分组查询。"""
    client = oci_factory.get_usage_client(tenant)
    # OCI 用量接口要求时间精度到天（时分秒必须为 0），否则报 InvalidParameter
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = (end - timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0)

    # 先尝试按 resourceId 分组，失败则降级
    for with_group_by in (True, False):
        try:
            details = _build_details(tenant.tenancy_ocid, start, end, granularity, with_group_by)
            break
        except TypeError as exc:
            if with_group_by:
                log.warning("group_by 不被支持，降级为不分组查询：%s", exc)
                continue
            raise
    else:  # pragma: no cover - 防御
        raise RuntimeError("无法构建用量查询参数")

    items: list[dict] = []
    page = None
    while True:
        kwargs = {"request_summarized_usages_details": details}
        if page:
            kwargs["page"] = page
        try:
            resp = client.request_summarized_usages(**kwargs)
        except TypeError as exc:
            # 某些 SDK 版本 group_by 会在请求时才报错，降级重试一次
            if with_group_by and "group_by" in str(exc).lower():
                log.warning("group_by 请求期失败，降级为不分组查询：%s", exc)
                details = _build_details(tenant.tenancy_ocid, start, end, granularity, False)
                resp = client.request_summarized_usages(request_summarized_usages_details=details)
            else:
                raise
        data = getattr(resp, "data", None)
        raw_items = getattr(data, "items", None) or []
        items.extend(_item_to_dict(i) for i in raw_items)
        page = resp.headers.get("opc-next-page") if hasattr(resp, "headers") else None
        if not page:
            break
    return items


def monthly_summary(tenant, days: int = 30) -> dict:
    """近 N 天汇总：总费用、币种、按服务分组、按日聚合。"""
    items = query_usage(tenant, days=days, granularity="DAILY")
    total = 0.0
    currency = ""
    by_service: dict[str, float] = {}
    daily: dict[str, float] = {}
    for it in items:
        amt = it["amount"]
        total += amt
        if not currency and it["currency"]:
            currency = it["currency"]
        svc = it["service"] or "未知服务"
        by_service[svc] = by_service.get(svc, 0.0) + amt
        day = (it["time"] or "")[:10]
        if day:
            daily[day] = daily.get(day, 0.0) + amt

    by_service_list = [
        {"name": name, "amount": round(amt, 4)} for name, amt in sorted(by_service.items(), key=lambda x: -x[1])
    ]
    daily_list = [{"date": d, "amount": round(a, 4)} for d, a in sorted(daily.items())]
    return {
        "total": round(total, 4),
        "currency": currency,
        "by_service": by_service_list,
        "daily": daily_list,
        "days": days,
    }
