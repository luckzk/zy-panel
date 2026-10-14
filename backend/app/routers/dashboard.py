"""总览路由：仪表盘真实数据聚合。

注意：实例部分是对各租户的 OCI 实时查询，租户多时响应较慢；
单个租户查询失败会被隔离，在返回的 errors 中说明，不影响整体。
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import dashboard_service

router = APIRouter(prefix="/dashboard", tags=["总览"])
log = logging.getLogger(__name__)


@router.get("/overview", summary="总览聚合（真实数据）")
def get_overview(
    tenant_ids: str | None = Query(default=None, description="逗号分隔的租户 ID，不传=全部租户"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ids: list[int] | None = None
    if tenant_ids:
        try:
            ids = [int(x) for x in tenant_ids.split(",") if x.strip()]
        except ValueError:
            return err(8001, "tenant_ids 格式错误，应为逗号分隔的数字", status=400)
    try:
        return ok(dashboard_service.get_overview(db, ids))
    except Exception as exc:
        log.exception("总览聚合失败")
        return err(8000, f"总览聚合失败：{str(exc)[:200]}", status=500)
