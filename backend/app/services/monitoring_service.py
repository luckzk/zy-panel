"""监控服务：OCI Monitoring 流量指标查询 + Limits 配额查询。

- 流量：monitoring.summarize_metrics_data，namespace=oci_vcn，
  MQL 如 VnicFromNetworkBytes[1h]{resourceId="<vnic_id>"}.sum()
- 配额：limits.list_limit_values(service_name="compute")
- 所有 OCI 异常向上抛，由 router 统一转友好错误码
"""
import logging
from datetime import datetime, timedelta, timezone

from ..db import models
from . import oci_factory

log = logging.getLogger(__name__)

METRIC_NAMESPACE = "oci_vcn"


def get_primary_vnic_id(tenant: models.Tenant, instance_id: str) -> str:
    """取实例的主 VNIC ID。"""
    compute = oci_factory.get_compute_client(tenant)
    instance = compute.get_instance(instance_id).data
    attachments = compute.list_vnic_attachments(
        compartment_id=instance.compartment_id, instance_id=instance_id
    ).data
    primary = next((a for a in attachments if getattr(a, "is_primary", False)), None)
    target = primary or (attachments[0] if attachments else None)
    if target is None:
        raise ValueError(f"实例 {instance_id} 没有找到 VNIC 附件")
    return target.vnic_id


def _summarize(
    tenant: models.Tenant,
    metric: str,
    vnic_id: str,
    start: datetime,
    end: datetime,
    resolution: str = "1h",
) -> dict:
    """单指标聚合查询，返回 {timestamp_iso: value_bytes}。"""
    import oci  # 延迟导入

    client = oci_factory.get_monitoring_client(tenant)
    details = oci.monitoring.models.SummarizeMetricsDataDetails(
        namespace=METRIC_NAMESPACE,
        query=f'{metric}[{resolution}]{{resourceId="{vnic_id}"}}.sum()',
        start_time=start,
        end_time=end,
        resolution=resolution,
    )
    resp = client.summarize_metrics_data(
        compartment_id=tenant.tenancy_ocid,
        summarize_metrics_data_details=details,
    )
    out: dict = {}
    for md in resp.data or []:
        for dp in md.aggregated_datapoints or []:
            ts = dp.timestamp
            key = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
            out[key] = float(dp.value or 0)
    return out


# 各聚合粒度对应的窗口秒数，用于 bytes -> 平均 Mbps 换算
_RESOLUTION_SECONDS = {"1m": 60, "5m": 300, "1h": 3600}
# 各粒度允许的最大回看小时数（OCI 对高粒度查询的时间窗口有限制）
_RESOLUTION_MAX_HOURS = {"1m": 6, "5m": 48, "1h": 168}


def query_vnic_traffic(
    tenant: models.Tenant, vnic_id: str, hours: int = 24, resolution: str = "1h"
) -> list[dict]:
    """查主 VNIC 出入流量，返回 [{time, inbound_mbps, outbound_mbps}]（按时间升序）。

    VnicFromNetworkBytes = 流入 VNIC 的字节（入站），VnicToNetworkBytes = 流出（出站）。
    resolution: 1m / 5m / 1h；高粒度自动收紧最大回看窗口。
    """
    if resolution not in _RESOLUTION_SECONDS:
        resolution = "1h"
    window_sec = _RESOLUTION_SECONDS[resolution]
    hours = max(1, min(_RESOLUTION_MAX_HOURS[resolution], hours))
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    inbound = _summarize(tenant, "VnicFromNetworkBytes", vnic_id, start, end, resolution)
    outbound = _summarize(tenant, "VnicToNetworkBytes", vnic_id, start, end, resolution)
    # bytes(窗口内总和) -> 平均 Mbps：bytes * 8 / 1e6 / window_sec
    factor = 8 / 1e6 / window_sec
    keys = sorted(set(inbound) | set(outbound))
    return [
        {
            "time": k,
            "inbound_mbps": round(inbound.get(k, 0) * factor, 3),
            "outbound_mbps": round(outbound.get(k, 0) * factor, 3),
        }
        for k in keys
    ]


def get_peak_bandwidth(tenant: models.Tenant, instance_id: str, hours: int = 24) -> dict:
    """实例近 N 小时峰值带宽（出向/入向 Mbps，5m 粒度取窗口平均的峰值）。

    OCI 没有实例带宽上限的 API，这里的峰值是 Monitoring 实测到的
    各 5 分钟窗口平均速率的最大值，反映实例真实跑到过的带宽。
    """
    vnic_id = get_primary_vnic_id(tenant, instance_id)
    points = query_vnic_traffic(tenant, vnic_id, hours=hours, resolution="5m")
    peak_out = max((p["outbound_mbps"] for p in points), default=0)
    peak_in = max((p["inbound_mbps"] for p in points), default=0)
    return {
        "instance_id": instance_id,
        "vnic_id": vnic_id,
        "hours": min(max(hours, 1), 48),
        "peak_egress_mbps": round(peak_out, 2),
        "peak_ingress_mbps": round(peak_in, 2),
    }


def list_compute_limits(tenant: models.Tenant, compartment_id: str) -> list[dict]:
    """查 compute 服务配额，返回 [{name, value}]。"""
    client = oci_factory.get_limits_client(tenant)
    resp = client.list_limit_values(compartment_id, service_name="compute")
    return [{"name": item.name, "value": item.value} for item in (resp.data or [])]
