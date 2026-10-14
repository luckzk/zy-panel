"""网络路由：换 IP 任务（真实 worker）、安全列表规则（真实 OCI 查询）。"""
import ipaddress
import json
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import security_service
from ..services.security_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/network", tags=["网络"])


class ChangeIpIn(BaseModel):
    tenant_id: int
    instance_id: str
    preferred_cidrs: list[str] = []  # 偏好的 CIDR 网段，换到为止
    update_dns: bool = False  # 换 IP 后是否自动更新 Cloudflare DNS
    max_retries: int = 3  # CIDR 偏好未命中时的重换次数

    @field_validator("preferred_cidrs")
    @classmethod
    def _validate_cidrs(cls, v: list[str]) -> list[str]:
        for cidr in v:
            try:
                ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                raise ValueError(f"无效的 CIDR 网段：{cidr}")
        return v

    @field_validator("max_retries")
    @classmethod
    def _validate_retries(cls, v: int) -> int:
        if v < 1 or v > 20:
            raise ValueError("max_retries 取值范围 1~20")
        return v


class SecurityRuleIn(BaseModel):
    direction: str = "INGRESS"  # INGRESS / EGRESS
    protocol: str = "6"  # 6=TCP, 17=UDP, 1=ICMP, all
    port: str = "22"
    cidr: str = "0.0.0.0/0"
    description: str = ""


def _ip_task_out(t: models.IpTask) -> dict:
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "instance_id": t.instance_id,
        "preferred_cidrs": json.loads(t.preferred_cidrs or "[]"),
        "update_dns": t.update_dns,
        "status": t.status,
        "old_ip": t.old_ip,
        "new_ip": t.new_ip,
        "attempts": t.attempts,
        "max_retries": t.max_retries,
        "dns_updated": t.dns_updated,
        "next_attempt_at": t.next_attempt_at.isoformat() if t.next_attempt_at else None,
        "last_error": t.last_error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.post("/change-ip", summary="发起换 IP 任务（后台 worker 真实执行）")
def change_ip(
    body: ChangeIpIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if db.get(models.Tenant, body.tenant_id) is None:
        return err(5001, "租户不存在", status=404)
    task = models.IpTask(
        tenant_id=body.tenant_id,
        instance_id=body.instance_id,
        preferred_cidrs=json.dumps(body.preferred_cidrs),
        update_dns=body.update_dns,
        max_retries=body.max_retries,
        status="running",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    write_log(db, user.id, "network.change_ip", f"实例 {body.instance_id} 发起换 IP")
    return ok(_ip_task_out(task))


@router.get("/ip-tasks", summary="换 IP 任务列表")
def list_ip_tasks(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tasks = db.query(models.IpTask).order_by(models.IpTask.id.desc()).all()
    return ok([_ip_task_out(t) for t in tasks])


@router.get("/change-ip-tasks", summary="换 IP 任务列表（与 /ip-tasks 同义）")
def list_change_ip_tasks(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tasks = db.query(models.IpTask).order_by(models.IpTask.id.desc()).all()
    return ok([_ip_task_out(t) for t in tasks])


@router.post("/ip-tasks/{task_id}/cancel", summary="取消换 IP 任务")
def cancel_ip_task(task_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    task = db.get(models.IpTask, task_id)
    if task is None:
        return err(5002, "任务不存在", status=404)
    if task.status not in ("pending", "running"):
        return err(5003, f"任务 {task.status} 不可取消", status=400)
    task.status = "failed"
    task.last_error = "用户手动取消"
    db.commit()
    return ok(_ip_task_out(task))


@router.get("/security-rules", summary="安全列表规则（真实 OCI 查询）")
def list_security_rules(
    tenant_id: int = Query(description="租户 ID（必填）"),
    vcn_id: str = Query(description="VCN OCID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = security_service.list_security_rules(tenant, compartment_id or tenant.tenancy_ocid, vcn_id)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询安全规则未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询安全规则失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})


@router.post("/security-rules", summary="新增安全规则（真实 OCI 调用）")
def add_security_rule(
    body: SecurityRuleIn,
    tenant_id: int = Query(description="租户 ID（必填）"),
    security_list_id: str = Query(description="安全列表 OCID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    direction = body.direction.lower()
    if direction not in ("ingress", "egress"):
        return err(3103, "direction 只能是 INGRESS 或 EGRESS", status=400)
    proto_map = {"6": "TCP", "17": "UDP", "1": "ICMP", "all": "全部"}
    try:
        return ok(
            security_service.add_security_rule(
                tenant,
                security_list_id,
                direction,
                proto_map.get(body.protocol, body.protocol),
                body.port,
                body.cidr,
                body.description,
            )
        )
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("新增安全规则未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"新增安全规则失败：{str(exc)[:200]}", status=500)


@router.delete("/security-rules/{rule_id}", summary="删除安全规则（真实 OCI 调用）")
def delete_security_rule(
    rule_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(security_service.delete_security_rule(tenant, rule_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("删除安全规则未知异常 rule_id=%s", rule_id)
        return err(3100, f"删除安全规则失败：{str(exc)[:200]}", status=500)


class Ipv6In(BaseModel):
    tenant_id: int
    instance_id: str


@router.post("/ipv6", summary="为实例主 VNIC 附加公网 IPv6（真实 OCI 调用）")
def attach_ipv6(
    body: Ipv6In,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    tenant = db.get(models.Tenant, body.tenant_id)
    if tenant is None:
        return err(3103, "租户不存在", status=404)
    try:
        from ..services import ipv6_service

        result = ipv6_service.attach_ipv6(tenant, body.instance_id)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("附加 IPv6 未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, f"附加 IPv6 失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "network.attach_ipv6", f"实例 {body.instance_id} 附加 IPv6 {result['ip_address']}")
    return ok(result)


@router.get("/ipv6", summary="查询实例主 VNIC 的 IPv6 地址")
def list_ipv6(
    tenant_id: int = Query(description="租户 ID"),
    instance_id: str = Query(description="实例 OCID"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(3103, "租户不存在", status=404)
    try:
        from ..services import ipv6_service

        return ok(ipv6_service.list_instance_ipv6s(tenant, instance_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询 IPv6 未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询 IPv6 失败：{str(exc)[:200]}", status=500)


