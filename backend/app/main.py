"""应用入口：FastAPI 应用、路由挂载（/api/v1）、CORS、APScheduler、SQLite 建表。

启动：
    uvicorn app.main:app --port 8818 --reload
文档：
    http://127.0.0.1:8818/docs
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.response import ok
from .db.session import init_db, seed_admin
from .routers import all_routers
from .routers.terminal import ws_terminal
from .routers.console import ws_console
from .workers.scheduler import shutdown_scheduler, start_scheduler
from .ws.manager import ws_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：建表 + 播种默认管理员 + 启动定时任务
    init_db()
    seed_admin()
    log.info("数据库初始化完成，默认管理员账号 admin / admin123（首次登录后请修改）")
    start_scheduler()
    # TG 运维机器人（按配置决定是否轮询）
    try:
        from .services import tg_ops_bot

        tg_ops_bot.start()
    except Exception as exc:
        log.warning("TG 运维机器人启动失败: %s", exc)
    yield
    # 关闭：停掉调度器
    shutdown_scheduler()
    try:
        from .services import tg_ops_bot

        tg_ops_bot.stop()
    except Exception:
        pass


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 所有 HTTP 路由统一挂载在 /api/v1 前缀
for _router in all_routers:
    app.include_router(_router, prefix="/api/v1")


@app.get("/", tags=["健康检查"], summary="健康检查")
def health():
    return ok({"service": settings.app_name, "version": "0.1.0"})


@app.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket):
    """实时日志推送：需 token 鉴权（与 /ws/terminal 同规则）。"""
    from .core.deps import decode_access_token

    await websocket.accept()
    if decode_access_token(websocket.query_params.get("token") or "") is None:
        await websocket.close(code=4401)
        return
    # 注意：ws_manager.connect 内部会 accept，这里已 accept，直接入列
    ws_manager.active.append(websocket)
    try:
        from .db.session import SessionLocal
        from .db import models as _models

        db = SessionLocal()
        try:
            last_id = 0
            rows = (
                db.query(_models.OperationLog)
                .order_by(_models.OperationLog.id.desc())
                .limit(50)
                .all()
            )
            for l in reversed(rows):
                await ws_manager.send_personal(
                    f"[{l.created_at}] {l.action} {l.detail or ''}", websocket
                )
                last_id = max(last_id, l.id)
        finally:
            db.close()
        while True:
            await asyncio.sleep(10)
            db = SessionLocal()
            try:
                rows = (
                    db.query(_models.OperationLog)
                    .filter(_models.OperationLog.id > last_id)
                    .order_by(_models.OperationLog.id.asc())
                    .limit(100)
                    .all()
                )
                for l in rows:
                    await ws_manager.send_personal(
                        f"[{l.created_at}] {l.action} {l.detail or ''}", websocket
                    )
                    last_id = max(last_id, l.id)
            finally:
                db.close()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)


@app.websocket("/ws/terminal")
async def ws_terminal_route(websocket: WebSocket):
    """Web SSH 终端（Cloud Shell 风格），实现见 app/routers/terminal.py。"""
    await ws_terminal(websocket)


@app.websocket("/ws/console")
async def ws_console_route(websocket: WebSocket):
    """串行控制台：OCI Instance Console Connection，不依赖实例网络。实现见 app/routers/console.py。"""
    await ws_console(websocket)
