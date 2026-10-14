"""换 IP worker：真实 OCI 公网 IP 更换。

设计：
- APScheduler 每 30s 调用 run_ip_tasks()
- 每次扫描 status=running 且未到下次尝试时间的任务，逐个执行
- 单次执行：取主 VNIC -> 旧公网 IP 记录并删除 -> 创建新临时公网 IP
  -> 按 preferred_cidrs 偏好检查，未命中则删除重建（attempts < max_retries）
- 429 -> 冷却 120s；超时 -> 下轮重试；400/404 -> failed 人工介入
- update_dns=True 时：本地 dns_records 中 content == old_ip 的 A 记录更新为
  new_ip，Cloudflare 远端同步为 best-effort（模块不存在也不影响主流程）
- 所有状态落库，服务重启后自动续跑
"""
import asyncio
import ipaddress
import json
import logging
from datetime import datetime, timedelta

import oci
from oci.exceptions import ConnectTimeout, RequestException, ServiceError

from ..db import models
from ..db.session import SessionLocal
from ..services import oci_factory

log = logging.getLogger(__name__)

# 429 后的冷却秒数
RATE_LIMIT_COOLDOWN_SEC = 120
# CIDR 未命中重试的间隔秒数
CIDR_RETRY_SLEEP_SEC = 3


def _now() -> datetime:
    return datetime.now()


def _cidr_hit(ip: str, preferred: list[str]) -> bool:
    """新 IP 是否落在任一偏好网段内；未设置偏好视为命中。"""
    if not preferred:
        return True
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in preferred:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def _get_main_private_ip(compute, network, instance_id: str) -> tuple[str, str]:
    """返回 (实例所在 compartment_id, 主 private_ip_id)。

    先 get_instance 取 compartment，再列 VNIC 附件找主 VNIC（nic_index=0 优先），
    最后在该 VNIC 下找主 private IP。
    """
    instance = compute.get_instance(instance_id).data
    compartment_id = instance.compartment_id
    attachments = compute.list_vnic_attachments(compartment_id, instance_id=instance_id).data
    attached = [a for a in attachments if getattr(a, "lifecycle_state", "") == "ATTACHED"]
    if not attached:
        raise ValueError("实例没有已挂载的 VNIC")
    primary = next((a for a in attached if getattr(a, "nic_index", None) == 0), attached[0])
    vnic_id = primary.vnic_id

    private_ips = network.list_private_ips(vnic_id=vnic_id).data
    primaries = [p for p in private_ips if getattr(p, "is_primary", False)]
    if not primaries:
        raise ValueError("主 VNIC 下没有主 private IP")
    return compartment_id, primaries[0].id


def _get_public_ip_by_private_ip(network, private_ip_id: str):
    """按 private_ip_id 查公网 IP；404 视为无公网 IP，返回 None。"""
    details = oci.core.models.GetPublicIpByPrivateIpIdDetails(private_ip_id=private_ip_id)
    try:
        return network.get_public_ip_by_private_ip_id(details).data
    except ServiceError as exc:
        if exc.status == 404:
            return None
        raise


def _classify_error(exc: ServiceError) -> tuple[str, str]:
    """错误分类 -> (处置, 原因描述)。

    处置：retry=下轮继续 / cooldown=429 冷却 / fail=转 failed 人工介入
    """
    status = exc.status or 0
    code = (exc.code or "").lower()
    msg = exc.message or ""
    if status == 429 or "toomanyrequests" in code or "rate" in code:
        return "cooldown", f"触发 OCI 频控，已冷却 {RATE_LIMIT_COOLDOWN_SEC}s"
    if status == 404:
        return "fail", f"资源不存在：[{exc.code}] {msg[:200]}"
    if status == 400 or "invalid" in code or "notauthorized" in code or "incorrect" in code:
        return "fail", f"参数/权限错误：[{exc.code}] {msg[:200]}"
    if status in (500, 502, 503):
        return "retry", f"OCI 服务端异常({status})：[{exc.code}] {msg[:150]}"
    return "retry", f"[{exc.code}] {msg[:200]}"


def _mark(db, task: models.IpTask, **fields) -> None:
    for key, value in fields.items():
        setattr(task, key, value)
    db.commit()


def _fail(db, task: models.IpTask, reason: str) -> None:
    _mark(db, task, status="failed", last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}")
    log.warning("换 IP 任务 %s 失败: %s", task.id, reason)


def _sync_dns(db, task: models.IpTask, new_ip: str) -> None:
    """DNS 联动：本地 dns_records 中 content == old_ip 的 A 记录更新为 new_ip。

    Cloudflare 远端同步为 best-effort：模块不存在或调用失败只记日志。
    """
    old_ip = task.old_ip
    if not old_ip:
        log.info("换 IP 任务 %s 无旧 IP，跳过 DNS 联动", task.id)
        return
    records = (
        db.query(models.DnsRecord)
        .filter(models.DnsRecord.type == "A", models.DnsRecord.content == old_ip)
        .all()
    )
    for r in records:
        r.content = new_ip
    db.commit()
    log.info("换 IP 任务 %s 本地 DNS 更新 %d 条: %s -> %s", task.id, len(records), old_ip, new_ip)

    # Cloudflare 远端同步（模块可能尚不存在）
    for r in records:
        try:
            from ..services.cloudflare_service import sync_record_to_cloudflare

            sync_record_to_cloudflare(db, r)
        except Exception as exc:  # noqa: BLE001  best-effort，不影响主流程
            log.warning("换 IP 任务 %s DNS %s 同步 Cloudflare 失败: %s", task.id, r.name, exc)
    _mark(db, task, dns_updated=True)


async def execute_change_ip(task_id: int) -> None:
    """单次换 IP 执行（真实 OCI 调用）。"""
    db = SessionLocal()
    try:
        task = db.get(models.IpTask, task_id)
        if task is None or task.status != "running":
            return
        tenant = db.get(models.Tenant, task.tenant_id)
        if tenant is None:
            _fail(db, task, "关联的租户配置已被删除")
            return

        preferred = json.loads(task.preferred_cidrs or "[]")

        try:
            compute = oci_factory.get_compute_client(tenant)
            network = oci_factory.get_network_client(tenant)
        except ValueError as exc:
            _fail(db, task, f"租户配置异常：{exc}")
            return

        # 1. 主 VNIC / 主 private IP
        try:
            compartment_id, private_ip_id = _get_main_private_ip(compute, network, task.instance_id)
        except ServiceError as exc:
            action, reason = _classify_error(exc)
            if action == "fail":
                _fail(db, task, reason)
            else:
                _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}")
            return
        except ValueError as exc:
            _fail(db, task, str(exc))
            return

        # 2. 查旧公网 IP 并删除
        try:
            old_pub = _get_public_ip_by_private_ip(network, private_ip_id)
            if old_pub is not None:
                _mark(db, task, old_ip=old_pub.ip_address)
                try:
                    network.delete_public_ip(old_pub.id)
                except ServiceError as exc:
                    if exc.status != 404:  # 已被删掉视为成功
                        raise
                log.info("换 IP 任务 %s 删除旧公网 IP %s", task_id, old_pub.ip_address)
            else:
                log.info("换 IP 任务 %s 实例当前无公网 IP，直接创建新 IP", task_id)
        except ServiceError as exc:
            action, reason = _classify_error(exc)
            if action == "cooldown":
                _mark(
                    db, task,
                    last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}",
                    next_attempt_at=_now() + timedelta(seconds=RATE_LIMIT_COOLDOWN_SEC),
                )
            elif action == "fail":
                _fail(db, task, reason)
            else:
                _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}")
            return
        except (ConnectTimeout, RequestException) as exc:
            _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] 连接 OCI 超时：{exc}")
            return

        # 3. 创建新公网 IP，CIDR 偏好未命中则删除重建
        new_ip = None
        new_pub_id = None
        cidr_failed = False
        try:
            while True:
                details = oci.core.models.CreatePublicIpDetails(
                    compartment_id=compartment_id,
                    lifetime="EPHEMERAL",
                    private_ip_id=private_ip_id,
                    display_name=f"oci-panel-ip-{task_id}-{task.attempts + 1}",
                )
                created = network.create_public_ip(details).data
                new_ip, new_pub_id = created.ip_address, created.id
                task.attempts += 1
                db.commit()
                log.info("换 IP 任务 %s 创建新公网 IP %s（第 %s 次）", task_id, new_ip, task.attempts)

                if _cidr_hit(new_ip, preferred):
                    break
                if task.attempts < task.max_retries:
                    log.info("换 IP 任务 %s %s 未命中偏好 %s，删除后重试", task_id, new_ip, preferred)
                    try:
                        network.delete_public_ip(new_pub_id)
                    except ServiceError:
                        log.exception("换 IP 任务 %s 删除未命中 IP 失败", task_id)
                    new_ip, new_pub_id = None, None
                    await asyncio.sleep(CIDR_RETRY_SLEEP_SEC)
                    continue
                cidr_failed = True
                break
        except ServiceError as exc:
            action, reason = _classify_error(exc)
            if action == "cooldown":
                _mark(
                    db, task,
                    last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}",
                    next_attempt_at=_now() + timedelta(seconds=RATE_LIMIT_COOLDOWN_SEC),
                )
            elif action == "fail":
                _fail(db, task, reason)
            else:
                _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] {reason}")
            return
        except (ConnectTimeout, RequestException) as exc:
            _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] 连接 OCI 超时：{exc}")
            return
        except Exception:  # 未知异常不杀死任务
            log.exception("换 IP 任务 %s 创建公网 IP 未知异常", task_id)
            _mark(db, task, last_error=f"[{_now():%m-%d %H:%M:%S}] 未知异常，已保留任务下轮重试")
            return

        # 4. 落库
        if cidr_failed:
            _mark(
                db, task,
                status="failed",
                new_ip=new_ip,
                next_attempt_at=None,
                last_error=(
                    f"[{_now():%m-%d %H:%M:%S}] {task.attempts} 次创建均未命中偏好 CIDR {preferred}，"
                    f"已保留当前 IP {new_ip}，可手动处理或重新发起"
                ),
            )
            log.warning("换 IP 任务 %s CIDR 偏好未命中，已保留 IP %s", task_id, new_ip)
            return

        _mark(db, task, status="success", new_ip=new_ip, next_attempt_at=None, last_error=None)
        log.info("换 IP 任务 %s 成功：%s -> %s", task_id, task.old_ip, new_ip)
        # 换 IP 成功通知（失败不影响主流程）
        try:
            from ..services.notification_service import send_to_all

            await asyncio.to_thread(
                send_to_all,
                title="🔁 换 IP 成功",
                body=f"实例 {task.instance_id} 公网 IP 已更换：{task.old_ip} -> {new_ip}",
            )
        except Exception:
            log.exception("换 IP 成功通知发送失败（任务 %s）", task_id)

        # 5. DNS 联动
        if task.update_dns:
            try:
                _sync_dns(db, task, new_ip)
            except Exception:
                log.exception("换 IP 任务 %s DNS 联动异常", task_id)
    finally:
        db.close()


async def run_ip_tasks() -> None:
    """定时入口：扫描 running 且未到冷却时间的换 IP 任务并执行。"""
    db = SessionLocal()
    try:
        now = _now()
        tasks = db.query(models.IpTask).filter(models.IpTask.status == "running").all()
        due = [t.id for t in tasks if not (t.next_attempt_at and t.next_attempt_at > now)]
    finally:
        db.close()

    for task_id in due:
        try:
            await execute_change_ip(task_id)
        except Exception:
            log.exception("换 IP 任务 %s 执行异常", task_id)
        await asyncio.sleep(2)
