"""定时任务路由：CRUD + 启用/禁用 + 立即执行。

cron 为标准 5 段表达式，按 Asia/Shanghai 解析；
next_run_at 落库为 UTC 时间，前端展示时按本地时区转换。
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..workers.scheduled_worker import TASK_TYPES, compute_next_run, execute_scheduled_task, validate_cron

router = APIRouter(prefix="/scheduled-tasks", tags=["定时任务"])

TASK_TYPE_NAMES = {
    "power_on": "定时开机",
    "power_off": "定时关机",
    "reboot": "定时重启",
    "change_ip": "定时换 IP",
}


class ScheduledTaskCreate(BaseModel):
    tenant_id: int
    name: str
    task_type: str
    instance_id: str
    cron_expr: str
    enabled: bool = True


class ScheduledTaskUpdate(BaseModel):
    name: str | None = None
    task_type: str | None = None
    instance_id: str | None = None
    cron_expr: str | None = None
    enabled: bool | None = None


class ToggleIn(BaseModel):
    enabled: bool


def _check_task_type(task_type: str):
    """返回 err 响应或 None（合法）。"""
    if task_type not in TASK_TYPES:
        return err(8004, f"任务类型非法，应为 {', '.join(TASK_TYPES)} 之一", status=400)
    return None


def _check_cron(cron_expr: str):
    """返回 (err响应或None, next_run_at或None)。"""
    try:
        validate_cron(cron_expr)
        return None, compute_next_run(cron_expr)
    except ValueError as exc:
        return err(8001, f"cron 表达式非法：{exc}", status=400), None


def _to_out(t: models.ScheduledTask) -> dict:
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "name": t.name,
        "task_type": t.task_type,
        "task_type_name": TASK_TYPE_NAMES.get(t.task_type, t.task_type),
        "instance_id": t.instance_id,
        "cron_expr": t.cron_expr,
        "enabled": t.enabled,
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "last_status": t.last_status,
        "last_error": t.last_error,
        "next_run_at": t.next_run_at.isoformat() if t.next_run_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/task-types", summary="支持的任务类型")
def list_task_types(_user: models.User = Depends(get_current_user)):
    return ok([{"value": v, "label": TASK_TYPE_NAMES[v]} for v in TASK_TYPES])


@router.get("", summary="定时任务列表")
def list_tasks(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tasks = db.query(models.ScheduledTask).order_by(models.ScheduledTask.id.desc()).all()
    return ok([_to_out(t) for t in tasks])


@router.post("", summary="创建定时任务")
def create_task(
    body: ScheduledTaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if db.get(models.Tenant, body.tenant_id) is None:
        return err(8003, "租户不存在", status=404)
    if (e := _check_task_type(body.task_type)) is not None:
        return e
    if (e := _check_cron(body.cron_expr))[0] is not None:
        return e[0]
    next_run_at = e[1]
    task = models.ScheduledTask(
        tenant_id=body.tenant_id,
        name=body.name,
        task_type=body.task_type,
        instance_id=body.instance_id,
        cron_expr=body.cron_expr.strip(),
        enabled=body.enabled,
        next_run_at=next_run_at if body.enabled else None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    write_log(db, user.id, "scheduled.create", f"创建定时任务 {task.name}（{task.cron_expr}）")
    return ok(_to_out(task))


@router.get("/{task_id}", summary="定时任务详情")
def get_task(task_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    task = db.get(models.ScheduledTask, task_id)
    if task is None:
        return err(8002, "任务不存在", status=404)
    return ok(_to_out(task))


@router.put("/{task_id}", summary="更新定时任务")
def update_task(
    task_id: int,
    body: ScheduledTaskUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = db.get(models.ScheduledTask, task_id)
    if task is None:
        return err(8002, "任务不存在", status=404)
    data = body.model_dump(exclude_unset=True)
    if "task_type" in data:
        if (e := _check_task_type(data["task_type"])) is not None:
            return e
    if "cron_expr" in data:
        data["cron_expr"] = data["cron_expr"].strip()
        if (e := _check_cron(data["cron_expr"]))[0] is not None:
            return e[0]
        data["next_run_at"] = e[1]
    if "enabled" in data and data["enabled"] and task.next_run_at is None:
        # 重新启用且无下次时间时重算
        try:
            data["next_run_at"] = compute_next_run(data.get("cron_expr", task.cron_expr))
        except ValueError:
            pass
    for key, value in data.items():
        setattr(task, key, value)
    db.commit()
    write_log(db, user.id, "scheduled.update", f"更新定时任务 {task.name}")
    return ok(_to_out(task))


@router.delete("/{task_id}", summary="删除定时任务")
def delete_task(
    task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    task = db.get(models.ScheduledTask, task_id)
    if task is None:
        return err(8002, "任务不存在", status=404)
    db.delete(task)
    db.commit()
    write_log(db, user.id, "scheduled.delete", f"删除定时任务 {task.name}")
    return ok(msg="删除成功")


@router.post("/{task_id}/toggle", summary="启用 / 禁用定时任务")
def toggle_task(
    task_id: int,
    body: ToggleIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = db.get(models.ScheduledTask, task_id)
    if task is None:
        return err(8002, "任务不存在", status=404)
    task.enabled = body.enabled
    if body.enabled and task.next_run_at is None:
        try:
            task.next_run_at = compute_next_run(task.cron_expr)
        except ValueError as exc:
            return err(8001, f"cron 表达式非法：{exc}", status=400)
    if not body.enabled:
        task.next_run_at = None
    db.commit()
    write_log(db, user.id, "scheduled.toggle", f"{'启用' if body.enabled else '禁用'}定时任务 {task.name}")
    return ok(_to_out(task))


@router.post("/{task_id}/run-now", summary="立即执行一次")
def run_now(
    task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    task = db.get(models.ScheduledTask, task_id)
    if task is None:
        return err(8002, "任务不存在", status=404)
    result = execute_scheduled_task(task_id)
    write_log(db, user.id, "scheduled.run_now", f"手动执行定时任务 {task.name}：{result['msg'][:100]}")
    db.refresh(task)
    return ok({**_to_out(task), "exec_result": result})
