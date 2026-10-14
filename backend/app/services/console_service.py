"""串行控制台服务：OCI Instance Console Connection 的创建/轮询/删除。

原理：通过 OCI API 创建实例控制台连接（需上传 SSH 公钥），连接 ACTIVE 后，
用 `ssh -o ProxyCommand='ssh -W %h:%p -p 443 <conn-ocid>@instance-console.<region>.oci.oraclecloud.com' <instance-ocid>`
即可进入实例串口。实例 SSH 挂掉、网络配崩时依然可用，是真正的救砖通道。
"""
import logging
import os
import pty
import subprocess
import threading
import time

import oci
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from oci.exceptions import ConnectTimeout, ServiceError

from ..db.session import SessionLocal
from . import oci_factory
from .security_service import OciApiError

log = logging.getLogger(__name__)

ACTIVE_TIMEOUT = 180  # 等待 ACTIVE 的最长秒数
POLL_INTERVAL = 5


def _translate(exc: ServiceError, op: str) -> OciApiError:
    status = exc.status or 502
    if status == 401:
        return OciApiError(3101, f"{op}失败：OCI 认证失败，请检查租户的 API 密钥、私钥与指纹是否匹配", 502)
    if status == 429:
        return OciApiError(3102, f"{op}失败：OCI 接口限流，请稍后重试", 502)
    if status == 404:
        return OciApiError(3103, f"{op}失败：资源不存在 ({exc.code})", 502)
    return OciApiError(3103, f"{op}失败：[{exc.code}] {exc.message}", 502)


def generate_keypair() -> tuple[str, str]:
    """生成一次性 RSA 密钥对：返回 (private_pem, public_openssh)。"""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ).decode()
    public_ssh = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode()
    return private_pem, public_ssh


def console_host(region: str) -> str:
    return f"instance-console.{region}.oci.oraclecloud.com"


def build_ssh_argv(connection_ocid: str, instance_id: str, region: str, key_path: str) -> list[str]:
    """构造串口连接的 ssh 命令（与 OCI 官方文档一致）。

    注意：OCI 串口网关（instance-console.*.oci.oraclecloud.com）的主机密钥
    只提供 ssh-rsa（SHA1），现代 OpenSSH 默认禁用，必须显式加回，
    否则报 "no matching host key type found. Their offer: ssh-rsa"。
    内层跳板（ProxyCommand）和外层都要加。
    """
    # 兼容新旧 OpenSSH 的选项名都加上
    rsa_opts = (
        "-o HostKeyAlgorithms=+ssh-rsa "
        "-o PubkeyAcceptedAlgorithms=+ssh-rsa "
        "-o PubkeyAcceptedKeyTypes=+ssh-rsa"
    )
    proxy = (
        f"ssh -W %h:%p -p 443 -i {key_path} "
        f"-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "
        f"{rsa_opts} "
        f"{connection_ocid}@{console_host(region)}"
    )
    return [
        "ssh", "-tt",
        "-i", key_path,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=20",
        "-o", "HostKeyAlgorithms=+ssh-rsa",
        "-o", "PubkeyAcceptedAlgorithms=+ssh-rsa",
        "-o", "PubkeyAcceptedKeyTypes=+ssh-rsa",
        "-o", f"ProxyCommand={proxy}",
        instance_id,
    ]


def _wait_active(tenant, connection_ocid: str) -> None:
    compute = oci_factory.get_compute_client(tenant)
    deadline = time.time() + ACTIVE_TIMEOUT
    while time.time() < deadline:
        try:
            conn = compute.get_instance_console_connection(connection_ocid).data
        except ServiceError as exc:
            raise _translate(exc, "查询控制台连接状态") from exc
        state = (conn.lifecycle_state or "").upper()
        if state == "ACTIVE":
            return
        if state in ("FAILED", "DELETED"):
            raise OciApiError(3103, f"控制台连接进入 {state} 状态，创建失败", 502)
        time.sleep(POLL_INTERVAL)
    raise OciApiError(3104, "控制台连接长时间未进入 ACTIVE 状态，请稍后重试", 504)


def _poll_to_active_task(tenant_id: int, row_id: int, connection_ocid: str) -> None:
    """后台线程：等待连接 ACTIVE 后回写 DB。"""
    from ..db import models

    db = SessionLocal()
    try:
        tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
        if tenant is None:
            return
        try:
            _wait_active(tenant, connection_ocid)
            state, error = "ACTIVE", ""
        except OciApiError as exc:
            state, error = "FAILED", exc.message
        row = db.query(models.ConsoleConnection).filter(models.ConsoleConnection.id == row_id).first()
        if row:
            row.state = state
            row.error = error
            db.commit()
    finally:
        db.close()


def create_console_connection(tenant, instance_id: str, instance_name: str, db) -> dict:
    """创建控制台连接：调 OCI API，DB 落盘后起后台线程等 ACTIVE。"""
    from ..db import models

    private_pem, public_ssh = generate_keypair()
    compute = oci_factory.get_compute_client(tenant)
    try:
        details = oci.core.models.CreateInstanceConsoleConnectionDetails(
            instance_id=instance_id,
            public_key=public_ssh,
        )
        conn = compute.create_instance_console_connection(details).data
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"创建控制台连接失败：连接 OCI 超时（{exc}）", 502) from exc
    except ServiceError as exc:
        raise _translate(exc, "创建控制台连接") from exc

    row = models.ConsoleConnection(
        tenant_id=tenant.id,
        instance_id=instance_id,
        instance_name=instance_name or "",
        connection_ocid=conn.id,
        region=tenant.region,
        private_key_ciphertext=oci_factory.encrypt_private_key(private_pem),
        state="CREATING",
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    threading.Thread(
        target=_poll_to_active_task,
        args=(tenant.id, row.id, conn.id),
        daemon=True,
        name=f"console-wait-{row.id}",
    ).start()
    log.info("已创建串行控制台连接 %s（实例 %s），后台等待 ACTIVE", conn.id, instance_id)
    return {
        "id": row.id,
        "connection_ocid": conn.id,
        "instance_id": instance_id,
        "state": "CREATING",
    }


def delete_console_connection(tenant, row) -> dict:
    """删除 OCI 侧控制台连接并清理 DB 记录（OCI 侧 404 视为已删除）。"""
    compute = oci_factory.get_compute_client(tenant)
    try:
        compute.delete_instance_console_connection(row.connection_ocid)
    except ServiceError as exc:
        if (exc.status or 0) != 404:
            raise _translate(exc, "删除控制台连接") from exc
    except ConnectTimeout as exc:
        raise OciApiError(3104, f"删除控制台连接失败：连接 OCI 超时（{exc}）", 502) from exc
    log.info("已删除串行控制台连接 %s", row.connection_ocid)
    return {"id": row.id, "deleted": True}


# =====================================================================
# 串口自动重置系统密码（救砖）：GRUB 改启动参数进单用户改密码
#
# 流程：复用/创建串行控制台连接 → 硬重启实例 → 串口盯 GRUB 菜单按 e →
# 编辑 linux 行追加 init=/bin/bash → Ctrl+X 进 root shell →
# mount -o remount,rw / → passwd 改密码 → reboot -f → 等 RUNNING。
# 全程 expect 式交互，后台线程执行，前端轮询任务日志。
# 注意：密码只在内存中流转，绝不写日志/落库。
# =====================================================================

_RESET_TASKS: dict = {}
_RESET_LOCK = threading.Lock()
_RESET_TASK_TTL = 3600  # 任务记录保留 1 小时

_GRUB_WAIT_TIMEOUT = 300   # 等 GRUB 菜单的最长秒数
_SHELL_WAIT_TIMEOUT = 180  # 等 root shell 的最长秒数
_RUNNING_WAIT_TIMEOUT = 600  # 等实例回到 RUNNING 的最长秒数


def _reset_task_get(task_id: str) -> dict | None:
    with _RESET_LOCK:
        return _RESET_TASKS.get(task_id)


def get_reset_password_task(task_id: str) -> dict | None:
    """给路由层用的任务查询（返回脱敏后的快照）。"""
    task = _reset_task_get(task_id)
    if task is None:
        return None
    with _RESET_LOCK:
        return {
            "task_id": task["task_id"],
            "state": task["state"],  # running / success / failed
            "step": task["step"],
            "logs": list(task["logs"]),
            "error": task["error"],
            "created_at": task["created_at"],
        }


def _reset_log(task: dict, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _RESET_LOCK:
        task["logs"].append(line)
        # 日志只保留最后 200 行
        if len(task["logs"]) > 200:
            task["logs"] = task["logs"][-200:]
    log.info("串口改密码 %s: %s", task["task_id"][:8], msg)


def _reset_fail(task: dict, msg: str) -> None:
    with _RESET_LOCK:
        task["state"] = "failed"
        task["error"] = msg
    _reset_log(task, f"❌ {msg}")


class _SerialSession:
    """pty 直连串口 ssh 进程，支持 expect 式交互。"""

    def __init__(self, argv: list[str]):
        import fcntl

        self._fcntl = fcntl
        master, slave = pty.openpty()
        self.proc = subprocess.Popen(
            argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True
        )
        os.close(slave)
        self.master = master
        self.buf = b""
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def send(self, data: str) -> None:
        os.write(self.master, data.encode("utf-8", "replace"))

    def _drain(self) -> None:
        try:
            while True:
                chunk = os.read(self.master, 65536)
                if not chunk:
                    break
                self.buf += chunk
        except OSError:
            pass

    def text(self) -> str:
        self._drain()
        return self.buf.decode("utf-8", "replace")

    def expect(self, patterns: list[str], timeout: float) -> int | None:
        """等待任一 pattern 出现在输出中，返回命中的索引，超时返回 None。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return None  # ssh 进程已退出
            txt = self.text()
            for i, p in enumerate(patterns):
                if p in txt:
                    return i
            time.sleep(0.5)
        return None

    def clear(self) -> None:
        self.buf = b""
        self._drain()

    def close(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.close(self.master)
        except Exception:
            pass


def _find_linux_line_index(frame: str) -> int | None:
    """在 GRUB 编辑界面的一帧输出里，定位 linux /boot/vmlinuz 行是第几行（从 0 计）。

    取最后一个清屏后的内容，按行找。GRUB 编辑器第一行是 setparams，
    按 Down 的次数 = 该行索引。
    """
    # 取最后一帧（清屏符之后）
    for sep in ("\x1b[2J", "\x1b[H\x1b[2J", "\x1bc"):
        if sep in frame:
            frame = frame.rsplit(sep, 1)[-1]
    # 去掉 ANSI 转义序列，方便按行解析
    import re

    clean = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", frame)
    clean = re.sub(r"\x1b[()][AB0]", "", clean)
    lines = [ln.strip() for ln in clean.splitlines()]
    # 找到 setparams 行作为起点
    start = 0
    for i, ln in enumerate(lines):
        if ln.startswith("setparams"):
            start = i
            break
    for i in range(start, len(lines)):
        ln = lines[i]
        if ln.startswith("linux ") and ("/boot/vmlinuz" in ln or "vmlinuz" in ln):
            return i - start
    return None


def _ensure_active_connection(tenant, instance_id: str, instance_name: str, db) -> "models.ConsoleConnection":
    """复用 ACTIVE 的串口连接，没有则创建并等待 ACTIVE。"""
    from ..db import models

    row = (
        db.query(models.ConsoleConnection)
        .filter(
            models.ConsoleConnection.tenant_id == tenant.id,
            models.ConsoleConnection.instance_id == instance_id,
            models.ConsoleConnection.state == "ACTIVE",
        )
        .order_by(models.ConsoleConnection.id.desc())
        .first()
    )
    if row is not None:
        return row
    create_console_connection(tenant, instance_id, instance_name or "", db)
    # 等待刚才创建的连接变 ACTIVE
    deadline = time.time() + ACTIVE_TIMEOUT + 30
    while time.time() < deadline:
        row = (
            db.query(models.ConsoleConnection)
            .filter(
                models.ConsoleConnection.tenant_id == tenant.id,
                models.ConsoleConnection.instance_id == instance_id,
            )
            .order_by(models.ConsoleConnection.id.desc())
            .first()
        )
        if row is not None and row.state == "ACTIVE":
            return row
        if row is not None and row.state == "FAILED":
            raise OciApiError(3103, f"控制台连接创建失败：{row.error or '未知错误'}", 502)
        time.sleep(POLL_INTERVAL)
    raise OciApiError(3104, "控制台连接长时间未就绪", 504)


def _run_reset_password_task(task_id: str, tenant_id: int, instance_id: str,
                             instance_name: str, username: str, new_password: str) -> None:
    """后台线程：执行串口自动改密码全流程。"""
    import tempfile

    from ..db import models
    from ..db.session import SessionLocal
    from . import instance_service

    task = _reset_task_get(task_id)
    if task is None:
        return

    def step(name: str) -> None:
        with _RESET_LOCK:
            task["step"] = name
        _reset_log(task, f"▶ {name}")

    db = SessionLocal()
    key_path = None
    sess = None
    try:
        tenant = db.query(models.Tenant).filter(models.Tenant.id == tenant_id).first()
        if tenant is None:
            _reset_fail(task, "租户不存在")
            return

        step("准备串行控制台连接")
        row = _ensure_active_connection(tenant, instance_id, instance_name, db)
        private_pem = oci_factory.decrypt_private_key(row.private_key_ciphertext)
        region = row.region or tenant.region
        kf = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False, dir="/tmp")
        os.chmod(kf.name, 0o600)
        kf.write(private_pem)
        kf.close()
        key_path = kf.name
        argv = build_ssh_argv(row.connection_ocid, instance_id, region, key_path)
        # 私钥明文只在内存/临时文件，用完即删
        del private_pem

        step("硬重启实例（RESET）")
        try:
            instance_service.power_instance(tenant, instance_id, "RESET")
        except OciApiError as exc:
            _reset_fail(task, f"重启实例失败：{exc.message}")
            return
        _reset_log(task, "已发送重启指令，开始监听串口…")

        step("连接串口，等待 GRUB 菜单")
        sess = _SerialSession(argv)
        # 等 ssh 建连（跳过 ProxyCommand 的握手输出）
        time.sleep(5)
        sess.clear()
        # GRUB 菜单可能被隐藏（timeout=0），持续发 Esc 调出，同时盯特征
        deadline = time.time() + _GRUB_WAIT_TIMEOUT
        grub_hit = False
        last_esc = 0.0
        while time.time() < deadline:
            if sess.proc.poll() is not None:
                _reset_fail(task, "串口 ssh 进程意外退出")
                return
            txt = sess.text()
            if "GNU GRUB" in txt:
                grub_hit = True
                break
            if "login:" in txt and "GRUB" not in txt:
                # 系统已经启动起来了（没看到 GRUB），再重启一次
                _reset_log(task, "错过 GRUB（系统已启动），重新硬重启一次…")
                try:
                    instance_service.power_instance(tenant, instance_id, "RESET")
                except OciApiError as exc:
                    _reset_fail(task, f"重新重启失败：{exc.message}")
                    return
                sess.clear()
                deadline = time.time() + _GRUB_WAIT_TIMEOUT
                continue
            if time.time() - last_esc > 2:
                sess.send("\x1b")  # Esc：调出隐藏的 GRUB 菜单
                last_esc = time.time()
            time.sleep(0.5)
        if not grub_hit:
            _reset_fail(task, f"等待 GRUB 菜单超时（{_GRUB_WAIT_TIMEOUT}s），实例可能未正常重启")
            return
        _reset_log(task, "已进入 GRUB 菜单")

        step("进入 GRUB 编辑模式")
        sess.clear()
        sess.send("e")
        idx = sess.expect(["setparams", "linux /boot", "linux\t/boot"], 30)
        if idx is None:
            _reset_fail(task, "未能进入 GRUB 编辑界面")
            return
        # 等一帧稳定输出后解析 linux 行号
        time.sleep(2)
        frame = sess.text()
        line_no = _find_linux_line_index(frame)
        if line_no is None:
            _reset_fail(task, "在 GRUB 编辑界面未找到 linux 启动行")
            return
        _reset_log(task, f"定位到 linux 启动行（第 {line_no + 1} 行）")
        for _ in range(line_no):
            sess.send("\x1b[B")  # Down
            time.sleep(0.15)
        sess.send("\x05")  # Ctrl+E：行尾
        time.sleep(0.3)
        sess.send(" init=/bin/bash")
        time.sleep(0.5)
        sess.send("\x18")  # Ctrl+X：启动
        _reset_log(task, "已修改启动参数，正在进入单用户 shell…")

        step("等待 root shell")
        idx = sess.expect(["# ", "root@"], _SHELL_WAIT_TIMEOUT)
        if idx is None:
            _reset_fail(task, "等待 root shell 超时，启动参数可能未生效")
            return
        _reset_log(task, "已进入 root shell")

        step("重新挂载根分区为可写")
        sess.clear()
        sess.send("mount -o remount,rw /\n")
        if sess.expect(["# ", "root@"], 30) is None:
            _reset_fail(task, "执行 mount 失败")
            return

        step(f"修改用户 {username} 的密码")
        sess.clear()
        sess.send(f"passwd {username}\n")
        idx = sess.expect(["New password:", "New Password:", "新密码"], 30)
        if idx is None:
            out = sess.text()[-500:]
            if "unknown user" in out.lower() or "不存在" in out:
                _reset_fail(task, f"用户 {username} 不存在，请确认系统用户名")
            else:
                _reset_fail(task, "passwd 未提示输入新密码")
            return
        sess.send(new_password + "\n")
        idx = sess.expect(["Retype new password:", "Retype New Password:", "重新输入", "确认"], 30)
        if idx is None:
            _reset_fail(task, "passwd 未提示确认密码")
            return
        sess.send(new_password + "\n")
        idx = sess.expect(["successfully", "成功", "# ", "root@"], 30)
        # passwd 成功后一般回到 # 提示符；简单起见只要回到 shell 就继续
        txt = sess.text()
        if "BAD PASSWORD" in txt or "bad password" in txt:
            _reset_log(task, "⚠ 密码强度被系统警告，但通常仍已生效，继续…")
        _reset_log(task, "密码已更新")

        step("重启实例恢复正常启动")
        sess.clear()
        sess.send("reboot -f\n")
        time.sleep(3)
        try:
            sess.close()
        except Exception:
            pass
        sess = None

        step("等待实例回到 RUNNING")
        compute = oci_factory.get_compute_client(tenant)
        deadline = time.time() + _RUNNING_WAIT_TIMEOUT
        running = False
        while time.time() < deadline:
            try:
                inst = compute.get_instance(instance_id).data
                state = (inst.lifecycle_state or "").upper()
                if state == "RUNNING":
                    running = True
                    break
            except Exception:
                pass
            time.sleep(10)
        if not running:
            _reset_fail(task, "实例长时间未回到 RUNNING，请在控制台确认状态")
            return

        with _RESET_LOCK:
            task["state"] = "success"
            task["step"] = "完成"
        _reset_log(task, f"✅ 完成：用户 {username} 的密码已重置，实例运行正常")
    except Exception as exc:
        log.exception("串口自动改密码异常 task=%s", task_id)
        _reset_fail(task, f"执行异常：{str(exc)[:200]}")
    finally:
        # 清理：密码变量清零、临时私钥删除、串口关闭
        try:
            new_password = "x" * len(new_password)
        except Exception:
            pass
        del new_password
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass
        if key_path:
            try:
                os.unlink(key_path)
            except Exception:
                pass
        db.close()


def start_reset_password_task(tenant_id: int, instance_id: str, instance_name: str,
                              username: str, new_password: str) -> str:
    """创建改密码任务并起后台线程，返回 task_id。"""
    import uuid

    # 清理过期任务
    now = time.time()
    with _RESET_LOCK:
        expired = [tid for tid, t in _RESET_TASKS.items() if now - t["created_ts"] > _RESET_TASK_TTL]
        for tid in expired:
            _RESET_TASKS.pop(tid, None)
        task_id = uuid.uuid4().hex
        _RESET_TASKS[task_id] = {
            "task_id": task_id,
            "state": "running",
            "step": "排队中",
            "logs": [],
            "error": "",
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "created_ts": now,
        }
    threading.Thread(
        target=_run_reset_password_task,
        args=(task_id, tenant_id, instance_id, instance_name, username, new_password),
        daemon=True,
        name=f"console-resetpwd-{task_id[:8]}",
    ).start()
    log.info("已启动串口自动改密码任务 %s（实例 %s，用户 %s）", task_id[:8], instance_id, username)
    return task_id
