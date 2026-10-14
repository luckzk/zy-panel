"""实例详情各 Tab 数据服务：对标 OCI Console 实例详情页的 9 个 Tab。

详细信息 / 网络 / 存储 / 安全 / 管理 / 操作系统管理 / 监视 / 工作请求 / 标记
全部只读查询（操作类接口在 routers/instances.py 中单独定义），单项失败降级不影响其他。
"""
import logging
from datetime import datetime, timedelta, timezone

from oci.exceptions import ServiceError

from ..db import models
from . import oci_factory
from .instance_service import OciApiError, _paginate, _translate

log = logging.getLogger(__name__)


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# ------------------------------------------------------------------ 详细信息 Tab
def get_detail_extra(inst, compute) -> dict:
    """启动选项 / 映像信息 / 容量类型 / SSH 用户名。"""
    out: dict = {}
    lo = getattr(inst, "launch_options", None)
    if lo:
        out["launch_options"] = {
            "network_type": getattr(lo, "network_type", None),
            "boot_volume_type": getattr(lo, "boot_volume_type", None),
            "remote_data_volume_type": getattr(lo, "remote_data_volume_type", None),
            "firmware": getattr(lo, "firmware", None),
            "is_pv_encryption_in_transit_enabled": getattr(lo, "is_pv_encryption_in_transit_enabled", None),
            "is_secure_boot_enabled": getattr(lo, "is_secure_boot_enabled", None),
            "is_measured_boot_enabled": getattr(lo, "is_measured_boot_enabled", None),
            "is_trusted_platform_module_enabled": getattr(lo, "is_trusted_platform_module_enabled", None),
            "is_consistent_volume_naming_enabled": getattr(lo, "is_consistent_volume_naming_enabled", None),
        }
    else:
        out["launch_options"] = None
    # 容量类型：有预留 ID 则为预留，否则按需
    out["capacity_type"] = "预留容量" if getattr(inst, "capacity_reservation_id", None) else "按需"
    out["time_created"] = _iso(getattr(inst, "time_created", None))
    # 映像信息
    out["image"] = get_image_info(compute, getattr(inst, "image_id", None))
    # SSH 用户名：按操作系统推断
    out["ssh_username"] = _infer_ssh_user((out["image"] or {}).get("operating_system"))
    return out


def get_image_info(compute, image_id: str | None) -> dict | None:
    if not image_id:
        return None
    try:
        img = compute.get_image(image_id).data
    except Exception as exc:
        log.warning("查询映像 %s 失败: %s", image_id, exc)
        return None
    return {
        "id": image_id,
        "display_name": getattr(img, "display_name", None),
        "operating_system": getattr(img, "operating_system", None),
        "operating_system_version": getattr(img, "operating_system_version", None),
    }


def _infer_ssh_user(os_name: str | None) -> str:
    os_name = (os_name or "").lower()
    if "ubuntu" in os_name or "canonical" in os_name:
        return "ubuntu"
    if "oracle linux" in os_name or "oel" in os_name:
        return "opc"
    if "centos" in os_name:
        return "opc"
    if "debian" in os_name:
        return "admin"
    if "fedora" in os_name:
        return "fedora"
    return ""


# ------------------------------------------------------------------ 网络 Tab
def get_network_tab(network, compute, instance_id: str, compartment_id: str, vnic_full: dict | None) -> dict:
    """路由表名 / 内部 FQDN / 附加 VNIC 列表。"""
    out: dict = {"route_table_name": "", "internal_fqdn": "", "vnic_attachments": []}
    if not vnic_full:
        return out
    # 路由表名 + 内部 FQDN
    try:
        subnet_id = vnic_full.get("subnet_id")
        if subnet_id:
            subnet = network.get_subnet(subnet_id).data
            rt_id = getattr(subnet, "route_table_id", None)
            if rt_id:
                try:
                    out["route_table_name"] = network.get_route_table(rt_id).data.display_name or ""
                except Exception:
                    pass
            # 内部 FQDN = 主机名 + 子网域名
            hostname = vnic_full.get("hostname") or ""
            dns_label = getattr(subnet, "dns_label", None)
            if hostname and dns_label:
                out["internal_fqdn"] = f"{hostname}.{dns_label}.oraclevcn.com"
            elif hostname:
                out["internal_fqdn"] = hostname
    except Exception as exc:
        log.warning("查询路由表/FQDN 失败: %s", exc)
    # 附加 VNIC 列表
    try:
        atts = _paginate(compute.list_vnic_attachments, compartment_id=compartment_id,
                         instance_id=instance_id)
        for a in atts:
            vid = getattr(a, "vnic_id", None)
            name = ""
            state = ""
            if vid:
                try:
                    v = network.get_vnic(vid).data
                    name = getattr(v, "display_name", "") or ""
                    state = getattr(v, "lifecycle_state", "") or ""
                except Exception:
                    pass
            out["vnic_attachments"].append({
                "id": getattr(a, "id", ""),
                "vnic_id": vid or "",
                "display_name": name,
                "lifecycle_state": getattr(a, "lifecycle_state", "") or state,
                "nic_index": getattr(a, "nic_index", None),
                "time_created": _iso(getattr(a, "time_created", None)),
            })
    except Exception as exc:
        log.warning("查询 VNIC 挂载列表失败: %s", exc)
    return out


# ------------------------------------------------------------------ 存储 Tab
def get_storage_tab(compute, blockstorage, compartment_id: str, instance_id: str,
                     availability_domain: str | None, image_id: str | None = None) -> dict:
    """引导卷扩展字段 + 数据卷扩展字段。"""
    out: dict = {"boot_volume": None, "data_volumes": []}
    # 引导卷
    try:
        atts = _paginate(compute.list_boot_volume_attachments,
                         availability_domain=availability_domain,
                         compartment_id=compartment_id, instance_id=instance_id)
        att = next((a for a in atts if getattr(a, "lifecycle_state", "") == "ATTACHED"), atts[0] if atts else None)
        if att and getattr(att, "boot_volume_id", None):
            bv = blockstorage.get_boot_volume(att.boot_volume_id).data
            # 来源映像：OCI 不返回已建卷的 source_details，用实例的 image_id
            image_name = ""
            if image_id:
                try:
                    image_name = compute.get_image(image_id).data.display_name or ""
                except Exception:
                    pass
            out["boot_volume"] = {
                "id": bv.id,
                "display_name": getattr(bv, "display_name", None),
                "size_in_gbs": getattr(bv, "size_in_gbs", None),
                "lifecycle_state": getattr(bv, "lifecycle_state", None),
                "is_transit_encryption_enabled": getattr(bv, "is_transit_encryption_enabled", None),
                "time_created": _iso(getattr(bv, "time_created", None)),
                "attached_time": _iso(getattr(att, "time_created", None)),
                "source_image": image_name,
                "volume_type": getattr(bv, "volume_type", None),
            }
    except Exception as exc:
        log.warning("存储 Tab 引导卷查询失败: %s", exc)
    # 数据卷
    try:
        atts = _paginate(compute.list_volume_attachments, compartment_id=compartment_id,
                         instance_id=instance_id)
        for a in atts:
            vid = getattr(a, "volume_id", None)
            if not vid:
                continue
            try:
                v = blockstorage.get_volume(vid).data
            except Exception:
                continue
            out["data_volumes"].append({
                "id": vid,
                "display_name": getattr(v, "display_name", None),
                "size_in_gbs": getattr(v, "size_in_gbs", None),
                "lifecycle_state": getattr(v, "lifecycle_state", None),
                "volume_type": getattr(v, "volume_type", None),
                "vpus_per_gb": getattr(v, "vpus_per_gb", None),
                "is_transit_encryption_enabled": getattr(v, "is_transit_encryption_enabled", None),
                "device": getattr(a, "device", None),
                "attachment_type": getattr(a, "attachment_type", None),
                "is_read_only": getattr(a, "is_read_only", None),
                "time_created": _iso(getattr(v, "time_created", None)),
                "attached_time": _iso(getattr(a, "time_created", None)),
            })
    except Exception as exc:
        log.warning("存储 Tab 数据卷查询失败: %s", exc)
    return out


# ------------------------------------------------------------------ 安全 Tab
def get_security_tab(network, vnic_full: dict | None) -> dict:
    """VNIC 关联安全列表的入站/出站规则明细。"""
    out: dict = {"security_list_rules": []}
    if not vnic_full:
        return out
    try:
        subnet_id = vnic_full.get("subnet_id")
        if not subnet_id:
            return out
        subnet = network.get_subnet(subnet_id).data
        for sl_id in list(getattr(subnet, "security_list_ids", None) or []):
            try:
                sl = network.get_security_list(sl_id).data
            except Exception:
                continue
            rules = []
            for r in list(getattr(sl, "ingress_security_rules", None) or []):
                rules.append({"direction": "入站", "protocol": getattr(r, "protocol", ""),
                              "source": getattr(r, "source", ""),
                              "source_type": getattr(r, "source_type", ""),
                              "description": getattr(r, "description", "") or ""})
            for r in list(getattr(sl, "egress_security_rules", None) or []):
                rules.append({"direction": "出站", "protocol": getattr(r, "protocol", ""),
                              "source": getattr(r, "destination", ""),
                              "source_type": getattr(r, "destination_type", ""),
                              "description": getattr(r, "description", "") or ""})
            out["security_list_rules"].append({
                "id": sl_id,
                "name": getattr(sl, "display_name", "") or "",
                "rules": rules,
            })
    except Exception as exc:
        log.warning("安全 Tab 查询失败: %s", exc)
    return out

# ------------------------------------------------------------------ 管理 Tab
def get_management_tab(compute, compartment_id: str, instance_id: str) -> dict:
    """维护事件列表。"""
    out: dict = {"maintenance_events": []}
    try:
        events = _paginate(compute.list_instance_maintenance_events,
                           compartment_id=compartment_id, instance_id=instance_id)
        for e in events:
            out["maintenance_events"].append({
                "id": getattr(e, "id", ""),
                "display_name": getattr(e, "display_name", "") or "",
                "maintenance_category": getattr(e, "maintenance_category", "") or "",
                "maintenance_reason": getattr(e, "maintenance_reason", "") or "",
                "lifecycle_state": getattr(e, "lifecycle_state", "") or "",
                "time_started": _iso(getattr(e, "time_started", None)),
                "time_finished": _iso(getattr(e, "time_finished", None)),
                "time_window_start": _iso(getattr(e, "time_window_start", None)),
            })
    except Exception as exc:
        log.warning("维护事件查询失败: %s", exc)
    return out


def get_agent_plugins(tenant: models.Tenant, compartment_id: str, instance_id: str) -> dict:
    """Cloud Agent 插件列表。需要 instanceagent_id，拿不到时降级提示。"""
    out: dict = {"plugins": [], "available": False, "note": ""}
    try:
        import oci.compute_instance_agent as cia
        agent_client = cia.ComputeInstanceAgentClient(oci_factory.build_oci_config(tenant))
        plugin_client = cia.PluginClient(oci_factory.build_oci_config(tenant))
        # 从该实例的 agent 命令反查 instanceagent_id
        instanceagent_id = None
        try:
            cmds = agent_client.list_instance_agent_commands(compartment_id, limit=50).data
            for cmd in cmds or []:
                if getattr(cmd, "target", None) and getattr(cmd.target, "instance_id", None) == instance_id:
                    instanceagent_id = getattr(cmd, "instance_agent_id", None)
                    break
        except Exception:
            pass
        if not instanceagent_id:
            out["note"] = "未找到该实例的 Cloud Agent（可能未安装或未启用插件）"
            return out
        plugins = plugin_client.list_instance_agent_plugins(compartment_id, instanceagent_id).data
        for p in plugins or []:
            out["plugins"].append({
                "name": getattr(p, "name", "") or "",
                "status": getattr(p, "status", "") or "",
                "time_last_updated": _iso(getattr(p, "time_last_updated", None)),
            })
        out["available"] = True
    except Exception as exc:
        log.warning("Agent 插件查询失败: %s", exc)
        out["note"] = f"查询失败：{str(exc)[:150]}"
    return out


# ------------------------------------------------------------------ 工作请求 Tab
def get_work_requests(tenant: models.Tenant, compartment_id: str, instance_id: str) -> dict:
    """与该实例相关的工作请求。"""
    out: dict = {"work_requests": []}
    try:
        import oci.work_requests as wr
        wr_client = wr.WorkRequestClient(oci_factory.build_oci_config(tenant))
        reqs = _paginate(wr_client.list_work_requests, compartment_id=compartment_id)
        for r in reqs:
            resources = getattr(r, "resources", None) or []
            hit = any(instance_id in (getattr(res, "identifier", "") or "") for res in resources)
            if not hit:
                # 按操作目标匹配实例名兜底
                continue
            out["work_requests"].append({
                "id": getattr(r, "id", ""),
                "operation_type": getattr(r, "operation_type", "") or "",
                "status": getattr(r, "status", "") or "",
                "percent_complete": getattr(r, "percent_complete", None),
                "time_accepted": _iso(getattr(r, "time_accepted", None)),
                "time_finished": _iso(getattr(r, "time_finished", None)),
            })
    except Exception as exc:
        log.warning("工作请求查询失败: %s", exc)
    return out


# ------------------------------------------------------------------ 操作系统管理 Tab：控制台历史记录
def capture_console_history(compute, instance_id: str) -> dict:
    """截取控制台历史（生成快照）。"""
    import oci.core.models as m
    details = m.CaptureConsoleHistoryDetails(instance_id=instance_id)
    try:
        resp = compute.capture_console_history(details)
    except ServiceError as exc:
        raise _translate(exc, "截取控制台历史")
    h = resp.data
    return {"id": getattr(h, "id", ""), "lifecycle_state": getattr(h, "lifecycle_state", ""),
            "time_created": _iso(getattr(h, "time_created", None))}


def get_console_history_content(compute, history_id: str) -> dict:
    """获取控制台历史内容（base64 解码为文本）。"""
    try:
        resp = compute.get_console_history_content(history_id)
    except ServiceError as exc:
        raise _translate(exc, "获取控制台历史内容")
    raw = resp.data
    text = ""
    # SDK 返回的已是解码后的文本（bytes 或 str），直接 decode 即可
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    elif isinstance(raw, str):
        text = raw
    return {"history_id": history_id, "content": text[-20000:]}  # 只返最后 20KB


# ------------------------------------------------------------------ 监视 Tab
_AGENT_METRICS = [
    ("CpuUtilization", "CPU 占用率", "percent"),
    ("MemoryUtilization", "内存使用率", "percent"),
    ("DiskIopsRead", "磁盘读 IOPS", "count"),
    ("DiskIopsWrite", "磁盘写 IOPS", "count"),
    ("DiskBytesRead", "磁盘读取字节", "bytes"),
    ("DiskBytesWrite", "磁盘写入字节", "bytes"),
    ("NetworkBytesIn", "网络接收字节", "bytes"),
    ("NetworkBytesOut", "网络发送字节", "bytes"),
]


def get_instance_metrics(tenant: models.Tenant, instance_id: str, hours: int = 6) -> dict:
    """实例监控度量（oci_computeagent 命名空间，需 Cloud Agent）。"""
    import oci.monitoring.models as mm
    monitoring = oci_factory.get_monitoring_client(tenant)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=max(1, min(hours, 72)))
    charts: list[dict] = []
    for metric, title, _unit in _AGENT_METRICS:
        try:
            q = (f"{metric}[1h]{{resourceId = \"{instance_id}\"}}"
                 f".mean()")
            details = mm.SummarizeMetricsDataDetails(
                namespace="oci_computeagent",
                query=q,
                start_time=start,
                end_time=end,
                resolution="1h",
            )
            resp = monitoring.summarize_metrics_data(
                tenant.tenancy_ocid, details)
            points = []
            for item in resp.data or []:
                for dp in item.aggregated_datapoints or []:
                    points.append({"time": _iso(dp.timestamp), "value": round(dp.value or 0, 2)})
            points.sort(key=lambda p: p["time"] or "")
            charts.append({"metric": metric, "title": title, "points": points})
        except Exception as exc:
            log.warning("指标 %s 查询失败: %s", metric, exc)
            charts.append({"metric": metric, "title": title, "points": [], "error": str(exc)[:150]})
    return {"instance_id": instance_id, "hours": hours, "charts": charts}


# ------------------------------------------------------------------ 操作类
def create_custom_image(compute, compartment_id: str, instance_id: str, display_name: str) -> dict:
    """创建定制映像（实例需关机）。"""
    import oci.core.models as m
    details = m.CreateImageDetails(compartment_id=compartment_id, instance_id=instance_id,
                                   display_name=display_name)
    try:
        resp = compute.create_image(details)
    except ServiceError as exc:
        raise _translate(exc, "创建定制映像")
    img = resp.data
    return {"id": getattr(img, "id", ""), "display_name": getattr(img, "display_name", ""),
            "lifecycle_state": getattr(img, "lifecycle_state", "")}


def change_instance_compartment(compute, instance_id: str, compartment_id: str) -> dict:
    """移动实例到其他 compartment。"""
    import oci.core.models as m
    details = m.ChangeInstanceCompartmentDetails(compartment_id=compartment_id)
    try:
        compute.change_instance_compartment(instance_id, details)
    except ServiceError as exc:
        raise _translate(exc, "移动实例")
    return {"instance_id": instance_id, "compartment_id": compartment_id}


def diagnostic_action(compute, instance_id: str, action: str) -> dict:
    """诊断操作：SENDDIAGNOSTICINTERRUPT / DIAGNOSTICREBOOT。"""
    if action not in ("SENDDIAGNOSTICINTERRUPT", "DIAGNOSTICREBOOT"):
        raise OciApiError(3103, f"不支持的诊断操作：{action}", 400)
    try:
        compute.instance_action(instance_id, action)
    except ServiceError as exc:
        raise _translate(exc, "诊断操作")
    return {"instance_id": instance_id, "action": action}


def run_instance_command(tenant: models.Tenant, compartment_id: str, instance_id: str,
                         content: str, display_name: str = "") -> dict:
    """在实例上运行命令（需 Cloud Agent 的 Run Command 插件）。"""
    import oci.compute_instance_agent as cia
    import oci.compute_instance_agent.models as m
    agent_client = cia.ComputeInstanceAgentClient(oci_factory.build_oci_config(tenant))
    # 找 instanceagent_id
    instanceagent_id = None
    try:
        cmds = agent_client.list_instance_agent_commands(compartment_id, limit=50).data
        for cmd in cmds or []:
            if getattr(cmd, "target", None) and getattr(cmd.target, "instance_id", None) == instance_id:
                instanceagent_id = getattr(cmd, "instance_agent_id", None)
                break
    except Exception as exc:
        raise OciApiError(3103, f"查询 Cloud Agent 失败：{exc}", 502)
    if not instanceagent_id:
        raise OciApiError(3103, "该实例未安装/启用 Cloud Agent，无法运行命令", 400)
    import base64 as _b64
    details = m.CreateInstanceAgentCommandDetails(
        compartment_id=compartment_id,
        instance_agent_id=instanceagent_id,
        target=m.InstanceAgentCommandTarget(instance_id=instance_id),
        content=m.InstanceAgentCommandContent(
            source=m.InstanceAgentCommandContentSourceText(
                source_type="TEXT",
                text=_b64.b64encode(content.encode()).decode(),
            )
        ),
        display_name=display_name or f"panel-run-{datetime.now(timezone.utc):%m%d%H%M%S}",
        execution_time_out_in_seconds=300,
    )
    try:
        resp = agent_client.create_instance_agent_command(details)
    except ServiceError as exc:
        raise _translate(exc, "运行实例命令")
    cmd = resp.data
    return {"id": getattr(cmd, "id", ""), "display_name": getattr(cmd, "display_name", "")}


def get_command_execution(tenant: models.Tenant, command_id: str) -> dict:
    """查询命令执行结果。"""
    import oci.compute_instance_agent as cia
    agent_client = cia.ComputeInstanceAgentClient(oci_factory.build_oci_config(tenant))
    try:
        cmd = agent_client.get_instance_agent_command(command_id).data
        execs = agent_client.list_instance_agent_command_executions(compartment_id="", instance_agent_command_id=command_id).data
    except ServiceError as exc:
        raise _translate(exc, "查询命令执行结果")
    out_execs = []
    for e in execs or []:
        out_execs.append({
            "instance_id": getattr(e, "instance_id", ""),
            "delivery_state": getattr(e, "delivery_state", ""),
            "lifecycle_state": getattr(e, "lifecycle_state", ""),
            "time_created": _iso(getattr(e, "time_created", None)),
        })
    return {"id": command_id, "display_name": getattr(cmd, "display_name", ""),
            "lifecycle_state": getattr(cmd, "lifecycle_state", ""),
            "executions": out_execs}
