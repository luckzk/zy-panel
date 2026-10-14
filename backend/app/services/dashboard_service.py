"""总览聚合服务：DB 聚合 + 跨租户实例聚合。

注意：实例聚合是对各租户的 OCI 实时查询，租户多时会较慢；
单个租户查询失败会被隔离（记入 errors），不影响其他租户。
"""
import logging
from collections import Counter
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import models
from . import instance_service

log = logging.getLogger(__name__)


def _count_by_status(db: Session, model, tenant_ids: list[int] | None) -> dict[str, int]:
    q = db.query(model.status, func.count(model.id))
    if tenant_ids is not None:
        q = q.filter(model.tenant_id.in_(tenant_ids))
    return dict(q.group_by(model.status).all())


def get_overview(db: Session, tenant_ids: list[int] | None) -> dict:
    """总览聚合。tenant_ids 为 None 表示全部租户。"""
    # 1. 租户
    tq = db.query(models.Tenant)
    if tenant_ids is not None:
        tq = tq.filter(models.Tenant.id.in_(tenant_ids))
    tenants = tq.all()
    tenant_id_list = [t.id for t in tenants]

    # 2. 抢机任务按状态计数
    snatch_counts = _count_by_status(db, models.SnatchTask, tenant_id_list)
    snatch_total = sum(snatch_counts.values())

    # 3. 今日换 IP 成功数（按 updated_at 落到当天）
    ip_q = db.query(func.count(models.IpTask.id)).filter(
        models.IpTask.status == "success",
        func.date(models.IpTask.updated_at) == date.today().isoformat(),
    )
    if tenant_ids is not None:
        ip_q = ip_q.filter(models.IpTask.tenant_id.in_(tenant_id_list))
    ip_changes_today = ip_q.scalar() or 0

    # 4. DNS 记录数（全局，不按租户）
    dns_records = db.query(func.count(models.DnsRecord.id)).scalar() or 0

    # 5. 跨租户实例聚合（OCI 实时查询，单租户失败隔离，多租户并行）
    total = running = stopped = 0
    by_region: Counter = Counter()
    by_shape: Counter = Counter()
    errors: list[dict] = []

    def _fetch_tenant_instances(tenant):
        try:
            return tenant, instance_service.list_instances(tenant), None
        except Exception as exc:
            log.warning("总览聚合：租户 %s(%s) 实例查询失败：%s", tenant.id, tenant.name, exc)
            return tenant, [], str(exc)[:200]

    if tenants:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(tenants), 8)) as pool:
            results = list(pool.map(_fetch_tenant_instances, tenants))
    else:
        results = []
    for tenant, items, err in results:
        if err:
            errors.append({"tenant_id": tenant.id, "tenant_name": tenant.name, "error": err})
            continue
        for inst in items:
            total += 1
            state = (inst.get("lifecycle_state") or "").upper()
            if state == "RUNNING":
                running += 1
            elif state == "STOPPED":
                stopped += 1
            by_region[inst.get("region") or tenant.region or "未知"] += 1
            by_shape[inst.get("shape") or "未知"] += 1

    return {
        "tenants": len(tenants),
        "instances": {
            "total": total,
            "running": running,
            "stopped": stopped,
            "by_region": [{"name": k, "value": v} for k, v in by_region.most_common()],
            "by_shape": [{"name": k, "value": v} for k, v in by_shape.most_common()],
        },
        "snatch": {
            "running": snatch_counts.get("running", 0),
            "success": snatch_counts.get("success", 0),
            "failed": snatch_counts.get("failed", 0),
            "total": snatch_total,
        },
        "ip_changes_today": ip_changes_today,
        "dns_records": dns_records,
        "errors": errors,
    }
