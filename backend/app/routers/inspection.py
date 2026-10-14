"""巡检路由：一键巡检全部/指定租户的实例状态，异常自动通知。"""
import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import ok
from ..db import models
from ..services import inspection_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/inspection", tags=["巡检"])


class RunIn(BaseModel):
    tenant_ids: list[int] | None = None  # 为空则巡检全部租户


@router.post("/run", summary="执行一键巡检")
def run_inspection(
    body: RunIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """同步执行巡检（单个租户异常已在服务层隔离，不会中断整体）。

    若发现 warning 及以上级别问题，自动通过通知渠道推送。
    """
    report = inspection_service.inspect_all(db, body.tenant_ids)

    important = [i for i in report["issues"] if i["level"] in ("error", "warning")]
    notified = None
    if important:
        try:
            from ..services.notification_service import send_to_all

            lines = "\n".join(
                f"[{i['level']}] {i['tenant']} / {i['instance']}：{i['message']}"
                for i in important[:20]
            )
            more = f"\n…等共 {len(important)} 项" if len(important) > 20 else ""
            notified = send_to_all("⚠️ 巡检发现异常", f"共 {len(important)} 项异常：\n{lines}{more}")
        except Exception:
            log.exception("巡检通知发送失败")

    return ok({**report, "notified": notified})
