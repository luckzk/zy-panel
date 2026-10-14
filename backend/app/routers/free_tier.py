"""免费额度（Always Free）使用情况。"""
import logging
import threading

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import free_tier_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/free-tier", tags=["免费额度"])

# 简单的内存缓存：同一租户 10 分钟内复用结果（全量查询较慢）
_CACHE: dict[int, dict] = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 600


@router.get("/summary", summary="免费额度使用情况汇总（只读）")
def get_summary(
    tenant_id: int = Query(description="租户 ID（必填）"),
    refresh: bool = Query(default=False, description="强制刷新缓存"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    import time

    now = time.time()
    with _CACHE_LOCK:
        cached = _CACHE.get(tenant_id)
    if cached and not refresh and now - cached["ts"] < _CACHE_TTL:
        data = dict(cached["data"])
        data["cached"] = True
        return ok(data)
    try:
        data = free_tier_service.get_free_tier_summary(tenant)
    except Exception as exc:
        log.exception("免费额度汇总异常 tenant_id=%s", tenant_id)
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)
    with _CACHE_LOCK:
        _CACHE[tenant_id] = {"ts": now, "data": data}
    data["cached"] = False
    return ok(data)
