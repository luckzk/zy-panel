"""安全组路由：VCN 列表、安全列表规则查询/新增/删除（真实 OCI 调用）。

说明：network.py 中的 /network/security-rules 桩由父 agent 统一合入替换，
本路由提供完整的安全组能力，前端直接使用此处接口。
"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import security_service
from ..services.security_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["安全组"])


class SecurityRuleIn(BaseModel):
    security_list_id: str
    direction: str = "ingress"  # ingress | egress
    protocol: str = "TCP"  # TCP | UDP | ICMP | 全部
    port_range: str = "all"  # 如 80、8000-9000、all
    cidr: str = "0.0.0.0/0"
    description: str = ""


def _tenant_or_404(db: Session, tenant_id: int):
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()


@router.get("/vcns", summary="VCN 列表（真实 OCI 查询）")
def list_vcns(
    tenant_id: int = Query(description="租户 ID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        items = security_service.list_vcns(tenant, compartment_id or tenant.tenancy_ocid)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("查询 VCN 未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询 VCN 失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items)})


@router.get("/rules", summary="安全列表规则（真实 OCI 查询）")
def list_rules(
    tenant_id: int = Query(description="租户 ID（必填）"),
    vcn_id: str = Query(description="VCN OCID（必填）"),
    compartment_id: str | None = Query(default=None, description="Compartment OCID（默认租户根 compartment）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
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


@router.post("/rules", summary="新增安全规则（真实 OCI 调用）")
def add_rule(
    body: SecurityRuleIn,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if body.direction not in ("ingress", "egress"):
        return err(3103, "direction 只能是 ingress 或 egress", status=400)
    try:
        return ok(
            security_service.add_security_rule(
                tenant,
                body.security_list_id,
                body.direction,
                body.protocol,
                body.port_range,
                body.cidr,
                body.description,
            )
        )
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("新增安全规则未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"新增安全规则失败：{str(exc)[:200]}", status=500)


@router.delete("/rules/{rule_id}", summary="删除安全规则（真实 OCI 调用）")
def delete_rule(
    rule_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        return ok(security_service.delete_security_rule(tenant, rule_id))
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("删除安全规则未知异常 rule_id=%s", rule_id)
        return err(3100, f"删除安全规则失败：{str(exc)[:200]}", status=500)


@router.post("/open-all-ports", summary="一键放行所有端口（真实 OCI 调用，危险操作）")
def open_all_ports(
    tenant_id: int = Query(description="租户 ID（必填）"),
    security_list_id: str = Query(description="安全列表 OCID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """向安全列表追加 0.0.0.0/0 与 ::/0 的全协议入站规则（幂等）。"""
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    try:
        result = security_service.open_all_ports(tenant, security_list_id)
        try:
            from ..core.audit import write_log

            write_log(db, _user.id, "放行所有端口", f"安全列表 {security_list_id} 新增 {result.get('added')}")
        except Exception:
            pass
        return ok(result)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("放行所有端口未知异常 tenant_id=%s", tenant_id)
        return err(3100, f"放行所有端口失败：{str(exc)[:200]}", status=500)
