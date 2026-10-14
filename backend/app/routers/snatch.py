"""抢机任务路由：CRUD + 状态机流转（start/pause/resume）。

状态机：pending -> running -> (paused <-> running) -> success / failed
任务行落库，worker 定时扫描 running 任务，服务重启自动续跑。
"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models

router = APIRouter(prefix="/snatch-tasks", tags=["抢机任务"])

VALID_TRANSITIONS = {
    "start": ("pending", "paused"),
    "pause": ("running",),
    "resume": ("paused",),
}


class SnatchTaskCreate(BaseModel):
    tenant_id: int
    name: str
    shape: str = "VM.Standard.A1.Flex"
    compartment_id: str = ""
    image_id: str = ""
    boot_volume_id: str = ""  # 从现有引导卷启动（与 image_id 二选一，优先）
    subnet_id: str = ""
    availability_domain: str = ""
    availability_domains: list[str] | None = None  # 多 AD 轮询，为空则用 availability_domain
    ocpus: float | None = None
    memory_in_gbs: float | None = None
    display_name: str = ""
    assign_public_ip: bool = True
    ssh_public_key: str | None = None
    interval_sec: int = 15
    max_attempts: int = 0  # 0 = 不限


class SnatchTaskUpdate(BaseModel):
    name: str | None = None
    shape: str | None = None
    compartment_id: str | None = None
    image_id: str | None = None
    boot_volume_id: str | None = None  # 传 "" 清空则回退到镜像模式
    subnet_id: str | None = None
    availability_domain: str | None = None
    availability_domains: list[str] | None = None  # 传 [] 或 None 清空多 AD
    ocpus: float | None = None
    memory_in_gbs: float | None = None
    display_name: str | None = None
    assign_public_ip: bool | None = None
    ssh_public_key: str | None = None
    interval_sec: int | None = None
    max_attempts: int | None = None


def _to_out(t: models.SnatchTask) -> dict:
    try:
        ads = json.loads(t.availability_domains) if t.availability_domains else []
        if not isinstance(ads, list):
            ads = []
    except (json.JSONDecodeError, TypeError):
        ads = []
    try:
        recent_logs = json.loads(t.recent_logs) if t.recent_logs else []
        if not isinstance(recent_logs, list):
            recent_logs = []
    except (json.JSONDecodeError, TypeError):
        recent_logs = []
    return {
        "id": t.id,
        "tenant_id": t.tenant_id,
        "name": t.name,
        "shape": t.shape,
        "compartment_id": t.compartment_id,
        "image_id": t.image_id,
        "boot_volume_id": getattr(t, "boot_volume_id", "") or "",
        "subnet_id": t.subnet_id,
        "availability_domain": t.availability_domain,
        "availability_domains": ads,
        "ocpus": t.ocpus,
        "memory_in_gbs": t.memory_in_gbs,
        "display_name": t.display_name,
        "assign_public_ip": t.assign_public_ip,
        "has_ssh_key": bool(t.ssh_public_key),  # 只返回是否配置，不回显密钥
        "status": t.status,
        "interval_sec": t.interval_sec,
        "max_attempts": t.max_attempts,
        "attempts": t.attempts,
        "last_error": t.last_error,
        "recent_logs": recent_logs,
        "last_attempt_at": t.last_attempt_at.isoformat() if t.last_attempt_at else None,
        "next_attempt_at": t.next_attempt_at.isoformat() if t.next_attempt_at else None,
        "created_instance_id": t.created_instance_id,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("", summary="抢机任务列表")
def list_tasks(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tasks = db.query(models.SnatchTask).order_by(models.SnatchTask.id.desc()).all()
    return ok([_to_out(t) for t in tasks])


@router.post("", summary="创建抢机任务（初始 pending）")
def create_task(
    body: SnatchTaskCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if db.get(models.Tenant, body.tenant_id) is None:
        return err(4001, "租户不存在", status=404)
    data = body.model_dump()
    ads = data.pop("availability_domains", None)
    task = models.SnatchTask(**data, availability_domains=json.dumps(ads) if ads else None)
    db.add(task)
    db.commit()
    db.refresh(task)
    write_log(db, user.id, "snatch.create", f"创建抢机任务 {task.name}")
    return ok(_to_out(task))


@router.get("/stats", summary="抢机统计：状态分布 / 总尝试次数 / 成功率")
def task_stats(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    tasks = db.query(models.SnatchTask).all()
    by_status = {"pending": 0, "running": 0, "paused": 0, "success": 0, "failed": 0}
    total_attempts = 0
    for t in tasks:
        if t.status in by_status:
            by_status[t.status] += 1
        total_attempts += t.attempts or 0
    done = by_status["success"] + by_status["failed"]
    success_rate = round(by_status["success"] / done, 4) if done else 0
    return ok(
        {
            "total": len(tasks),
            "by_status": by_status,
            "total_attempts": total_attempts,
            "success_rate": success_rate,
        }
    )


@router.get("/{task_id}", summary="抢机任务详情")
def get_task(task_id: int, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    task = db.get(models.SnatchTask, task_id)
    if task is None:
        return err(4002, "任务不存在", status=404)
    return ok(_to_out(task))


@router.put("/{task_id}", summary="更新抢机任务（仅 pending/paused 可改配置）")
def update_task(
    task_id: int,
    body: SnatchTaskUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    task = db.get(models.SnatchTask, task_id)
    if task is None:
        return err(4002, "任务不存在", status=404)
    if task.status not in ("pending", "paused"):
        return err(4003, f"任务 {task.status} 状态下不可修改配置", status=400)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "availability_domains":
            value = json.dumps(value) if value else None
        setattr(task, key, value)
    db.commit()
    return ok(_to_out(task))


@router.delete("/{task_id}", summary="删除抢机任务")
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    task = db.get(models.SnatchTask, task_id)
    if task is None:
        return err(4002, "任务不存在", status=404)
    db.delete(task)
    db.commit()
    write_log(db, user.id, "snatch.delete", f"删除抢机任务 {task.name}")
    return ok(msg="删除成功")


def _transition(db: Session, user: models.User, task_id: int, op: str):
    """状态机流转：非法流转返回错误。"""
    task = db.get(models.SnatchTask, task_id)
    if task is None:
        return err(4002, "任务不存在", status=404)
    allowed = VALID_TRANSITIONS[op]
    if task.status not in allowed:
        return err(4004, f"任务当前为 {task.status}，不允许 {op}", status=400)
    new_status = {"start": "running", "pause": "paused", "resume": "running"}[op]
    task.status = new_status
    db.commit()
    write_log(db, user.id, f"snatch.{op}", f"抢机任务 {task.name} -> {new_status}")
    return ok(_to_out(task))


@router.post("/{task_id}/start", summary="启动任务（pending/paused -> running）")
def start_task(task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _transition(db, user, task_id, "start")


@router.post("/{task_id}/pause", summary="暂停任务（running -> paused）")
def pause_task(task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _transition(db, user, task_id, "pause")


@router.post("/{task_id}/resume", summary="继续任务（paused -> running）")
def resume_task(task_id: int, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _transition(db, user, task_id, "resume")
