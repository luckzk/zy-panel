"""串行控制台路由：控制台连接的创建/查询/删除 + WebSocket 串口终端桥接。

WS 协议（与 /ws/terminal 一致）：
- C -> S {"type": "input", "data": str}
- C -> S {"type": "resize", "cols": int, "rows": int}
- S -> C {"type": "output", "data": str}
- S -> C {"type": "error", "message": str}
- S -> C {"type": "closed"}

鉴权：连接时 query 传 token=JWT 与 connection_id，与 HTTP 接口同一套登录态。
"""
import asyncio
import fcntl
import json
import logging
import os
import pty
import struct
import subprocess
import tempfile
import termios
import threading

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..core.deps import get_current_user, get_db
from ..core.response import err, ok
from ..db import models
from ..services import console_service, oci_factory
from ..services.security_service import OciApiError

log = logging.getLogger(__name__)

router = APIRouter(prefix="/console", tags=["串行控制台"])


class ConsoleCreateIn(BaseModel):
    tenant_id: int
    instance_id: str
    instance_name: str = ""


class ResetPasswordIn(BaseModel):
    tenant_id: int
    instance_id: str
    instance_name: str = ""
    username: str = "ubuntu"
    new_password: str


def _tenant_or_404(db: Session, tenant_id: int):
    return db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()


def _row_out(row: models.ConsoleConnection) -> dict:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "instance_id": row.instance_id,
        "instance_name": row.instance_name,
        "connection_ocid": row.connection_ocid,
        "region": row.region,
        "state": row.state,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("/connections", summary="创建串行控制台连接（真实 OCI 调用，后台等待 ACTIVE）")
def create_connection(
    body: ConsoleCreateIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if not body.instance_id.strip():
        return err(3103, "instance_id 不能为空", status=400)
    # 复用已存在的 ACTIVE 连接，避免重复创建
    existing = (
        db.query(models.ConsoleConnection)
        .filter(
            models.ConsoleConnection.tenant_id == body.tenant_id,
            models.ConsoleConnection.instance_id == body.instance_id,
            models.ConsoleConnection.state == "ACTIVE",
        )
        .order_by(models.ConsoleConnection.id.desc())
        .first()
    )
    if existing:
        return ok(_row_out(existing))
    try:
        return ok(
            console_service.create_console_connection(
                tenant, body.instance_id.strip(), body.instance_name, db
            )
        )
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("创建控制台连接未知异常 tenant_id=%s", body.tenant_id)
        return err(3100, f"创建控制台连接失败：{str(exc)[:200]}", status=500)


@router.get("/connections", summary="查询串行控制台连接")
def list_connections(
    tenant_id: int = Query(description="租户 ID（必填）"),
    instance_id: str | None = Query(default=None, description="实例 OCID（可选）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(models.ConsoleConnection).filter(models.ConsoleConnection.tenant_id == tenant_id)
    if instance_id:
        q = q.filter(models.ConsoleConnection.instance_id == instance_id)
    rows = q.order_by(models.ConsoleConnection.id.desc()).limit(50).all()
    return ok({"items": [_row_out(r) for r in rows]})


@router.delete("/connections/{conn_id}", summary="删除串行控制台连接")
def delete_connection(
    conn_id: int,
    tenant_id: int = Query(description="租户 ID（必填）"),
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tenant = _tenant_or_404(db, tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    row = (
        db.query(models.ConsoleConnection)
        .filter(models.ConsoleConnection.id == conn_id, models.ConsoleConnection.tenant_id == tenant_id)
        .first()
    )
    if row is None:
        return err(3004, "控制台连接不存在", status=404)
    try:
        result = console_service.delete_console_connection(tenant, row)
        db.delete(row)
        db.commit()
        return ok(result)
    except OciApiError as exc:
        return err(exc.code, exc.message, status=exc.http_status)
    except Exception as exc:
        log.exception("删除控制台连接未知异常 conn_id=%s", conn_id)
        return err(3100, f"删除控制台连接失败：{str(exc)[:200]}", status=500)


@router.post("/reset-password", summary="串口自动重置系统密码（GRUB 单用户，需硬重启实例）")
def reset_password(
    body: ResetPasswordIn,
    _user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """救砖：实例 SSH 进不去时，通过串口自动走 GRUB 单用户流程重置系统用户密码。

    后台线程执行（硬重启 → GRUB 改启动参数 → passwd → 重启），前端轮询任务。
    密码只在内存流转，不落库、不记日志。
    """
    tenant = _tenant_or_404(db, body.tenant_id)
    if tenant is None:
        return err(3004, "租户不存在", status=404)
    if not body.instance_id.strip():
        return err(3103, "instance_id 不能为空", status=400)
    username = (body.username or "").strip()
    if not username or not username.replace("_", "").replace("-", "").isalnum():
        return err(3103, "用户名不合法", status=400)
    if not body.new_password or len(body.new_password) < 6:
        return err(3103, "新密码至少 6 位", status=400)
    if len(body.new_password) > 128:
        return err(3103, "新密码过长", status=400)
    task_id = console_service.start_reset_password_task(
        tenant.id, body.instance_id.strip(), body.instance_name, username, body.new_password
    )
    try:
        from ..core.audit import write_log

        write_log(
            db,
            _user.id,
            "console.reset_password",
            f"串口自动重置系统密码（用户 {username}，实例 {body.instance_name or body.instance_id.strip()}）",
        )
    except Exception:
        pass
    return ok({"task_id": task_id})


@router.get("/reset-password/tasks/{task_id}", summary="查询串口改密码任务状态")
def get_reset_password_task(
    task_id: str,
    _user: models.User = Depends(get_current_user),
):
    task = console_service.get_reset_password_task(task_id)
    if task is None:
        return err(3004, "任务不存在或已过期", status=404)
    return ok(task)


def _check_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        from ..core.deps import decode_access_token

        return decode_access_token(token) is not None
    except Exception:
        return False
    try:
        from ..core.deps import decode_access_token

        return decode_access_token(token) is not None
    except Exception:
        return False


def _set_winsize(fd: int, cols: int, rows: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except Exception:
        pass


async def ws_console(websocket: WebSocket):
    """WebSocket <-> ssh 串口进程（pty）双向桥接。query: token, connection_id。"""
    params = websocket.query_params
    await websocket.accept()
    if not _check_token(params.get("token")):
        await websocket.send_text(json.dumps({"type": "error", "message": "未授权：登录已过期"}))
        await websocket.close(code=4401)
        return

    from ..db.session import SessionLocal

    db = SessionLocal()
    try:
        try:
            conn_id = int(params.get("connection_id") or 0)
        except ValueError:
            conn_id = 0
        row = db.query(models.ConsoleConnection).filter(models.ConsoleConnection.id == conn_id).first()
        if row is None or row.state != "ACTIVE":
            await websocket.send_text(
                json.dumps({"type": "error", "message": "控制台连接不存在或尚未就绪"})
            )
            await websocket.close(code=4404)
            return
        tenant = db.query(models.Tenant).filter(models.Tenant.id == row.tenant_id).first()
        if tenant is None:
            await websocket.send_text(json.dumps({"type": "error", "message": "租户不存在"}))
            await websocket.close(code=4404)
            return
        private_pem = oci_factory.decrypt_private_key(row.private_key_ciphertext)
        region = row.region or tenant.region
        connection_ocid = row.connection_ocid
        instance_id = row.instance_id
    finally:
        db.close()

    # 私钥落临时文件（600 权限），进程结束后删除
    key_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".pem", delete=False, dir="/tmp"
    )
    try:
        os.chmod(key_file.name, 0o600)
        key_file.write(private_pem)
        key_file.close()
        argv = console_service.build_ssh_argv(
            connection_ocid, instance_id, region, key_file.name
        )

        master, slave = pty.openpty()
        _set_winsize(slave, 120, 32)
        proc = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True
        )
        os.close(slave)
    except Exception as exc:
        await websocket.send_text(json.dumps({"type": "error", "message": f"启动串口进程失败：{exc}"}))
        await websocket.close(code=4500)
        try:
            os.unlink(key_file.name)
        except Exception:
            pass
        return

    stop = threading.Event()

    def reader():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def forward():
            try:
                while not stop.is_set():
                    try:
                        chunk = await asyncio.to_thread(os.read, master, 4096)
                    except OSError:
                        break
                    if not chunk:
                        break
                    await websocket.send_text(
                        json.dumps({"type": "output", "data": chunk.decode("utf-8", "replace")})
                    )
            finally:
                try:
                    await websocket.send_text(json.dumps({"type": "closed"}))
                except Exception:
                    pass

        try:
            loop.run_until_complete(forward())
        finally:
            loop.close()

    threading.Thread(target=reader, daemon=True).start()
    await websocket.send_text(
        json.dumps({"type": "output", "data": "\r\n✅ 串行控制台已连接（实例串口，不依赖实例网络）\r\n"})
    )
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get("type")
            if mtype == "input":
                try:
                    os.write(master, msg.get("data", "").encode("utf-8", "replace"))
                except OSError:
                    break
            elif mtype == "resize":
                _set_winsize(master, int(msg.get("cols") or 120), int(msg.get("rows") or 32))
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            os.close(master)
        except Exception:
            pass
        try:
            os.unlink(key_file.name)
        except Exception:
            pass
