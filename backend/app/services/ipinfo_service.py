"""IP 归属地查询：ip-api.com 批量接口 + 本地缓存（TTL 30 天）。

免费版限制：45 请求/分钟、每批最多 100 个 IP，批次之间 sleep 1.5s 限流。
"""
import logging
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from ..db import models
from .instance_service import OciApiError, list_instances

log = logging.getLogger(__name__)

IP_API_BATCH_URL = "http://ip-api.com/batch"
BATCH_SIZE = 100
BATCH_INTERVAL_SEC = 1.5  # 免费版 45 req/min，批次之间留足间隔
CACHE_TTL_DAYS = 30
FIELDS = "status,country,city,lat,lon,isp,query"


def _ipapi_client() -> httpx.Client:
    """创建 ip-api 请求客户端。

    优先走环境代理（trust_env）；若代理环境变量畸形导致 httpx 解析崩溃
    （如 no_proxy 含方括号 IPv6），则降级为显式代理 URL，绕开有问题的解析。
    """
    try:
        return httpx.Client(timeout=30, trust_env=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("代理环境变量解析失败，改用显式代理访问 ip-api: %s", exc)
        import os

        proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
        return httpx.Client(timeout=30, trust_env=False, proxy=proxy)


def _fetch_batch(ips: list[str]) -> dict[str, dict]:
    """调 ip-api.com 批量接口查一批 IP，返回 {ip: {country, city, lat, lon, isp}}（只含成功项）。"""
    # body 元素可为纯 IP 字符串或 {query, fields} 对象；统一用对象以限定返回字段
    payload = [{"query": ip, "fields": FIELDS} for ip in ips]
    try:
        with _ipapi_client() as client:
            resp = client.post(IP_API_BATCH_URL, json=payload)
            resp.raise_for_status()
            items = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("ip-api 批量查询失败: %s", exc)
        return {}
    result: dict[str, dict] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict) or item.get("status") != "success":
            continue
        ip = item.get("query")
        if not ip:
            continue
        result[ip] = {
            "country": item.get("country"),
            "city": item.get("city"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "isp": item.get("isp"),
        }
    return result


def resolve_locations(db: Session, ips: list[str], force_refresh: bool = False) -> dict[str, dict]:
    """解析一批 IP 的归属地：先读缓存（30 天 TTL），缺失的再批量查询并回写缓存。"""
    uniq = sorted({ip for ip in ips if ip})
    if not uniq:
        return {}

    fresh: dict[str, models.IpLocationCache] = {}
    if not force_refresh:
        cutoff = datetime.now() - timedelta(days=CACHE_TTL_DAYS)
        rows = (
            db.query(models.IpLocationCache)
            .filter(models.IpLocationCache.ip.in_(uniq), models.IpLocationCache.updated_at >= cutoff)
            .all()
        )
        fresh = {r.ip: r for r in rows}

    missing = [ip for ip in uniq if ip not in fresh]
    fetched: dict[str, dict] = {}
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i : i + BATCH_SIZE]
        fetched.update(_fetch_batch(batch))
        if i + BATCH_SIZE < len(missing):
            time.sleep(BATCH_INTERVAL_SEC)

    # 回写缓存（merge 按主键 upsert）
    now = datetime.now()
    for ip, info in fetched.items():
        db.merge(
            models.IpLocationCache(
                ip=ip,
                country=info.get("country"),
                city=info.get("city"),
                lat=info.get("lat"),
                lon=info.get("lon"),
                isp=info.get("isp"),
                updated_at=now,
            )
        )
    if fetched:
        db.commit()

    out: dict[str, dict] = {}
    for ip in uniq:
        if ip in fetched:
            out[ip] = fetched[ip]
        elif ip in fresh:
            r = fresh[ip]
            out[ip] = {"country": r.country, "city": r.city, "lat": r.lat, "lon": r.lon, "isp": r.isp}
    return out


def collect_instance_points(db: Session, force_refresh: bool = False) -> list[dict]:
    """遍历所有租户的实例公网 IP，附上归属地。单租户失败只记日志跳过，不破坏整体。"""
    tenants = db.query(models.Tenant).order_by(models.Tenant.id).all()
    ip_metas: list[dict] = []  # {tenant_name, instance_name, ip}
    for tenant in tenants:
        try:
            instances = list_instances(tenant)
        except OciApiError as exc:
            log.warning("租户 %s 实例列表查询失败，跳过地图打点: %s", tenant.name, exc)
            continue
        except Exception as exc:  # noqa: BLE001  防御性：未知异常不中断整体
            log.warning("租户 %s 查询异常，跳过地图打点: %s", tenant.name, exc)
            continue
        for inst in instances:
            ip = inst.get("public_ip")
            if not ip:
                continue
            ip_metas.append(
                {"tenant_name": tenant.name, "instance_name": inst.get("display_name") or "", "ip": ip}
            )

    locations = resolve_locations(db, [m["ip"] for m in ip_metas], force_refresh=force_refresh)

    points: list[dict] = []
    for meta in ip_metas:
        loc = locations.get(meta["ip"])
        if not loc or loc.get("lat") is None or loc.get("lon") is None:
            continue  # 归属地查不到的不打点，不编造数据
        points.append(
            {
                "tenant_name": meta["tenant_name"],
                "instance_name": meta["instance_name"],
                "ip": meta["ip"],
                "country": loc.get("country"),
                "city": loc.get("city"),
                "lat": loc.get("lat"),
                "lon": loc.get("lon"),
                "isp": loc.get("isp"),
            }
        )
    return points
