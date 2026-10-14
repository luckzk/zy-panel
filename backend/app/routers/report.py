"""每日健康报告路由：配置读写 + 立即发送（仅管理员）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import report_service

router = APIRouter(prefix="/system/daily-report", tags=["系统"])


def get_admin_user(user: models.User = Depends(get_current_user)) -> models.User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")
    return user


class ReportConfigIn(BaseModel):
    enabled: bool
    time: str = "08:00"

    @field_validator("time")
    @classmethod
    def _check_time(cls, v: str) -> str:
        try:
            return report_service.validate_time(v)
        except ValueError as exc:
            raise ValueError(str(exc))


@router.get("", summary="每日报告配置")
def get_config(db: Session = Depends(get_db), _user: models.User = Depends(get_admin_user)):
    return ok(report_service.get_report_config(db))


@router.post("", summary="更新每日报告配置（仅管理员）")
def update_config(
    body: ReportConfigIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_admin_user),
):
    cfg = report_service.set_report_config(db, body.enabled, body.time)
    write_log(db, user.id, "report.config", f"每日报告：{'启用' if body.enabled else '停用'}，时间 {cfg['time']}")
    return ok(cfg)


@router.post("/send", summary="立即发送一次每日报告（仅管理员，测试用）")
def send_now(db: Session = Depends(get_db), user: models.User = Depends(get_admin_user)):
    try:
        result = report_service.send_daily_report(db, user_id=user.id, mark_sent=False)
    except Exception as exc:
        return err(9001, f"发送失败：{exc}", status=500)
    if not result.get("dispatched"):
        return ok({"body": result.get("body"), "note": "暂无租户配置，仅生成报告正文，未实际发送"})
    return ok({k: v for k, v in result.items() if k != "body"},
              msg=f"已发送（成功 {result.get('channels_ok', 0)} / 失败 {result.get('channels_failed', 0)}）")
