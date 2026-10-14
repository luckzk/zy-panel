"""IPv6 服务：为实例 VNIC 附加公网 IPv6（真实 OCI 调用）。

流程（对齐 Y 探长实现）：
1. VCN 无 IPv6 CIDR -> add_ipv6_vcn_cidr（Oracle GUA 分配）
2. VCN 下各子网无 ipv6_cidr_block -> update_subnet（VCN /56 取 /64）
3. 确保 Internet 网关存在；默认路由表补 ::/0 -> IGW
4. 默认安全列表放行 ::/0（出入站 all）
5. create_ipv6(vnic_id) 附加公网 IPv6
"""
import logging
import time

import oci
from oci.exceptions import ServiceError

from ..db import models
from .instance_service import OciApiError, _paginate
from . import oci_factory

log = logging.getLogger(__name__)


def _translate(exc: ServiceError, op: str) -> OciApiError:
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {str(exc.message)[:200]}", 502)


def _clients(tenant: models.Tenant):
    try:
        network = oci_factory.get_network_client(tenant)
        compute = oci_factory.get_compute_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502)
    return network, compute


def _wait_available(get_fn, name: str, timeout: int = 120):
    """等待资源变为可用（简单轮询）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = get_fn()
        if state in ("AVAILABLE", "ACTIVE", "ATTACHED", "ASSIGNED"):
            return
        time.sleep(3)
    raise OciApiError(3104, f"{name} 长时间未就绪，请稍后在控制台确认", 504)


def list_instance_ipv6s(tenant: models.Tenant, instance_id: str) -> list[dict]:
    """列出实例主 VNIC 上的 IPv6 地址。"""
    from . import monitoring_service

    network, _ = _clients(tenant)
    vnic_id = monitoring_service.get_primary_vnic_id(tenant, instance_id)
    try:
        items = _paginate(network.list_ipv6s, vnic_id=vnic_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 IPv6")
    return [
        {
            "id": v.id,
            "ip_address": v.ip_address,
            "lifecycle_state": getattr(v, "lifecycle_state", None),
        }
        for v in items
    ]


def attach_ipv6(tenant: models.Tenant, instance_id: str) -> dict:
    """为实例主 VNIC 附加公网 IPv6，返回 {ip_address, vnic_id}。"""
    from . import monitoring_service

    network, compute = _clients(tenant)
    vnic_id = monitoring_service.get_primary_vnic_id(tenant, instance_id)
    try:
        vnic = network.get_vnic(vnic_id).data
        subnet = network.get_subnet(vnic.subnet_id).data
        vcn = network.get_vcn(subnet.vcn_id).data
    except ServiceError as exc:
        raise _translate(exc, "查询 VNIC/子网/VCN")

    vcn_id = vcn.id
    compartment_id = vcn.compartment_id

    # 1. VCN 加 IPv6 CIDR（Oracle GUA）
    ipv6_blocks = list(getattr(vcn, "ipv6_cidr_blocks", None) or [])
    if not ipv6_blocks:
        try:
            network.add_ipv6_vcn_cidr(
                vcn_id,
                oci.core.models.AddVcnIpv6CidrDetails(is_oracle_gua_allocation_enabled=True),
            )
        except ServiceError as exc:
            raise _translate(exc, "为 VCN 添加 IPv6 CIDR")
        _wait_available(
            lambda: network.get_vcn(vcn_id).data.lifecycle_state, "VCN IPv6 CIDR"
        )
        vcn = network.get_vcn(vcn_id).data
        ipv6_blocks = list(getattr(vcn, "ipv6_cidr_blocks", None) or [])
    if not ipv6_blocks:
        raise OciApiError(3103, "VCN 未能分配 IPv6 CIDR", 502)
    v6_64 = ipv6_blocks[0].replace("/56", "/64")

    # 2. 子网补 IPv6 CIDR
    try:
        subnets = _paginate(network.list_subnets, compartment_id=compartment_id, vcn_id=vcn_id)
    except ServiceError as exc:
        raise _translate(exc, "查询子网")
    for sn in subnets:
        if getattr(sn, "ipv6_cidr_block", None):
            continue
        try:
            network.update_subnet(
                sn.id,
                oci.core.models.UpdateSubnetDetails(ipv6_cidr_block=v6_64),
            )
        except ServiceError as exc:
            # 已有 ULA 前缀等情况可忽略
            if "ULA" not in str(exc.message or ""):
                log.warning("子网 %s 添加 IPv6 前缀失败: %s", sn.id, exc.message)

    # 3. 确保 Internet 网关 + 路由表 ::/0 -> IGW
    try:
        igws = _paginate(network.list_internet_gateways, compartment_id=compartment_id, vcn_id=vcn_id)
    except ServiceError as exc:
        raise _translate(exc, "查询 Internet 网关")
    igw = next((g for g in igws if getattr(g, "lifecycle_state", "") == "AVAILABLE"), None)
    if igw is None:
        try:
            igw = network.create_internet_gateway(
                oci.core.models.CreateInternetGatewayDetails(
                    compartment_id=compartment_id, vcn_id=vcn_id, display_name="igw-ipv6", is_enabled=True
                )
            ).data
            _wait_available(
                lambda: network.get_internet_gateway(igw.id).data.lifecycle_state, "Internet 网关"
            )
        except ServiceError as exc:
            raise _translate(exc, "创建 Internet 网关")
    rt_id = vcn.default_route_table_id
    try:
        rt = network.get_route_table(rt_id).data
        rules = list(rt.route_rules or [])
        if not any(getattr(r, "destination", "") == "::/0" for r in rules):
            rules.append(
                oci.core.models.RouteRule(
                    destination="::/0",
                    destination_type="CIDR_BLOCK",
                    network_entity_id=igw.id,
                )
            )
            network.update_route_table(
                rt_id, oci.core.models.UpdateRouteTableDetails(route_rules=rules)
            )
    except ServiceError as exc:
        raise _translate(exc, "更新路由表")

    # 4. 默认安全列表放行 ::/0（幂等：已存在则跳过）
    sl_id = vcn.default_security_list_id
    try:
        sl = network.get_security_list(sl_id).data
        ingress = list(sl.ingress_security_rules or [])
        egress = list(sl.egress_security_rules or [])
        if not any(getattr(r, "source", "") == "::/0" for r in ingress):
            ingress.append(
                oci.core.models.IngressSecurityRule(
                    source="::/0", source_type="CIDR_BLOCK", protocol="all"
                )
            )
        if not any(getattr(r, "destination", "") == "::/0" for r in egress):
            egress.append(
                oci.core.models.EgressSecurityRule(
                    destination="::/0", destination_type="CIDR_BLOCK", protocol="all"
                )
            )
        network.update_security_list(
            sl_id,
            oci.core.models.UpdateSecurityListDetails(
                ingress_security_rules=ingress, egress_security_rules=egress
            ),
        )
    except ServiceError as exc:
        log.warning("更新安全列表失败（可手动放行）: %s", exc.message)

    # 5. 附加 IPv6
    try:
        ipv6 = network.create_ipv6(
            oci.core.models.CreateIpv6Details(vnic_id=vnic_id)
        ).data
    except ServiceError as exc:
        raise _translate(exc, "附加 IPv6")
    return {"ip_address": ipv6.ip_address, "vnic_id": vnic_id, "id": ipv6.id}
