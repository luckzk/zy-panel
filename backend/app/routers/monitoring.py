"""监控路由：实例流量时序（真实 OCI Monitoring）+ 配额查询（真实 Limits API）。"""
import logging

from fastapi import APIRouter, Depends, Query
from oci.exceptions import ConnectTimeout, RequestException, ServiceError
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import instance_service, monitoring_service

router = APIRouter(prefix="/monitoring", tags=["监控"])
log = logging.getLogger(__name__)


def _translate(exc: ServiceError, op: str):
    """OCI ServiceError -> 友好错误（32xx 段为监控模块）。"""
    status = exc.status or 502
    if status == 401:
        return err(3201, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", status=502)
    if status == 429:
        return err(3202, f"{op}失败：OCI 接口限流，请稍后重试", status=502)
    if status == 404:
        return err(3203, f"{op}失败：资源不存在 ({exc.code})", status=502)
    return err(3202, f"{op}失败：[{exc.code}] {str(exc.message)[:200]}", status=502)


@router.get("/traffic", summary="实例流量时序（真实 OCI 指标）")
def get_traffic(
    tenant_id: int = Query(description="租户 ID（必填）"),
    instance_id: str | None = Query(default=None, description="实例 OCID；不传则用该租户第一个运行中实例"),
    hours: int = Query(default=24, ge=1, le=168, description="回看小时数"),
    resolution: str = Query(default="1h", pattern="^(1m|5m|1h)$", description="聚合粒度：1m/5m/1h"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(3203, "租户不存在", status=404)

    try:
        target_id = instance_id
        if not target_id:
            # 默认取第一个运行中实例，方便前端开箱展示
            items = instance_service.list_instances(tenant)
            running = next((i for i in items if i.get("lifecycle_state") == "RUNNING"), None)
            if running is None:
                return err(3203, "该租户下没有运行中的实例", status=404)
            target_id = running["id"]
        vnic_id = monitoring_service.get_primary_vnic_id(tenant, target_id)
        points = monitoring_service.query_vnic_traffic(tenant, vnic_id, hours, resolution)
    except ValueError as exc:  # 租户配置异常 / 无 VNIC
        return err(3201, f"查询流量失败：{exc}", status=502)
    except instance_service.OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except (ConnectTimeout, RequestException) as exc:
        return err(3202, f"查询流量失败：连接 OCI 超时（{exc}）", status=502)
    except ServiceError as exc:
        return _translate(exc, "查询流量")
    except Exception as exc:  # 兜底：未知异常不暴露堆栈
        log.exception("查询流量未知异常 tenant_id=%s", tenant_id)
        return err(3200, f"查询流量失败：{str(exc)[:200]}", status=500)

    return ok({"tenant_id": tenant_id, "instance_id": target_id, "vnic_id": vnic_id, "points": points})


@router.get("/bandwidth", summary="实例峰值带宽（近 N 小时出向/入向 Mbps 实测峰值）")
def get_bandwidth(
    tenant_id: int = Query(description="租户 ID（必填）"),
    instance_id: str = Query(description="实例 OCID（必填）"),
    hours: int = Query(default=24, ge=1, le=48, description="回看小时数"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(3203, "租户不存在", status=404)
    try:
        return ok(monitoring_service.get_peak_bandwidth(tenant, instance_id, hours))
    except ValueError as exc:
        return err(3201, f"查询峰值带宽失败：{exc}", status=502)
    except instance_service.OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except (ConnectTimeout, RequestException) as exc:
        return err(3202, f"查询峰值带宽失败：连接 OCI 超时（{exc}）", status=502)
    except ServiceError as exc:
        return _translate(exc, "查询峰值带宽")
    except Exception as exc:
        log.exception("查询峰值带宽未知异常 tenant_id=%s", tenant_id)
        return err(3200, f"查询峰值带宽失败：{str(exc)[:200]}", status=500)


@router.get("/quotas", summary="租户配额查询（真实 Limits API）")
def get_quotas(
    tenant_id: int = Query(description="租户 ID（必填）"),
    compartment_id: str | None = Query(default=None, description="compartment OCID；不传则用租户根"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return err(3203, "租户不存在", status=404)

    comp_id = compartment_id or tenant.tenancy_ocid
    try:
        quotas = monitoring_service.list_compute_limits(tenant, comp_id)
    except ValueError as exc:  # 私钥解密失败等配置问题
        return err(3201, f"查询配额失败：租户配置异常：{exc}", status=502)
    except (ConnectTimeout, RequestException) as exc:
        return err(3202, f"查询配额失败：连接 OCI 超时（{exc}）", status=502)
    except ServiceError as exc:
        return _translate(exc, "查询配额")
    except Exception as exc:
        log.exception("查询配额未知异常 tenant_id=%s", tenant_id)
        return err(3200, f"查询配额失败：{str(exc)[:200]}", status=500)

    return ok({"tenant_id": tenant_id, "compartment_id": comp_id, "quotas": quotas})
