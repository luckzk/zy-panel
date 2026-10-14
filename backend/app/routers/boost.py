"""一键 500M 路由：为免费 AMD 实例开启/关闭下行 500Mbps（后台任务）。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import boost_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/boost", tags=["一键 500M"])


class EnableIn(BaseModel):
    tenant_id: int
    instance_id: str
    ssh_port: int = 22  # NLB 健康检查端口


class DisableIn(BaseModel):
    tenant_id: int
    instance_id: str
    retain_nat_gw: bool = False  # 是否保留 NAT 网关
    retain_nlb: bool = False  # 是否保留网络负载均衡器


def _get_tenant_or_404(db: Session, tenant_id: int):
    tenant = db.get(models.Tenant, tenant_id)
    if tenant is None:
        return None, err(3103, "租户不存在", status=404)
    return tenant, None


@router.post("/enable", summary="一键开启下行 500M（后台任务）")
def enable_500m(
    body: EnableIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _, not_found = _get_tenant_or_404(db, body.tenant_id)
    if not_found:
        return not_found
    task_id = boost_service.start_enable(body.tenant_id, body.instance_id, body.ssh_port)
    write_log(db, user.id, "boost.enable", f"下发一键 500M 开启任务 {task_id}（实例 {body.instance_id}）")
    return ok({"task_id": task_id, "status": "running"})


@router.post("/disable", summary="关闭下行 500M（后台任务）")
def disable_500m(
    body: DisableIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _, not_found = _get_tenant_or_404(db, body.tenant_id)
    if not_found:
        return not_found
    task_id = boost_service.start_disable(
        body.tenant_id, body.instance_id, body.retain_nat_gw, body.retain_nlb
    )
    write_log(db, user.id, "boost.disable", f"下发一键 500M 关闭任务 {task_id}（实例 {body.instance_id}）")
    return ok({"task_id": task_id, "status": "running"})


@router.get("/tasks", summary="500M 任务列表")
def list_tasks(_user: models.User = Depends(get_current_user)):
    return ok(boost_service.list_tasks())


@router.get("/tasks/{task_id}", summary="500M 任务状态")
def get_task(task_id: str, _user: models.User = Depends(get_current_user)):
    task = boost_service.get_task(task_id)
    if task is None:
        return err(3103, "任务不存在", status=404)
    return ok(task)
