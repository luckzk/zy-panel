"""通知渠道路由：Telegram / 邮件配置的 CRUD + 测试发送。

安全：列表/详情输出时 bot_token、smtp_pass 等敏感字段脱敏；
更新支持部分字段（config_json 做浅合并）。
"""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import notification_service as ns

router = APIRouter(prefix="/notifications", tags=["通知"])

VALID_TYPES = ("telegram", "email")

# 各类型创建时的必填配置项
REQUIRED_FIELDS = {
    "telegram": ("bot_token", "chat_id"),
    "email": ("smtp_host", "to_addrs"),
}


class NotificationCreate(BaseModel):
    type: str
    name: str = ""
    config_json: dict = {}
    enabled: bool = True


class NotificationUpdate(BaseModel):
    name: str | None = None
    config_json: dict | None = None  # 传则与已有配置浅合并
    enabled: bool | None = None


def _to_out(c: models.NotificationConfig) -> dict:
    cfg = ns.parse_config(c.config_json)
    return {
        "id": c.id,
        "type": c.type,
        "name": c.name,
        "config": ns.mask_config(cfg),  # 脱敏输出
        "enabled": c.enabled,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


def _check_required(cfg: dict, channel_type: str) -> str | None:
    """返回缺失的必填项描述，无缺失返回 None。"""
    missing = [f for f in REQUIRED_FIELDS[channel_type] if not cfg.get(f)]
    return "、".join(missing) if missing else None


@router.get("", summary="通知渠道列表")
def list_configs(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    rows = db.query(models.NotificationConfig).order_by(models.NotificationConfig.id).all()
    return ok([_to_out(c) for c in rows])


@router.post("", summary="创建通知渠道")
def create_config(
    body: NotificationCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if body.type not in VALID_TYPES:
        return err(6001, f"不支持的渠道类型：{body.type}，可选 telegram / email", status=400)
    missing = _check_required(body.config_json, body.type)
    if missing:
        return err(6002, f"配置缺失必填项：{missing}", status=400)
    cfg = models.NotificationConfig(
        type=body.type,
        name=body.name,
        config_json=json.dumps(body.config_json, ensure_ascii=False),
        enabled=body.enabled,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    write_log(db, user.id, "notification.create", f"创建通知渠道 {cfg.name}（{cfg.type}）")
    return ok(_to_out(cfg))


@router.put("/{config_id}", summary="更新通知渠道（支持部分字段）")
def update_config(
    config_id: int,
    body: NotificationUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cfg = db.get(models.NotificationConfig, config_id)
    if cfg is None:
        return err(6003, "通知渠道不存在", status=404)
    if body.name is not None:
        cfg.name = body.name
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.config_json is not None:
        merged = ns.parse_config(cfg.config_json)
        merged.update(body.config_json)  # 浅合并：只传要改的字段
        cfg.config_json = json.dumps(merged, ensure_ascii=False)
        missing = _check_required(merged, cfg.type)
        if missing:
            db.rollback()
            return err(6002, f"配置缺失必填项：{missing}", status=400)
    db.commit()
    write_log(db, user.id, "notification.update", f"更新通知渠道 {cfg.name}")
    return ok(_to_out(cfg))


@router.delete("/{config_id}", summary="删除通知渠道")
def delete_config(
    config_id: int,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    cfg = db.get(models.NotificationConfig, config_id)
    if cfg is None:
        return err(6003, "通知渠道不存在", status=404)
    db.delete(cfg)
    db.commit()
    write_log(db, user.id, "notification.delete", f"删除通知渠道 {cfg.name}")
    return ok(msg="删除成功")


@router.post("/{config_id}/test", summary="发送测试消息")
def test_config(
    config_id: int,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    cfg = db.get(models.NotificationConfig, config_id)
    if cfg is None:
        return err(6003, "通知渠道不存在", status=404)
    result = ns.send_to_one(cfg, ns.parse_config(cfg.config_json), "OCI 面板测试通知", "这是一条测试消息，说明该通知渠道工作正常。")
    return ok(result)
