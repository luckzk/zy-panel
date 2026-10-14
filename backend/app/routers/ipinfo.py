"""IP 归属地路由：全球实例分布（真实 OCI 实例公网 IP + ip-api.com 归属地查询）。"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import ok
from ..db import models
from ..services import ipinfo_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/ipinfo", tags=["IP 归属地"])


@router.get("/map", summary="全球实例分布（公网 IP 归属地打点）")
def ip_map(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """返回 [{tenant_name, instance_name, ip, country, city, lat, lon, isp}]；查不到返回空数组。"""
    points = ipinfo_service.collect_instance_points(db)
    return ok(points)


@router.post("/refresh", summary="强制刷新 IP 归属地缓存")
def refresh_ip_cache(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """绕过 30 天缓存，重新查询全部实例公网 IP 的归属地。"""
    points = ipinfo_service.collect_instance_points(db, force_refresh=True)
    return ok(points)
