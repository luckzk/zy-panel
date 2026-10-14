"""一键 500M 服务：为免费 AMD 实例开启/关闭下行 500Mbps（真实 OCI 调用）。

原理：
- 开启：创建 NAT 网关 + NAT 路由表（0.0.0.0/0 -> NAT），删除旧 NLB 后创建公网
  Network Load Balancer（TCP_AND_UDP 全端口监听，后端指向实例私网 IP，
  健康检查走 SSH 端口），VNIC 绑定 NAT 路由表并跳过源/目检查，放行安全组。
  流量经 NLB（约 500Mbps 带宽）进实例，绕开免费 AMD 实例自身带宽上限。
- 关闭：删除 NLB（可选保留）、清空/删除 NAT 路由表（可选保留 NAT 网关），
  VNIC 绑回普通路由表。

任务为后台线程执行，通过内存任务表轮询状态。"""
import logging
import threading
import time
import uuid

import oci
from oci.exceptions import ServiceError

from ..db import models
from ..db.session import SessionLocal
from . import oci_factory
from .instance_service import OciApiError, _paginate

log = logging.getLogger(__name__)

_TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _set_task(task_id: str, **fields):
    with _LOCK:
        _TASKS[task_id].update(fields)


def list_tasks() -> list[dict]:
    with _LOCK:
        return sorted(_TASKS.values(), key=lambda t: t["created_at"], reverse=True)[:50]


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        return _TASKS.get(task_id)


def _translate(exc: ServiceError, op: str) -> OciApiError:
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {str(exc.message)[:200]}", 502)


def _wait(get_state, name: str, timeout: int = 300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if get_state() in ("AVAILABLE", "ACTIVE", "ATTACHED"):
            return
        time.sleep(5)
    raise OciApiError(3104, f"{name} 长时间未就绪", 504)


def _notify(title: str, body: str):
    try:
        from . import notification_service

        notification_service.send_to_all(title, body)
    except Exception as exc:
        log.warning("500M 任务通知发送失败: %s", exc)


def _audit(tenant_id: int, action: str, detail: str):
    try:
        from ..core.audit import write_log

        db = SessionLocal()
        try:
            write_log(db, None, action, detail)
        finally:
            db.close()
    except Exception as exc:
        log.warning("500M 任务审计写入失败: %s", exc)


def _load_tenant(tenant_id: int) -> models.Tenant:
    db = SessionLocal()
    try:
        tenant = db.get(models.Tenant, tenant_id)
        if tenant is None:
            raise OciApiError(3103, "租户不存在", 404)
        db.expunge(tenant)
        return tenant
    finally:
        db.close()


def _nlb_client(tenant: models.Tenant):
    try:
        return oci_factory.get_network_load_balancer_client(tenant)
    except ValueError as exc:
        raise OciApiError(3101, f"租户配置异常：{exc}", 502)
    except AttributeError:
        raise OciApiError(3103, "当前 OCI SDK 不支持 Network Load Balancer", 502)


def _enable_worker(task_id: str, tenant_id: int, instance_id: str, ssh_port: int):
    tenant = _load_tenant(tenant_id)
    try:
        network = oci_factory.get_network_client(tenant)
        compute = oci_factory.get_compute_client(tenant)
        nlb_client = _nlb_client(tenant)

        inst = compute.get_instance(instance_id).data
        shape = inst.shape or ""
        if "AMD" not in shape.upper() and "E2" not in shape and "E3" not in shape and "E4" not in shape:
            raise OciApiError(3103, f"该实例 Shape（{shape}）不支持一键 500M，仅支持 AMD 机型", 400)
        compartment_id = inst.compartment_id
        name = inst.display_name

        # VNIC / 私网 IP / VCN
        atts = _paginate(compute.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance_id, limit=10)
        primary = next((a for a in atts if getattr(a, "lifecycle_state", "") == "ATTACHED"), None) or (atts[0] if atts else None)
        if primary is None:
            raise OciApiError(3103, "实例没有 VNIC", 502)
        vnic = network.get_vnic(primary.vnic_id).data
        priv_ips = network.list_private_ips(vnic_id=vnic.id).data
        private_ip = priv_ips[0].ip_address if priv_ips else vnic.private_ip
        vcn = network.get_vcn(network.get_subnet(vnic.subnet_id).data.vcn_id).data
        subnet_id = vnic.subnet_id

        # NAT 网关（复用或创建）
        nat_gws = _paginate(
            network.list_nat_gateways, compartment_id=compartment_id, vcn_id=vcn.id
        )
        nat_gw = next((g for g in nat_gws if getattr(g, "lifecycle_state", "") == "AVAILABLE"), None)
        if nat_gw is None:
            nat_gw = network.create_nat_gateway(
                oci.core.models.CreateNatGatewayDetails(
                    compartment_id=compartment_id, vcn_id=vcn.id, display_name="nat-gateway"
                )
            ).data
            _wait(lambda: network.get_nat_gateway(nat_gw.id).data.lifecycle_state, "NAT 网关")

        # 查找已有的 NAT 路由表（0.0.0.0/0 -> 该 NAT 网关）
        route_tables = _paginate(
            network.list_route_tables, compartment_id=compartment_id, vcn_id=vcn.id
        )
        nat_rt = None
        for rt in route_tables:
            for rule in getattr(rt, "route_rules", None) or []:
                if (
                    getattr(rule, "network_entity_id", "") == nat_gw.id
                    and getattr(rule, "destination", "") == "0.0.0.0/0"
                ):
                    nat_rt = rt
                    break
            if nat_rt:
                break
        # 同一租户已有其他 AMD 实例绑定 NAT 路由表则拒绝（避免互相影响）
        if nat_rt is not None:
            instances = _paginate(compute.list_instances, compartment_id=compartment_id)
            for other in instances:
                if other.id == instance_id:
                    continue
                osh = (other.shape or "").upper()
                if "AMD" not in osh and "E2" not in osh and "E3" not in osh and "E4" not in osh:
                    continue
                try:
                    oatts = _paginate(compute.list_vnic_attachments, compartment_id=other.compartment_id, instance_id=other.id, limit=5)
                    op = next((a for a in oatts if getattr(a, "lifecycle_state", "") == "ATTACHED"), None)
                    if op is None:
                        continue
                    ov = network.get_vnic(op.vnic_id).data
                    if getattr(ov, "route_table_id", None) == nat_rt.id:
                        raise OciApiError(3103, f"已有其他 AMD 实例（{other.display_name}）绑定 NAT 路由表", 400)
                except OciApiError:
                    raise
                except Exception:
                    continue

        # 删除已有 NLB
        try:
            nlbs = nlb_client.list_network_load_balancers(compartment_id=compartment_id).data.items or []
        except ServiceError as exc:
            raise _translate(exc, "查询网络负载均衡器")
        for n in nlbs:
            try:
                nlb_client.delete_network_load_balancer(n.id)
            except Exception as exc:
                log.warning("删除旧 NLB %s 失败: %s", n.id, exc)

        # 创建公网 NLB（TCP_AND_UDP 全端口，后端指向实例私网 IP）
        import datetime as _dt

        nlb_name = "nlb-" + _dt.datetime.now().strftime("%Y%m%d%H%M%S")
        nlb = None
        for attempt in range(10):
            try:
                nlb = nlb_client.create_network_load_balancer(
                    oci.network_load_balancer.models.CreateNetworkLoadBalancerDetails(
                        display_name=nlb_name,
                        compartment_id=compartment_id,
                        is_private=False,
                        subnet_id=subnet_id,
                        listeners={
                            "listener1": oci.network_load_balancer.models.ListenerDetails(
                                name="listener1",
                                default_backend_set_name="backend1",
                                protocol="TCP_AND_UDP",
                                port=0,
                            )
                        },
                        backend_sets={
                            "backend1": oci.network_load_balancer.models.BackendSetDetails(
                                policy="TWO_TUPLE",
                                is_preserve_source=True,
                                is_fail_open=True,
                                health_checker=oci.network_load_balancer.models.HealthChecker(
                                    protocol="TCP", port=ssh_port
                                ),
                                backends=[
                                    oci.network_load_balancer.models.Backend(
                                        target_id=instance_id,
                                        ip_address=private_ip,
                                        port=0,
                                        weight=1,
                                    )
                                ],
                            )
                        },
                    )
                ).data
                break
            except ServiceError as exc:
                log.warning("创建 NLB 第 %d 次失败: %s", attempt + 1, exc.message)
                time.sleep(30)
        if nlb is None:
            raise OciApiError(3103, "创建网络负载均衡器重试 10 次均失败", 502)
        _wait(
            lambda: nlb_client.get_network_load_balancer(nlb.id).data.lifecycle_state,
            "网络负载均衡器",
        )
        nlb_full = nlb_client.get_network_load_balancer(nlb.id).data
        public_ip = None
        for ip in getattr(nlb_full, "ip_addresses", None) or []:
            addr = getattr(ip, "ip_address", "")
            if addr and not addr.startswith(("10.", "192.168.", "172.")):
                public_ip = addr
                break

        # 创建/复用 NAT 路由表
        if nat_rt is None:
            nat_rt = network.create_route_table(
                oci.core.models.CreateRouteTableDetails(
                    compartment_id=compartment_id,
                    vcn_id=vcn.id,
                    display_name="nat-route",
                    route_rules=[
                        oci.core.models.RouteRule(
                            destination="0.0.0.0/0",
                            destination_type="CIDR_BLOCK",
                            network_entity_id=nat_gw.id,
                        )
                    ],
                )
            ).data
            _wait(lambda: network.get_route_table(nat_rt.id).data.lifecycle_state, "NAT 路由表")

        # VNIC 绑定 NAT 路由表 + 跳过源/目检查
        network.update_vnic(
            vnic.id,
            oci.core.models.UpdateVnicDetails(skip_source_dest_check=True, route_table_id=nat_rt.id),
        )

        # 安全组放行全端口（内网段 + IPv6）
        try:
            sl = network.get_security_list(vcn.default_security_list_id).data
            ingress = list(sl.ingress_security_rules or [])
            egress = list(sl.egress_security_rules or [])
            for cidr in ("10.0.0.0/16", "::/0"):
                if not any(getattr(r, "source", "") == cidr for r in ingress):
                    ingress.append(
                        oci.core.models.IngressSecurityRule(
                            source=cidr, source_type="CIDR_BLOCK", protocol="all"
                        )
                    )
                if not any(getattr(r, "destination", "") == cidr for r in egress):
                    egress.append(
                        oci.core.models.EgressSecurityRule(
                            destination=cidr, destination_type="CIDR_BLOCK", protocol="all"
                        )
                    )
            network.update_security_list(
                vcn.default_security_list_id,
                oci.core.models.UpdateSecurityListDetails(
                    ingress_security_rules=ingress, egress_security_rules=egress
                ),
            )
        except Exception as exc:
            log.warning("放行安全组失败（可手动处理）: %s", exc)

        msg = f"实例 {name} 已开启下行 500M，NLB 公网 IP：{public_ip}"
        _set_task(task_id, status="success", message=msg, public_ip=public_ip)
        _audit(tenant_id, "boost.enable_500m", msg)
        _notify("一键 500M 开启成功", msg)
    except OciApiError as exc:
        _set_task(task_id, status="failed", message=exc.message)
        _audit(tenant_id, "boost.enable_500m", f"实例 {instance_id} 开启 500M 失败：{exc.message}")
        _notify("一键 500M 开启失败", exc.message)
    except Exception as exc:
        log.exception("500M 开启任务未知异常")
        _set_task(task_id, status="failed", message=f"未知异常：{str(exc)[:200]}")


def _disable_worker(task_id: str, tenant_id: int, instance_id: str, retain_nat_gw: bool, retain_nlb: bool):
    tenant = _load_tenant(tenant_id)
    try:
        network = oci_factory.get_network_client(tenant)
        compute = oci_factory.get_compute_client(tenant)
        nlb_client = _nlb_client(tenant)

        inst = compute.get_instance(instance_id).data
        compartment_id = inst.compartment_id
        name = inst.display_name
        atts = _paginate(compute.list_vnic_attachments, compartment_id=compartment_id, instance_id=instance_id, limit=10)
        primary = next((a for a in atts if getattr(a, "lifecycle_state", "") == "ATTACHED"), None) or (atts[0] if atts else None)
        vnic = network.get_vnic(primary.vnic_id).data
        vcn = network.get_vcn(network.get_subnet(vnic.subnet_id).data.vcn_id).data

        route_tables = _paginate(
            network.list_route_tables, compartment_id=compartment_id, vcn_id=vcn.id
        )
        nat_gws = _paginate(network.list_nat_gateways, compartment_id=compartment_id, vcn_id=vcn.id)
        nat_rt_ids: set[str] = set()
        # 清空 NAT 路由表规则 / 删除 NAT 网关
        for gw in nat_gws:
            if getattr(gw, "lifecycle_state", "") != "AVAILABLE":
                continue
            for rt in route_tables:
                rules = getattr(rt, "route_rules", None) or []
                if any(
                    getattr(r, "network_entity_id", "") == gw.id
                    and getattr(r, "destination", "") == "0.0.0.0/0"
                    for r in rules
                ):
                    nat_rt_ids.add(rt.id)
                    if not retain_nat_gw:
                        network.update_route_table(
                            rt.id, oci.core.models.UpdateRouteTableDetails(route_rules=[])
                        )
            if not retain_nat_gw:
                try:
                    network.delete_nat_gateway(gw.id)
                except Exception as exc:
                    log.warning("删除 NAT 网关 %s 失败: %s", gw.id, exc)

        # VNIC 绑回普通路由表（第一个非 NAT 路由表）
        fallback_rt = next((rt for rt in route_tables if rt.id not in nat_rt_ids), None)
        if fallback_rt is not None:
            network.update_vnic(
                vnic.id,
                oci.core.models.UpdateVnicDetails(
                    skip_source_dest_check=True, route_table_id=fallback_rt.id
                ),
            )
        # 删除 NAT 路由表
        for rt_id in nat_rt_ids:
            try:
                network.delete_route_table(rt_id)
            except Exception as exc:
                log.warning("删除 NAT 路由表 %s 失败: %s", rt_id, exc)

        # 删除 NLB
        if not retain_nlb:
            try:
                nlbs = nlb_client.list_network_load_balancers(compartment_id=compartment_id).data.items or []
            except ServiceError as exc:
                raise _translate(exc, "查询网络负载均衡器")
            for n in nlbs:
                try:
                    nlb_client.delete_network_load_balancer(n.id)
                except Exception as exc:
                    log.warning("删除 NLB %s 失败: %s", n.id, exc)

        msg = f"实例 {name} 已关闭下行 500M"
        _set_task(task_id, status="success", message=msg)
        _audit(tenant_id, "boost.disable_500m", msg)
        _notify("一键 500M 关闭成功", msg)
    except OciApiError as exc:
        _set_task(task_id, status="failed", message=exc.message)
        _notify("一键 500M 关闭失败", exc.message)
    except Exception as exc:
        log.exception("500M 关闭任务未知异常")
        _set_task(task_id, status="failed", message=f"未知异常：{str(exc)[:200]}")


def start_enable(tenant_id: int, instance_id: str, ssh_port: int = 22) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _TASKS[task_id] = {
            "id": task_id, "action": "enable", "tenant_id": tenant_id,
            "instance_id": instance_id, "status": "running", "message": "任务执行中…",
            "public_ip": None, "created_at": time.time(),
        }
    threading.Thread(
        target=_enable_worker, args=(task_id, tenant_id, instance_id, ssh_port), daemon=True
    ).start()
    return task_id


def start_disable(tenant_id: int, instance_id: str, retain_nat_gw: bool, retain_nlb: bool) -> str:
    task_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _TASKS[task_id] = {
            "id": task_id, "action": "disable", "tenant_id": tenant_id,
            "instance_id": instance_id, "status": "running", "message": "任务执行中…",
            "public_ip": None, "created_at": time.time(),
        }
    threading.Thread(
        target=_disable_worker, args=(task_id, tenant_id, instance_id, retain_nat_gw, retain_nlb), daemon=True
    ).start()
    return task_id
