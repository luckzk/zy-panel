"""一键巡检服务：遍历租户实例，检查状态异常并汇总报告。

检查项：
- 实例处于 STOPPED / STOPPING -> warning
- RUNNING 但无公网 IP -> info
单个租户失败不中断整体巡检，记入 errors。
"""
import logging

from ..db import models
from . import instance_service

log = logging.getLogger(__name__)

LEVEL_ORDER = {"error": 0, "warning": 1, "info": 2}

_STOPPED_STATES = {"STOPPED", "STOPPING"}


def inspect_tenant(tenant: models.Tenant) -> dict:
    """巡检单个租户，返回该租户的统计与问题列表。"""
    items = instance_service.list_instances(tenant)

    running = stopped = 0
    issues: list[dict] = []
    for inst in items:
        state = (inst.get("lifecycle_state") or "").upper()
        name = inst.get("display_name") or inst.get("id", "")
        if state == "RUNNING":
            running += 1
            if not inst.get("public_ip"):
                issues.append(_issue(tenant, name, "info", f"实例 {name} 运行中但无公网 IP"))
        elif state in _STOPPED_STATES:
            stopped += 1
            issues.append(_issue(tenant, name, "warning", f"实例 {name} 处于停止状态"))
        # 其他状态（PROVISIONING/TERMINATED 等）只计入 other，不告警

    return {
        "tenant_id": tenant.id,
        "tenant_name": tenant.name,
        "region": tenant.region,
        "total": len(items),
        "running": running,
        "stopped": stopped,
        "other": len(items) - running - stopped,
        "issues": issues,
    }


def _issue(tenant: models.Tenant, instance: str, level: str, message: str) -> dict:
    return {
        "tenant": tenant.name,
        "tenant_id": tenant.id,
        "instance": instance,
        "level": level,
        "message": message,
    }


def inspect_all(db, tenant_ids: list[int] | None = None) -> dict:
    """巡检全部（或指定）租户，汇总报告。单个租户失败记入 errors，不中断。"""
    query = db.query(models.Tenant).order_by(models.Tenant.id)
    if tenant_ids:
        query = query.filter(models.Tenant.id.in_(tenant_ids))
    tenants = query.all()

    per_tenant: list[dict] = []
    issues: list[dict] = []
    errors: list[dict] = []
    instances_total = running = stopped = 0

    for tenant in tenants:
        try:
            result = inspect_tenant(tenant)
        except Exception as exc:
            log.warning("巡检租户 %s(%s) 失败：%s", tenant.id, tenant.name, exc)
            errors.append({"tenant": tenant.name, "tenant_id": tenant.id, "message": str(exc)[:300]})
            continue
        per_tenant.append(result)
        issues.extend(result["issues"])
        instances_total += result["total"]
        running += result["running"]
        stopped += result["stopped"]

    issues.sort(key=lambda i: (LEVEL_ORDER.get(i["level"], 9), i["tenant"], i["instance"]))

    return {
        "tenants_total": len(tenants),
        "tenants_checked": len(per_tenant),
        "instances_total": instances_total,
        "running": running,
        "stopped": stopped,
        "issues": issues,
        "errors": errors,
        "per_tenant": per_tenant,
    }
