"""费用路由：OCI 用量查询（真实 Usage API）+ 汇总。"""
import logging

from fastapi import APIRouter, Depends, Query
from oci.exceptions import ConnectTimeout, RequestException, ServiceError
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import usage_service

router = APIRouter(prefix="/billing", tags=["费用"])
log = logging.getLogger(__name__)


def _translate(exc: ServiceError, op: str):
    """OCI ServiceError -> 友好错误（33xx 段为费用模块）。"""
    status = exc.status or 502
    if status == 401:
        return err(3301, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", status=502)
    if status == 429:
        return err(3302, f"{op}失败：OCI 接口限流，请稍后重试", status=502)
    if status == 404:
        return err(3303, f"{op}失败：资源不存在 ({exc.code})", status=502)
    return err(3302, f"{op}失败：[{exc.code}] {str(exc.message)[:200]}", status=502)


def _get_tenant_or_404(db: Session, tenant_id: int):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return None, err(3004, "租户不存在", status=404)
    return tenant, None


@router.get("/summary", summary="费用汇总（真实 OCI 用量）")
def get_summary(
    tenant_id: int = Query(description="租户 ID（必填）"),
    days: int = Query(default=30, ge=1, le=365, description="回看天数"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant, err_resp = _get_tenant_or_404(db, tenant_id)
    if err_resp:
        return err_resp
    try:
        data = usage_service.monthly_summary(tenant, days=days)
    except (ConnectTimeout, RequestException) as exc:
        return err(3302, f"查询费用失败：连接 OCI 超时（{exc}）", status=502)
    except ServiceError as exc:
        return _translate(exc, "查询费用")
    except Exception as exc:
        log.exception("查询费用未知异常 tenant_id=%s", tenant_id)
        return err(3300, f"查询费用失败：{str(exc)[:200]}", status=500)
    return ok(data)


@router.get("/details", summary="费用明细（真实 OCI 用量）")
def get_details(
    tenant_id: int = Query(description="租户 ID（必填）"),
    days: int = Query(default=30, ge=1, le=365, description="回看天数"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant, err_resp = _get_tenant_or_404(db, tenant_id)
    if err_resp:
        return err_resp
    try:
        items = usage_service.query_usage(tenant, days=days, granularity="DAILY")
    except (ConnectTimeout, RequestException) as exc:
        return err(3302, f"查询费用明细失败：连接 OCI 超时（{exc}）", status=502)
    except ServiceError as exc:
        return _translate(exc, "查询费用明细")
    except Exception as exc:
        log.exception("查询费用明细未知异常 tenant_id=%s", tenant_id)
        return err(3300, f"查询费用明细失败：{str(exc)[:200]}", status=500)
    return ok({"items": items, "total": len(items), "days": days})
