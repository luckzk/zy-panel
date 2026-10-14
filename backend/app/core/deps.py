"""FastAPI 依赖注入：数据库会话、当前登录用户。"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import models
from ..db.session import SessionLocal
from .security import decode_access_token

bearer_scheme = HTTPBearer(auto_error=False)


def get_db():
    """请求级数据库会话，请求结束自动关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> models.User:
    """从 Authorization: Bearer <JWT> 解析当前用户，未登录抛 401。"""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    username = decode_access_token(credentials.credentials)
    user = db.query(models.User).filter(models.User.username == username).first() if username else None
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效")
    return user
