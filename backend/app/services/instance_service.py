"""实例查询服务：真实 OCI SDK 调用。

- 按租户遍历其有权限的全部 compartment（含子级），聚合实例列表
- 为每个实例补全主 VNIC 的公网 / 私网 IP
- OCI SDK 异常统一翻译为 OciApiError，由路由层映射为接口错误码

注意：OCI Python SDK 为同步阻塞调用，路由层保持 `def`（非 async），
FastAPI 会将其放到线程池执行，不会阻塞事件循环。
"""
import logging

import oci
from oci.exceptions import ConnectTimeout, RequestException, ServiceError

from ..db import models
from .oci_factory import get_blockstorage_client, get_compute_client, get_identity_client, get_network_client

log = logging.getLogger(__name__)


class OciApiError(Exception):
    """可直接映射为接口错误码的 OCI 调用异常。"""

    def __init__(self, code: int, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _translate(exc: ServiceError, op: str) -> OciApiError:
    """把 OCI ServiceError 翻译为面向用户的错误码。"""
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {exc.message}", 502)


def _paginate(list_fn, **kwargs) -> list:
    """通用的 OCI 列表分页收集（opc-next-page）。"""
    items: list = []
    page = None
    while True:
        resp = list_fn(page=page, **kwargs) if page else list_fn(**kwargs)
        items.extend(resp.data)
        page = resp.headers.get("opc-next-page")
        if not page:
            break
    return items


def _short_ad(ad: str | None) -> str:
    """'abcd:AP-TOKYO-1-AD-1' -> 'AD-1'，展示用短名。"""
    if not ad:
        return ""
    return "AD-" + ad.split(":")[-1].split("-")[-1]


def _to_out(inst, tenant: models.Tenant, vnic_map: dict, compartment_names: dict) -> dict:
    vnic = vnic_map.get(inst.id) or {}
    shape_cfg = inst.shape_config
    tc = inst.time_created
    time_created = tc.isoformat() if hasattr(tc, "isoformat") else tc
    return {
        "id": inst.id,
        "display_name": inst.display_name,
        "lifecycle_state": inst.lifecycle_state,
        "shape": inst.shape,
        "ocpus": getattr(shape_cfg, "ocpus", None),
        "memory_in_gbs": getattr(shape_cfg, "memory_in_gbs", None),
        "region": tenant.region,
        "availability_domain": _short_ad(inst.availability_domain),
        "compartment_id": inst.compartment_id,
        "compartment_name": compartment_names.get(inst.compartment_id, ""),
        "public_ip": vnic.get("public_ip"),
        "private_ip": vnic.get("private_ip"),
        "time_created": time_created,
    }


def _compute_network(tenant: models.Tenant):
    """建 compute/network client，统一异常翻译。"""
    try:
        return get_compute_client(tenant), get_network_client(tenant)
    except ValueError as exc:  # 私钥解密失败等配置问题
        raise OciApiError(3101, f"租户配置异常：{exc}", 502)


def _primary_vnic_ips(network, compute, instance_id: str, compartment_id: str) -> dict:
    """取实例主 VNIC 的公网/私网 IP（单点失败降级为空）。"""
    try:
        attachments = _paginate(compute.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance_id, limit=10)
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "查询 VNIC 挂载")
    primary = next(
        (a for a in attachments if getattr(a, "lifecycle_state", "") == "ATTACHED"),
        attachments[0] if attachments else None,
    )
    if primary is None:
        return {"public_ip": None, "private_ip": None}
    try:
        v = network.get_vnic(primary.vnic_id).data
        return {"public_ip": v.public_ip, "private_ip": v.private_ip}
    except ServiceError as exc:
        log.warning("获取 VNIC %s 失败: %s", primary.vnic_id, exc.message)
        return {"public_ip": None, "private_ip": None}
    except Exception as exc:  # 超时/网络抖动等非 ServiceError 也降级，不抛 500
        log.warning("获取 VNIC %s 未知异常: %s", primary.vnic_id, exc)
        return {"public_ip": None, "private_ip": None}


def _get_security_groups(network, vnic) -> dict:
    """VNIC 关联的安全组：NSG 列表 + 子网安全列表。失败降级为空。"""
    out: dict = {"nsgs": [], "security_lists": []}
    # NSG：vnic.nsg_ids -> 名称
    try:
        for nsg_id in list(getattr(vnic, "nsg_ids", None) or []):
            try:
                nsg = network.get_network_security_group(nsg_id).data
                out["nsgs"].append({"id": nsg_id, "name": getattr(nsg, "display_name", "") or ""})
            except Exception:
                out["nsgs"].append({"id": nsg_id, "name": ""})
    except Exception as exc:
        log.warning("查询 NSG 失败: %s", exc)
    # 子网的安全列表
    try:
        subnet_id = getattr(vnic, "subnet_id", None)
        if subnet_id:
            subnet = network.get_subnet(subnet_id).data
            for sl_id in list(getattr(subnet, "security_list_ids", None) or []):
                try:
                    sl = network.get_security_list(sl_id).data
                    out["security_lists"].append({"id": sl_id, "name": getattr(sl, "display_name", "") or ""})
                except Exception:
                    out["security_lists"].append({"id": sl_id, "name": ""})
    except Exception as exc:
        log.warning("查询子网安全列表失败: %s", exc)
    return out


def _get_primary_vnic_full(network, compute, instance_id: str, compartment_id: str) -> dict | None:
    """主 VNIC 完整信息：ID / 子网 / MAC / 主机名 / IP（失败降级为 None）。"""
    try:
        attachments = _paginate(compute.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance_id, limit=10)
    except Exception as exc:
        log.warning("查询 VNIC 挂载失败: %s", exc)
        return None
    primary = next(
        (a for a in attachments if getattr(a, "lifecycle_state", "") == "ATTACHED"),
        attachments[0] if attachments else None,
    )
    if primary is None or not getattr(primary, "vnic_id", None):
        return None
    try:
        v = network.get_vnic(primary.vnic_id).data
    except Exception as exc:
        log.warning("获取 VNIC %s 失败: %s", primary.vnic_id, exc)
        return None
    subnet_name = None
    try:
        subnet_name = network.get_subnet(v.subnet_id).data.display_name
    except Exception:
        pass
    ipv6s: list[str] = []
    try:
        for ip6 in _paginate(network.list_ipv6s, vnic_id=v.id):
            addr = getattr(ip6, "ip_address", None)
            if addr:
                ipv6s.append(addr)
    except Exception:
        pass
    return {
        "id": v.id,
        "subnet_id": getattr(v, "subnet_id", None),
        "subnet_name": subnet_name,
        "mac": getattr(v, "mac_addr", None),
        "hostname": getattr(v, "hostname_label", None),
        "public_ip": getattr(v, "public_ip", None),
        "private_ip": getattr(v, "private_ip", None),
        "ipv6_addresses": ipv6s,
        "nsg_ids": list(getattr(v, "nsg_ids", None) or []),
        "security_groups": _get_security_groups(network, v),
    }


def _get_boot_volume_info(compute, blockstorage, compartment_id: str, instance_id: str,
                          availability_domain: str | None = None) -> dict | None:
    """实例引导卷：名称 + 大小（无挂载或失败时返回 None）。

    注意：list_boot_volume_attachments 必填 availability_domain + compartment_id。
    """
    if not availability_domain:
        # 兜底：从实例查 AD
        try:
            availability_domain = compute.get_instance(instance_id).data.availability_domain
        except Exception as exc:
            log.warning("获取实例 AD 失败: %s", exc)
            return None
    try:
        atts = _paginate(
            compute.list_boot_volume_attachments,
            availability_domain=availability_domain,
            compartment_id=compartment_id,
            instance_id=instance_id,
        )
    except Exception as exc:
        log.warning("查询引导卷挂载失败: %s", exc)
        return None
    att = next(
        (a for a in atts if getattr(a, "lifecycle_state", "") == "ATTACHED"),
        atts[0] if atts else None,
    )
    vol_id = getattr(att, "boot_volume_id", None) if att else None
    if not vol_id:
        return None
    try:
        bv = blockstorage.get_boot_volume(vol_id).data
        return {
            "id": bv.id,
            "display_name": getattr(bv, "display_name", None),
            "size_in_gbs": getattr(bv, "size_in_gbs", None),
        }
    except Exception as exc:
        log.warning("获取引导卷 %s 失败: %s", vol_id, exc)
        return None


def _get_data_volumes(compute, blockstorage, compartment_id: str, instance_id: str) -> list[dict]:
    """实例挂载的数据卷列表（失败时返回空列表）。"""
    try:
        atts = _paginate(
            compute.list_volume_attachments,
            compartment_id=compartment_id,
            instance_id=instance_id,
        )
    except Exception as exc:
        log.warning("查询数据卷挂载失败: %s", exc)
        return []
    out = []
    for a in atts:
        if getattr(a, "lifecycle_state", "") != "ATTACHED":
            continue
        vol_id = getattr(a, "volume_id", None)
        if not vol_id:
            continue
        try:
            vol = blockstorage.get_volume(vol_id).data
            out.append(
                {
                    "id": vol.id,
                    "display_name": getattr(vol, "display_name", None),
                    "size_in_gbs": getattr(vol, "size_in_gbs", None),
                }
            )
        except Exception as exc:
            log.warning("获取数据卷 %s 失败: %s", vol_id, exc)
    return out


def get_instance_detail(tenant: models.Tenant, instance_id: str) -> dict:
    """实例详情：get_instance + 主 VNIC 的 IP 补全 + 资源/网络/存储扩展信息。"""
    compute, network = _compute_network(tenant)
    try:
        inst = compute.get_instance(instance_id).data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "获取实例详情")
    vnic_ips = _primary_vnic_ips(network, compute, instance_id, inst.compartment_id)
    out = _to_out(inst, tenant, {inst.id: vnic_ips}, {})
    # 扩展信息：单点失败降级，不影响详情主体
    try:
        blockstorage = get_blockstorage_client(tenant)
    except ValueError:
        blockstorage = None
    vnic_full = _get_primary_vnic_full(network, compute, instance_id, inst.compartment_id)
    boot_volume = _get_boot_volume_info(
        compute, blockstorage, inst.compartment_id, instance_id,
        availability_domain=inst.availability_domain,
    ) if blockstorage else None
    data_volumes = _get_data_volumes(compute, blockstorage, inst.compartment_id, instance_id) if blockstorage else []
    network_bandwidth = _get_shape_bandwidth(compute, inst.compartment_id, inst.shape)
    compartment_name = _get_compartment_name(tenant, inst.compartment_id)
    out.update(
        {
            "availability_domain_full": inst.availability_domain,
            "fault_domain": getattr(inst, "fault_domain", None),
            "image_id": getattr(inst, "image_id", None),
            "defined_tags": getattr(inst, "defined_tags", None),
            "freeform_tags": getattr(inst, "freeform_tags", None),
            "vnic": vnic_full,
            "boot_volume": boot_volume,
            "data_volumes": data_volumes,
            "network_bandwidth_gbps": network_bandwidth,
            "compartment_name": compartment_name,
        }
    )
    return out


def _get_compartment_name(tenant: models.Tenant, compartment_id: str | None) -> str:
    """查 compartment 显示名称（含根 compartment），失败返回空字符串。"""
    if not compartment_id:
        return ""
    try:
        identity = get_identity_client(tenant)
        return identity.get_compartment(compartment_id).data.name or ""
    except Exception as exc:
        log.warning("查询 compartment 名称失败: %s", exc)
        return ""


def _get_shape_bandwidth(compute, compartment_id: str, shape: str | None) -> float | None:
    """实例 Shape 的理论网络带宽（Gbps），走 list_shapes 实时查询，失败降级为 None。

    对应 OCI 官方控制台实例详情里展示的"带宽"。Flex 机型的带宽随 OCPU
    变化，这里取该 Shape 的基准值。
    """
    if not shape:
        return None
    try:
        shapes = _paginate(compute.list_shapes, compartment_id=compartment_id, limit=100)
    except Exception as exc:
        log.warning("查询 Shape 带宽失败: %s", exc)
        return None
    for s in shapes:
        if getattr(s, "shape", None) == shape:
            bw = getattr(s, "networking_bandwidth_in_gbps", None)
            return float(bw) if bw is not None else None
    return None


def power_instance(tenant: models.Tenant, instance_id: str, action: str) -> dict:
    """电源操作：start / stop(硬关) / reboot。"""
    compute, _ = _compute_network(tenant)
    try:
        compute.instance_action(instance_id, action.upper())
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, f"实例{action}")
    return {"instance_id": instance_id, "action": action, "accepted": True}


def rename_instance(tenant: models.Tenant, instance_id: str, display_name: str) -> dict:
    """修改实例显示名。"""
    compute, _ = _compute_network(tenant)
    details = oci.core.models.UpdateInstanceDetails(display_name=display_name)
    try:
        inst = compute.update_instance(instance_id, details).data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "修改实例名称")
    return {"instance_id": instance_id, "display_name": inst.display_name}


def terminate_instance(tenant: models.Tenant, instance_id: str, preserve_boot_volume: bool) -> dict:
    """终止实例，可选是否保留引导卷。"""
    compute, _ = _compute_network(tenant)
    try:
        compute.terminate_instance(instance_id, preserve_boot_volume=preserve_boot_volume)
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "终止实例")
    return {
        "instance_id": instance_id,
        "terminated": True,
        "preserve_boot_volume": preserve_boot_volume,
    }


def change_shape(
    tenant: models.Tenant,
    instance_id: str,
    shape: str,
    ocpus: float | None = None,
    memory_in_gbs: float | None = None,
) -> dict:
    """更改实例 Shape：实例必须处于关机(STOPPED)状态；Flex 机型需带 OCPU/内存配置。"""
    compute, _ = _compute_network(tenant)
    try:
        inst = compute.get_instance(instance_id).data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "查询实例状态")
    state = (inst.lifecycle_state or "").upper()
    if state != "STOPPED":
        raise OciApiError(3103, f"更改 Shape 失败：实例当前状态为 {state}，请先关机后再更改 Shape", 400)
    kwargs: dict = {"shape": shape}
    if ocpus is not None and memory_in_gbs is not None:
        kwargs["shape_config"] = oci.core.models.UpdateInstanceShapeConfigDetails(
            ocpus=ocpus, memory_in_gbs=memory_in_gbs
        )
    details = oci.core.models.UpdateInstanceDetails(**kwargs)
    try:
        updated = compute.update_instance(instance_id, details).data
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "更改实例 Shape")
    return {"instance_id": instance_id, "shape": updated.shape, "accepted": True}
def list_instances(tenant: models.Tenant) -> list[dict]:
    """返回该租户下所有 compartment 的实例，按创建时间倒序。"""
    try:
        compute = get_compute_client(tenant)
        network = get_network_client(tenant)
        identity = get_identity_client(tenant)
    except ValueError as exc:  # 私钥解密失败等配置问题
        raise OciApiError(3101, f"租户配置异常：{exc}", 502)

    # 1. 取租户下全部可用 compartment（含子级）+ 根 compartment 本体
    try:
        compartments = _paginate(
            identity.list_compartments,
            compartment_id=tenant.tenancy_ocid,
            compartment_id_in_subtree=True,
            access_level="ANY",
            lifecycle_state="ACTIVE",
            limit=100,
        )
    except (ConnectTimeout, RequestException) as exc:
        raise OciApiError(3104, f"连接 OCI 超时，请检查网络或代理配置：{exc}", 504)
    except ServiceError as exc:
        raise _translate(exc, "获取 compartment 列表")
    comp_ids = [tenant.tenancy_ocid] + [c.id for c in compartments]
    comp_names = {tenant.tenancy_ocid: "root"}
    comp_names.update({c.id: c.name for c in compartments})

    # 2. 逐 compartment 拉实例，并批量补全主 VNIC 的 IP
    all_instances: list = []
    vnic_map: dict = {}
    for cid in comp_ids:
        try:
            instances = _paginate(
                compute.list_instances,
                compartment_id=cid,
                limit=100,
                sort_by="TIMECREATED",
                sort_order="DESC",
            )
            attachments = _paginate(compute.list_vnic_attachments, compartment_id=cid, limit=100)
        except (ConnectTimeout, RequestException) as exc:
            raise OciApiError(3104, f"连接 OCI 超时，请检查网络或代理配置：{exc}", 504)
        except ServiceError as exc:
            raise _translate(exc, "查询实例列表")
        all_instances.extend(instances)

        primary: dict = {}
        for att in attachments:
            if att.lifecycle_state == "ATTACHED":
                primary.setdefault(att.instance_id, att.vnic_id)
        for inst_id, vnic_id in primary.items():
            try:
                v = network.get_vnic(vnic_id).data
                vnic_map[inst_id] = {"public_ip": v.public_ip, "private_ip": v.private_ip}
            except ServiceError as exc:
                # 单个 VNIC 失败不影响整体列表，只记日志
                log.warning("获取 VNIC %s 失败: %s", vnic_id, exc.message)

    items = [_to_out(i, tenant, vnic_map, comp_names) for i in all_instances]
    items.sort(key=lambda x: x["time_created"] or "", reverse=True)
    return items
