"""Web SSH 终端：websocket <-> paramiko 双向桥接（Cloud Shell 风格）。

协议（JSON 文本帧）：
- C -> S {"type": "connect", "host": str, "port": int, "username": str,
           "auth_type": "password"|"key", "credential": str}
- C -> S {"type": "input", "data": str}
- C -> S {"type": "resize", "cols": int, "rows": int}
- S -> C {"type": "output", "data": str}
- S -> C {"type": "error", "message": str}
- S -> C {"type": "closed"}

鉴权：连接时 query 传 token=JWT，与 HTTP 接口同一套登录态。
"""
import asyncio
import io
import json
import logging
import threading

from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)


def _check_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        from ..core.deps import decode_access_token

        return decode_access_token(token) is not None
    except Exception:
        return False


async def ws_terminal(websocket: WebSocket):
    token = websocket.query_params.get("token")
    await websocket.accept()
    if not _check_token(token):
        await websocket.send_text(json.dumps({"type": "error", "message": "未授权：登录已过期"}))
        await websocket.close(code=4401)
        return

    import paramiko

    ssh: paramiko.SSHClient | None = None
    channel = None
    stop = threading.Event()

    def reader():
        """后台线程：SSH channel -> websocket。"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def forward():
            while not stop.is_set() and channel is not None:
                try:
                    if channel.recv_ready():
                        data = channel.recv(4096)
                        if not data:
                            break
                        await websocket.send_text(
                            json.dumps({"type": "output", "data": data.decode("utf-8", "replace")})
                        )
                    else:
                        await asyncio.sleep(0.02)
                except Exception:
                    break
            try:
                await websocket.send_text(json.dumps({"type": "closed"}))
            except Exception:
                pass

        try:
            loop.run_until_complete(forward())
        finally:
            loop.close()

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            mtype = msg.get("type")

            if mtype == "connect":
                host = (msg.get("host") or "").strip()
                port = int(msg.get("port") or 22)
                username = (msg.get("username") or "").strip()
                auth_type = msg.get("auth_type") or "password"
                credential = msg.get("credential") or ""
                if not host or not username or not credential:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": "host/用户名/凭证不能为空"})
                    )
                    continue
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    kwargs: dict = {
                        "hostname": host, "port": port, "username": username,
                        "timeout": 15, "banner_timeout": 15, "auth_timeout": 15,
                    }
                    if auth_type == "key":
                        kwargs["pkey"] = paramiko.RSAKey.from_private_key(io.StringIO(credential))
                    else:
                        kwargs["password"] = credential
                    await asyncio.to_thread(ssh.connect, **kwargs)
                    channel = ssh.invoke_shell(term="xterm-256color", width=120, height=32)
                    channel.settimeout(0.0)
                    threading.Thread(target=reader, daemon=True).start()
                    await websocket.send_text(
                        json.dumps({"type": "output", "data": f"\r\n✅ 已连接到 {username}@{host}:{port}\r\n"})
                    )
                except Exception as exc:
                    await websocket.send_text(
                        json.dumps({"type": "error", "message": f"SSH 连接失败：{str(exc)[:200]}"})
                    )
            elif mtype == "input":
                if channel is not None:
                    try:
                        await asyncio.to_thread(channel.send, msg.get("data", ""))
                    except Exception:
                        pass
            elif mtype == "resize":
                if channel is not None:
                    try:
                        channel.resize_pty(
                            width=int(msg.get("cols") or 120), height=int(msg.get("rows") or 32)
                        )
                    except Exception:
                        pass
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        try:
            if channel is not None:
                channel.close()
        except Exception:
            pass
        try:
            if ssh is not None:
                ssh.close()
        except Exception:
            pass
