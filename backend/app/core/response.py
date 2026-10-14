"""统一响应信封：{"code": 0, "msg": "ok", "data": ...}。"""
from typing import Any

from fastapi.responses import JSONResponse


def ok(data: Any = None, msg: str = "ok") -> dict:
    """成功响应。"""
    return {"code": 0, "msg": msg, "data": data}


def err(code: int = 1, msg: str = "error", data: Any = None, status: int = 400) -> JSONResponse:
    """失败响应。"""
    return JSONResponse(status_code=status, content={"code": code, "msg": msg, "data": data})
