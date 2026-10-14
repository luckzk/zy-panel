"""审计日志小助手：关键操作写入 operation_logs 表。"""
from sqlalchemy.orm import Session

from ..db import models


def write_log(db: Session, user_id: int | None, action: str, detail: str = "") -> None:
    db.add(models.OperationLog(user_id=user_id, action=action, detail=detail))
    db.commit()
