"""安全组（安全列表）服务：真实 OCI Virtual Network 调用。"""
import logging

import oci
from oci.exceptions import ConnectTimeout, ServiceError

from . import oci_factory

log = logging.getLogger(__name__)

PROTOCOL_NAMES = {"1": "ICMP", "6": "TCP", "17": "UDP", "all": "全部"}
PROTOCOL_NUMBERS = {"TCP": "6", "UDP": "17", "ICMP": "1", "全部": "all", "ALL": "all"}


class OciApiError(Exception):
    """可直接映射为接口错误码的 OCI 调用异常。"""

    def __init__(self, code: int, message: str, http_status: int = 502):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _translate(exc: ServiceError, op: str) -> OciApiError:
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {exc.message}", 502)


def _paginate(list_fn, **kwargs) -> list:
    items: list = []
    page = None
    while True:
        resp = list_fn(page=page, **kwargs) if page else list_fn(**kwargs)
        items.extend(resp.data)
        page = resp.headers.get("opc-next-page")
        if not page:
            break
    return items


def _client(tenant):
    try:
        return oci_factory.get_network_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502) from exc


def _port_range(rule) -> str:
    """提取规则的端口范围：'80' / '8000-9000' / 'all'。"""
    for attr, opts_cls in (("tcp_options", None), ("udp_options", None)):
        opts = getattr(rule, attr, None)
        pr = getattr(opts, "destination_port_range", None) if opts else None
        if pr and pr.min is not None:
            return str(pr.min) if pr.min == pr.max else f"{pr.min}-{pr.max}"
    icmp = getattr(rule, "icmp_options", None)
    if icmp is not None and (icmp.type is not None or icmp.code is not None):
        return f"type {icmp.type}/code {icmp.code}"
    return "all"


def _flatten(sl_id: str, sl_name: str, direction: str, rules) -> list[dict]:
    out = []
    for idx, r in enumerate(rules or []):
        proto = str(getattr(r, "protocol", "all"))
        endpoint = getattr(r, "source", None) if direction == "ingress" else getattr(r, "destination", None)
        out.append(
            {
                "id": f"{sl_id}__{direction}__{idx}",
                "security_list_id": sl_id,
                "security_list_name": sl_name,
                "direction": direction,
                "protocol": PROTOCOL_NAMES.get(proto, proto),
                "port_range": _port_range(r),
                "source": endpoint or "-",
                "description": getattr(r, "description", "") or "",
                "stateless": bool(getattr(r, "is_stateless", False)),
            }
        )
    return out


def list_vcns(tenant, compartment_id: str) -> list[dict]:
    """列出 compartment 下的 VCN（供前端选择）。"""
    client = _client(tenant)
    try:
        vcns = _paginate(client.list_vcns, compartment_id=compartment_id)
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询 VCN 失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询 VCN") from exc
    return [
        {"id": v.id, "display_name": v.display_name, "cidr_block": getattr(v, "cidr_block", "")}
        for v in vcns
    ]


def list_security_rules(tenant, compartment_id: str, vcn_id: str) -> list[dict]:
    """列出某 VCN 下全部安全列表的入站/出站规则（打平为前端友好结构）。"""
    client = _client(tenant)
    try:
        slists = _paginate(client.list_security_lists, compartment_id=compartment_id, vcn_id=vcn_id)
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"查询安全列表失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "查询安全列表") from exc

    items: list[dict] = []
    for sl in slists:
        try:
            full = client.get_security_list(sl.id).data
        except ServiceError as exc:
            log.warning("获取安全列表 %s 详情失败：%s", sl.id, exc)
            continue
        items += _flatten(sl.id, sl.display_name, "ingress", full.ingress_security_rules)
        items += _flatten(sl.id, sl.display_name, "egress", full.egress_security_rules)
    return items


def _parse_port_range(port_range: str) -> tuple[int, int]:
    port_range = (port_range or "all").strip().lower()
    if port_range in ("all", ""):
        return (1, 65535)
    if "-" in port_range:
        lo, hi = port_range.split("-", 1)
        return (int(lo), int(hi))
    return (int(port_range), int(port_range))


def add_security_rule(
    tenant,
    security_list_id: str,
    direction: str,
    protocol: str,
    port_range: str,
    cidr: str,
    description: str = "",
) -> dict:
    """向安全列表追加一条规则（OCI 是整列表替换，这里先读后写）。"""
    client = _client(tenant)
    proto_num = PROTOCOL_NUMBERS.get(protocol, protocol)
    lo, hi = _parse_port_range(port_range)
    try:
        sl = client.get_security_list(security_list_id).data
        if direction == "ingress":
            opts = None
            if proto_num == "6":
                opts = {"tcp_options": oci.core.models.TcpOptions(
                    destination_port_range=oci.core.models.PortRange(min=lo, max=hi))}
            elif proto_num == "17":
                opts = {"udp_options": oci.core.models.UdpOptions(
                    destination_port_range=oci.core.models.PortRange(min=lo, max=hi))}
            rule = oci.core.models.IngressSecurityRule(
                protocol=proto_num, source=cidr, description=description, **(opts or {}))
            rules = list(sl.ingress_security_rules or []) + [rule]
            details = oci.core.models.UpdateSecurityListDetails(ingress_security_rules=rules)
        else:
            opts = None
            if proto_num == "6":
                opts = {"tcp_options": oci.core.models.TcpOptions(
                    destination_port_range=oci.core.models.PortRange(min=lo, max=hi))}
            elif proto_num == "17":
                opts = {"udp_options": oci.core.models.UdpOptions(
                    destination_port_range=oci.core.models.PortRange(min=lo, max=hi))}
            rule = oci.core.models.EgressSecurityRule(
                protocol=proto_num, destination=cidr, description=description, **(opts or {}))
            rules = list(sl.egress_security_rules or []) + [rule]
            details = oci.core.models.UpdateSecurityListDetails(egress_security_rules=rules)
        client.update_security_list(security_list_id, details)
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"添加安全规则失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "添加安全规则") from exc
    log.info("安全列表 %s 新增%s规则 %s %s", security_list_id, direction, protocol, port_range)
    return {"security_list_id": security_list_id, "direction": direction, "added": True}


def delete_security_rule(tenant, rule_id: str) -> dict:
    """按 id 删除规则：id 格式 {security_list_id}__{direction}__{index}。"""
    try:
        sl_id, direction, idx = rule_id.rsplit("__", 2)
        idx = int(idx)
    except (ValueError, AttributeError) as exc:
        raise OciApiError(3103, f"删除失败：规则 id 格式不正确（{rule_id}）", 400) from exc
    client = _client(tenant)
    try:
        sl = client.get_security_list(sl_id).data
        if direction == "ingress":
            rules = list(sl.ingress_security_rules or [])
        elif direction == "egress":
            rules = list(sl.egress_security_rules or [])
        else:
            raise OciApiError(3103, f"删除失败：未知方向 {direction}", 400)
        if not 0 <= idx < len(rules):
            raise OciApiError(3103, "删除失败：规则不存在（可能已被外部修改）", 404)
        rules.pop(idx)
        if direction == "ingress":
            details = oci.core.models.UpdateSecurityListDetails(ingress_security_rules=rules)
        else:
            details = oci.core.models.UpdateSecurityListDetails(egress_security_rules=rules)
        client.update_security_list(sl_id, details)
    except OciApiError:
        raise
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"删除安全规则失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "删除安全规则") from exc
    log.info("已删除安全规则 %s", rule_id)
    return {"id": rule_id, "deleted": True}


def open_all_ports(tenant, security_list_id: str) -> dict:
    """一键放行所有端口：向安全列表追加 0.0.0.0/0 与 ::/0 的全协议入站规则。

    幂等：已存在的全放行规则会被跳过。OCI 更新安全列表是整列表替换，这里先读后写。
    """
    client = _client(tenant)
    targets = ["0.0.0.0/0", "::/0"]
    try:
        sl = client.get_security_list(security_list_id).data
        existing = {
            (str(getattr(r, "source", "") or ""), str(getattr(r, "protocol", "") or ""))
            for r in (sl.ingress_security_rules or [])
        }
        rules = list(sl.ingress_security_rules or [])
        added: list[str] = []
        for cidr in targets:
            if (cidr, "all") in existing:
                continue
            rules.append(
                oci.core.models.IngressSecurityRule(
                    protocol="all",
                    source=cidr,
                    description="oci-panel 一键放行所有端口",
                )
            )
            added.append(cidr)
        if added:
            client.update_security_list(
                security_list_id,
                oci.core.models.UpdateSecurityListDetails(ingress_security_rules=rules),
            )
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"放行所有端口失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "放行所有端口") from exc
    log.warning("安全列表 %s 已放行所有端口（%s），该操作会暴露全部入站端口", security_list_id, ",".join(added) or "无新增")
    return {
        "security_list_id": security_list_id,
        "added": added,
        "already_open": [c for c in targets if c not in added],
    }
