"""定时任务 worker：cron 表达式驱动的实例电源操作 / 换 IP。

设计：
- APScheduler 每 60 秒调用 run_scheduled_tasks()
- 扫描 enabled 且 next_run_at <= now(UTC) 的任务逐个执行
- power_on/power_off/reboot -> instance_service.power_instance 真实调用
- change_ip -> 创建一条 IpTask(status=running)，由换 IP worker 接管执行
- 执行后更新 last_run_at/last_status/last_error 并重算 next_run_at
- 单个任务异常隔离，不影响其他任务；失败时尝试通知
- cron 按 Asia/Shanghai 解析（用户视角的"每天 2 点"），落库用 naive UTC
"""
import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from ..db import models
from ..db.session import SessionLocal
from ..services import instance_service

log = logging.getLogger(__name__)

SCHEDULED_TZ = "Asia/Shanghai"
SH_TZ = ZoneInfo(SCHEDULED_TZ)

# 定时任务类型 -> 电源操作
POWER_ACTION_MAP = {
    "power_on": "start",
    "power_off": "stop",
    "reboot": "reboot",
}

TASK_TYPES = ("power_on", "power_off", "reboot", "change_ip")


def _now_utc() -> datetime:
    """naive UTC 当前时间（与 DB DateTime 列保持一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def validate_cron(cron_expr: str) -> None:
    """校验 cron 表达式合法性（5 段），非法抛 ValueError。"""
    CronTrigger.from_crontab(cron_expr, timezone=SCHEDULED_TZ)


def compute_next_run(cron_expr: str, after: datetime | None = None) -> datetime:
    """计算下次触发时间，返回 naive UTC。非法表达式抛 ValueError。"""
    trigger = CronTrigger.from_crontab(cron_expr, timezone=SCHEDULED_TZ)
    base = after or _now_utc()
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    nxt = trigger.get_next_fire_time(None, base)
    if nxt is None:
        raise ValueError(f"cron 表达式 {cron_expr!r} 无法计算下次执行时间")
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=SH_TZ)
    return nxt.astimezone(timezone.utc).replace(tzinfo=None)


def _finish(db, task: models.ScheduledTask, ok: bool, detail: str) -> None:
    now = _now_utc()
    task.last_run_at = now
    task.last_status = "success" if ok else "failed"
    task.last_error = None if ok else f"[{now:%m-%d %H:%M:%S}] {detail}"
    try:
        task.next_run_at = compute_next_run(task.cron_expr, after=now)
    except ValueError as exc:
        # cron 被改坏时暂停后续触发，等待人工修复
        task.next_run_at = None
        log.warning("定时任务 %s cron 非法，暂停触发：%s", task.id, exc)
    db.commit()


def _notify_failure(task_name: str, detail: str) -> None:
    try:
        from ..services.notification_service import send_to_all

        send_to_all(title="⚠️ 定时任务执行失败", body=f"任务「{task_name}」执行失败：{detail[:200]}")
    except Exception:
        log.exception("定时任务失败通知发送异常")


def execute_scheduled_task(task_id: int) -> dict:
    """执行单个定时任务（同步，供 worker 轮询和 run-now 接口共用）。"""
    db = SessionLocal()
    try:
        task = db.get(models.ScheduledTask, task_id)
        if task is None:
            return {"ok": False, "msg": "任务不存在"}
        if not task.enabled:
            return {"ok": False, "msg": "任务已禁用"}
        tenant = db.get(models.Tenant, task.tenant_id)
        if tenant is None:
            _finish(db, task, False, "关联的租户配置已被删除")
            return {"ok": False, "msg": "关联租户已被删除"}

        task_name = task.name
        try:
            if task.task_type in POWER_ACTION_MAP:
                action = POWER_ACTION_MAP[task.task_type]
                instance_service.power_instance(tenant, task.instance_id, action)
                detail = f"电源操作 {action} 已下发"
            elif task.task_type == "change_ip":
                ip_task = models.IpTask(
                    tenant_id=tenant.id,
                    instance_id=task.instance_id,
                    preferred_cidrs="[]",
                    update_dns=False,
                    status="running",
                )
                db.add(ip_task)
                db.flush()
                detail = f"已创建换 IP 任务 #{ip_task.id}，由换 IP worker 执行"
            else:
                _finish(db, task, False, f"未知任务类型：{task.task_type}")
                return {"ok": False, "msg": f"未知任务类型：{task.task_type}"}
        except Exception as exc:
            err_msg = getattr(exc, "message", None) or str(exc) or "未知错误"
            _finish(db, task, False, f"执行失败：{err_msg[:300]}")
            _notify_failure(task_name, err_msg)
            log.warning("定时任务 %s 执行失败：%s", task_id, err_msg[:200])
            return {"ok": False, "msg": err_msg[:300]}

        _finish(db, task, True, detail)
        log.info("定时任务 %s 执行成功：%s", task_id, detail)
        return {"ok": True, "msg": detail}
    finally:
        db.close()


async def run_scheduled_tasks() -> None:
    """定时入口：每 60 秒扫描到期的定时任务并执行。"""
    db = SessionLocal()
    try:
        now = _now_utc()
        tasks = (
            db.query(models.ScheduledTask)
            .filter(
                models.ScheduledTask.enabled == True,  # noqa: E712
                models.ScheduledTask.next_run_at.isnot(None),
                models.ScheduledTask.next_run_at <= now,
            )
            .all()
        )
        task_ids = [t.id for t in tasks]
    finally:
        db.close()

    for task_id in task_ids:
        try:
            execute_scheduled_task(task_id)
        except Exception:
            log.exception("定时任务 %s 执行异常（已隔离）", task_id)
