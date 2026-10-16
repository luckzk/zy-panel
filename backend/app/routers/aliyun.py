"""阿里云厂商命名空间路由：磁盘/快照/EIP/监控（归一化之外的厂商能力）。"""
import logging

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..providers import get_provider
from ..providers.base import ProviderError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/aliyun", tags=["阿里云"])


def _get_aliyun(db: Session, tenant_id: int):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return None, err(2001, "租户不存在", status=404)
    if (getattr(tenant, "provider", None) or "") != "aliyun":
        return None, err(2002, "该租户不是阿里云账号", status=400)
    try:
        return get_provider(tenant), None
    except ProviderError as exc:
        return None, err(exc.code, exc.message, status=exc.http_status)


def _handle(exc: ProviderError):
    return err(exc.code, exc.message, status=exc.http_status)


# ---------------- 磁盘 ----------------
@router.get("/disks", summary="云盘列表")
def list_disks(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok([v.to_dict() for v in p.list_volumes()])
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云云盘列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class ResizeIn(BaseModel):
    tenant_id: int
    new_size_gb: int


@router.post("/disks/{disk_id}/resize", summary="云盘扩容（只允许调大）")
def resize_disk(
    disk_id: str, body: ResizeIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    if body.new_size_gb <= 0:
        return err(2002, "new_size_gb 必须大于 0", status=400)
    try:
        p.resize_disk(disk_id, body.new_size_gb)
        write_log(db, user.id, "aliyun.disk_resize", f"云盘 {disk_id} 扩容到 {body.new_size_gb}GB")
        return ok({"disk_id": disk_id, "new_size_gb": body.new_size_gb})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云云盘扩容异常")
        return err(3100, f"扩容失败：{str(exc)[:200]}", status=500)


# ---------------- 快照 ----------------
@router.get("/snapshots", summary="快照列表")
def list_snapshots(
    tenant_id: int = Query(description="租户 ID（必填）"),
    disk_id: str | None = Query(default=None, description="按云盘过滤"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_snapshots(disk_id))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云快照列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class SnapshotCreateIn(BaseModel):
    tenant_id: int
    disk_id: str
    name: str = ""


@router.post("/snapshots", summary="创建快照")
def create_snapshot(
    body: SnapshotCreateIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        r = p.create_snapshot(body.disk_id, body.name)
        write_log(db, user.id, "aliyun.snapshot_create", f"云盘 {body.disk_id} 创建快照 {r.get('snapshot_id')}")
        return ok(r)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云创建快照异常")
        return err(3100, f"创建失败：{str(exc)[:200]}", status=500)


@router.delete("/snapshots/{snapshot_id}", summary="删除快照")
def delete_snapshot(
    snapshot_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.delete_snapshot(snapshot_id)
        write_log(db, user.id, "aliyun.snapshot_delete", f"删除快照 {snapshot_id}")
        return ok({"snapshot_id": snapshot_id})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除快照异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)


# ---------------- EIP ----------------
@router.get("/eips", summary="弹性公网 IP 列表")
def list_eips(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_eips())
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云 EIP 列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class EipAllocateIn(BaseModel):
    tenant_id: int
    bandwidth: int = 5


@router.post("/eips", summary="申请 EIP（按量付费，按流量计费）")
def allocate_eip(
    body: EipAllocateIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    if not 1 <= body.bandwidth <= 500:
        return err(2002, "带宽范围 1-500 Mbps", status=400)
    try:
        r = p.allocate_eip(body.bandwidth)
        write_log(db, user.id, "aliyun.eip_allocate", f"申请 EIP {r.get('ip')}（{body.bandwidth}Mbps）")
        return ok(r)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云申请 EIP 异常")
        return err(3100, f"申请失败：{str(exc)[:200]}", status=500)


class EipBindIn(BaseModel):
    tenant_id: int
    allocation_id: str
    instance_id: str


@router.post("/eips/bind", summary="EIP 绑定实例")
def bind_eip(
    body: EipBindIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        p.associate_eip(body.allocation_id, body.instance_id)
        write_log(db, user.id, "aliyun.eip_bind", f"EIP {body.allocation_id} 绑定实例 {body.instance_id}")
        return ok({"allocation_id": body.allocation_id, "instance_id": body.instance_id})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云 EIP 绑定异常")
        return err(3100, f"绑定失败：{str(exc)[:200]}", status=500)


@router.post("/eips/unbind", summary="EIP 解绑实例")
def unbind_eip(
    body: EipBindIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        p.unassociate_eip(body.allocation_id, body.instance_id)
        write_log(db, user.id, "aliyun.eip_unbind", f"EIP {body.allocation_id} 解绑实例 {body.instance_id}")
        return ok({"allocation_id": body.allocation_id})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云 EIP 解绑异常")
        return err(3100, f"解绑失败：{str(exc)[:200]}", status=500)


@router.delete("/eips/{allocation_id}", summary="释放 EIP")
def release_eip(
    allocation_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.release_eip(allocation_id)
        write_log(db, user.id, "aliyun.eip_release", f"释放 EIP {allocation_id}")
        return ok({"allocation_id": allocation_id})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云释放 EIP 异常")
        return err(3100, f"释放失败：{str(exc)[:200]}", status=500)


# ---------------- 监控 ----------------
@router.get("/instances/{instance_id}/metrics", summary="实例监控指标（CMS）")
def instance_metrics(
    instance_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    hours: int = Query(default=6, ge=1, le=72, description="回看小时数"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok({"instance_id": instance_id, "charts": p.get_instance_metrics(instance_id, hours)})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云监控指标异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


# ---------------- 镜像 ----------------
@router.get("/images", summary="自定义镜像列表")
def list_images(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_images())
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云镜像列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


@router.get("/images/public", summary="公共镜像列表（创建实例/抢占式任务用）")
def list_public_images(
    tenant_id: int = Query(description="租户 ID（必填）"),
    os_type: str = Query(default="linux", description="linux / windows"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_public_images(os_type))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云公共镜像异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class ImageCreateIn(BaseModel):
    tenant_id: int
    instance_id: str | None = None
    snapshot_id: str | None = None
    name: str = ""
    description: str = ""


@router.post("/images", summary="创建自定义镜像（从实例或快照）")
def create_image(
    body: ImageCreateIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        r = p.create_image(body.instance_id, body.snapshot_id, body.name, body.description)
        write_log(db, user.id, "aliyun.image_create", f"创建镜像 {r.get('image_id')}（{body.name}）")
        return ok(r)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云创建镜像异常")
        return err(3100, f"创建失败：{str(exc)[:200]}", status=500)


@router.delete("/images/{image_id}", summary="删除自定义镜像")
def delete_image(
    image_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.delete_image(image_id)
        write_log(db, user.id, "aliyun.image_delete", f"删除镜像 {image_id}")
        return ok({"image_id": image_id})
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除镜像异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)


# ---------------- 费用 ----------------
@router.get("/billing/summary", summary="费用概览（余额 + 当月账单）")
def billing_summary(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        balance = p.get_account_balance()
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云余额查询异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)
    try:
        bill = p.get_month_bill()
    except Exception as exc:
        log.warning("阿里云账单查询失败: %s", exc)
        bill = {"billing_cycle": "", "total": 0, "products": [], "error": str(exc)[:150]}
    return ok({"balance": balance, "bill": bill})


# ---------------- 抢占式任务支持数据 ----------------
@router.get("/instance-types", summary="实例规格列表")
def list_instance_types(
    tenant_id: int = Query(description="租户 ID（必填）"),
    zone_id: str = Query(default="", description="可用区过滤"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_instance_types(zone_id))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云规格列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


@router.get("/vswitches", summary="交换机列表")
def list_vswitches(
    tenant_id: int = Query(description="租户 ID（必填）"),
    zone_id: str = Query(default="", description="可用区过滤"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_vswitches(zone_id))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云交换机列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


# ---------------- 抢占式实例任务 ----------------
def _spot_to_out(t) -> dict:
    import json as _json
    try:
        logs = _json.loads(t.recent_logs) if t.recent_logs else []
    except Exception:
        logs = []
    return {
        "id": t.id, "tenant_id": t.tenant_id, "name": t.name,
        "region_id": t.region_id, "zone_id": t.zone_id,
        "instance_type": t.instance_type, "image_id": t.image_id,
        "vswitch_id": t.vswitch_id, "security_group_id": t.security_group_id,
        "spot_strategy": t.spot_strategy, "spot_price_limit": t.spot_price_limit,
        "system_disk_category": t.system_disk_category, "system_disk_size": t.system_disk_size,
        "bandwidth_out": t.bandwidth_out, "instance_name": t.instance_name,
        "status": t.status, "interval_sec": t.interval_sec, "max_attempts": t.max_attempts,
        "attempts": t.attempts, "last_error": t.last_error,
        "recent_logs": logs,
        "last_attempt_at": t.last_attempt_at.isoformat() if t.last_attempt_at else None,
        "next_attempt_at": t.next_attempt_at.isoformat() if t.next_attempt_at else None,
        "created_instance_id": t.created_instance_id,
    }


class SpotTaskIn(BaseModel):
    tenant_id: int
    name: str
    region_id: str
    zone_id: str = ""
    instance_type: str
    image_id: str
    vswitch_id: str
    security_group_id: str
    spot_strategy: str = "SpotWithPriceLimit"
    spot_price_limit: str | None = None
    system_disk_category: str = "cloud_essd"
    system_disk_size: int = 40
    bandwidth_out: int = 5
    instance_name: str = "panel-spot"
    interval_sec: int = 60
    max_attempts: int = 0


@router.get("/spot-tasks", summary="抢占式任务列表")
def list_spot_tasks(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    tasks = db.query(models.AliyunSpotTask).filter(
        models.AliyunSpotTask.tenant_id == tenant_id
    ).order_by(models.AliyunSpotTask.id.desc()).all()
    return ok([_spot_to_out(t) for t in tasks])


@router.post("/spot-tasks", summary="创建抢占式任务")
def create_spot_task(
    body: SpotTaskIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    if body.spot_strategy not in ("SpotWithPriceLimit", "SpotAsPriceGo"):
        return err(2002, "spot_strategy 仅支持 SpotWithPriceLimit / SpotAsPriceGo", status=400)
    if body.spot_strategy == "SpotWithPriceLimit" and not body.spot_price_limit:
        return err(2002, "限价策略必须填写最高出价 spot_price_limit", status=400)
    t = models.AliyunSpotTask(**{k: v for k, v in body.model_dump().items()})
    db.add(t)
    db.commit()
    db.refresh(t)
    write_log(db, user.id, "aliyun.spot_create", f"创建抢占式任务 {t.name}")
    return ok(_spot_to_out(t))


@router.post("/spot-tasks/{task_id}/start", summary="启动抢占式任务")
def start_spot_task(
    task_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.get(models.AliyunSpotTask, task_id)
    if t is None:
        return err(2001, "任务不存在", status=404)
    p, e = _get_aliyun(db, t.tenant_id)
    if e:
        return e
    if t.status == "running":
        return err(2002, "任务已在运行中", status=400)
    t.status = "running"
    t.next_attempt_at = None
    db.commit()
    write_log(db, user.id, "aliyun.spot_start", f"启动抢占式任务 {t.name}")
    return ok(_spot_to_out(t))


@router.post("/spot-tasks/{task_id}/pause", summary="暂停抢占式任务")
def pause_spot_task(
    task_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.get(models.AliyunSpotTask, task_id)
    if t is None:
        return err(2001, "任务不存在", status=404)
    if t.status != "running":
        return err(2002, "只有运行中的任务可以暂停", status=400)
    t.status = "paused"
    db.commit()
    write_log(db, user.id, "aliyun.spot_pause", f"暂停抢占式任务 {t.name}")
    return ok(_spot_to_out(t))


@router.delete("/spot-tasks/{task_id}", summary="删除抢占式任务")
def delete_spot_task(
    task_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    t = db.get(models.AliyunSpotTask, task_id)
    if t is None:
        return err(2001, "任务不存在", status=404)
    if t.status == "running":
        return err(2002, "请先暂停运行中的任务再删除", status=400)
    db.delete(t)
    db.commit()
    write_log(db, user.id, "aliyun.spot_delete", f"删除抢占式任务 {t.name}")
    return ok({"id": task_id})


# ---------------- RAM 子用户 ----------------
@router.get("/ram/users", summary="RAM 用户列表")
def list_ram_users(
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_ram_users())
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云 RAM 用户列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class RamUserIn(BaseModel):
    tenant_id: int
    user_name: str
    display_name: str = ""
    mobile_phone: str = ""
    email: str = ""
    comments: str = ""


@router.post("/ram/users", summary="创建 RAM 用户")
def create_ram_user(
    body: RamUserIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        r = p.create_ram_user(body.user_name, body.display_name,
                              body.mobile_phone, body.email, body.comments)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云创建 RAM 用户异常")
        return err(3100, f"创建失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.ram_user_create", f"创建 RAM 用户 {r['user_name']}")
    return ok(r)


@router.delete("/ram/users/{user_name}", summary="删除 RAM 用户（含其 AccessKey）")
def delete_ram_user(
    user_name: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.delete_ram_user(user_name)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除 RAM 用户异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.ram_user_delete", f"删除 RAM 用户 {user_name}")
    return ok({"user_name": user_name})


@router.get("/ram/users/{user_name}/keys", summary="RAM 用户 AccessKey 列表")
def list_ram_access_keys(
    user_name: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_access_keys(user_name))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云 AccessKey 列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class RamKeyIn(BaseModel):
    tenant_id: int


@router.post("/ram/users/{user_name}/keys", summary="为 RAM 用户创建 AccessKey（Secret 仅返回一次）")
def create_ram_access_key(
    user_name: str,
    body: RamKeyIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        r = p.create_access_key(user_name)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云创建 AccessKey 异常")
        return err(3100, f"创建失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.ram_key_create", f"为 RAM 用户 {user_name} 创建 AccessKey")
    return ok(r)


@router.delete("/ram/users/{user_name}/keys/{key_id}", summary="删除 RAM 用户 AccessKey")
def delete_ram_access_key(
    user_name: str,
    key_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.delete_access_key(user_name, key_id)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除 AccessKey 异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.ram_key_delete", f"删除 RAM 用户 {user_name} 的 AccessKey {key_id}")
    return ok({"user_name": user_name, "key_id": key_id})


# ---------------- 安全组 ----------------
@router.get("/security-groups", summary="安全组列表")
def list_security_groups(
    tenant_id: int = Query(description="租户 ID（必填）"),
    region_id: str | None = Query(default=None, description="地域，不填用租户默认"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok([g.to_dict() for g in p.list_security_groups(region_id)])
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云安全组列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


@router.get("/security-groups/{sg_id}/rules", summary="安全组规则列表")
def list_security_group_rules(
    sg_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    region_id: str | None = Query(default=None, description="地域，不填用租户默认"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        return ok(p.list_security_group_rules(sg_id, region_id))
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云安全组规则列表异常")
        return err(3100, f"查询失败：{str(exc)[:200]}", status=500)


class SgRuleIn(BaseModel):
    tenant_id: int
    direction: str = "ingress"  # ingress / egress
    protocol: str = "tcp"       # tcp / udp / icmp / all
    port_range: str = ""        # 如 80/80、8000/9000、-1/-1（全部）
    cidr: str = "0.0.0.0/0"
    description: str = ""
    region_id: str | None = None


@router.post("/security-groups/{sg_id}/rules", summary="添加安全组规则")
def authorize_security_group_rule(
    sg_id: str,
    body: SgRuleIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        p.authorize_security_group_rule(
            sg_id, body.direction, body.protocol, body.port_range,
            body.cidr, body.description, body.region_id,
        )
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云添加安全组规则异常")
        return err(3100, f"添加失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.sg_rule_add",
              f"安全组 {sg_id} 添加{body.direction}规则 {body.protocol} {body.port_range} {body.cidr}")
    return ok({"security_group_id": sg_id})


@router.delete("/security-groups/{sg_id}/rules", summary="删除安全组规则")
def revoke_security_group_rule(
    sg_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    direction: str = Query(default="ingress"),
    protocol: str = Query(default="tcp"),
    port_range: str = Query(description="端口范围，如 80/80"),
    cidr: str = Query(default="0.0.0.0/0"),
    region_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.revoke_security_group_rule(sg_id, direction, protocol, port_range, cidr, region_id)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除安全组规则异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.sg_rule_delete",
              f"安全组 {sg_id} 删除{direction}规则 {protocol} {port_range} {cidr}")
    return ok({"security_group_id": sg_id})


class SgCreateIn(BaseModel):
    tenant_id: int
    name: str
    description: str = ""
    vpc_id: str = ""
    region_id: str | None = None


@router.post("/security-groups", summary="创建安全组")
def create_security_group(
    body: SgCreateIn,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    p, e = _get_aliyun(db, body.tenant_id)
    if e:
        return e
    try:
        r = p.create_security_group(body.name, body.description, body.vpc_id, body.region_id)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云创建安全组异常")
        return err(3100, f"创建失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.sg_create", f"创建安全组 {r.get('security_group_id')}（{body.name}）")
    return ok(r)


@router.delete("/security-groups/{sg_id}", summary="删除安全组")
def delete_security_group(
    sg_id: str,
    tenant_id: int = Query(description="租户 ID（必填）"),
    region_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    p, e = _get_aliyun(db, tenant_id)
    if e:
        return e
    try:
        p.delete_security_group(sg_id, region_id)
    except ProviderError as exc:
        return _handle(exc)
    except Exception as exc:
        log.exception("阿里云删除安全组异常")
        return err(3100, f"删除失败：{str(exc)[:200]}", status=500)
    write_log(db, user.id, "aliyun.sg_delete", f"删除安全组 {sg_id}")
    return ok({"security_group_id": sg_id})
