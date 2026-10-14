"""抢机 worker：真实 OCI 创建调用。

设计：
- APScheduler 定时调用 poll_snatch_tasks()（默认 15s）
- 每次扫描 status=running 且未到下次尝试时间的任务，按任务自身的
  interval_sec 做间隔控制（last_attempt_at），避免不同任务互相干扰
- 单次尝试：launch_instance；成功 -> success；无货/频控 -> 记录
  last_error 并按策略退避；参数错误 -> failed 人工介入
- 所有状态落库，服务重启后自动续跑（断点续抢）
- 429 退避：next_attempt_at = now + 120s，避免持续轰炸被封
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta

import oci
from oci.exceptions import ConnectTimeout, RequestException, ServiceError

from ..db import models
from ..db.session import SessionLocal
from ..services import oci_factory

log = logging.getLogger(__name__)

# 429 后的冷却秒数
RATE_LIMIT_COOLDOWN_SEC = 120


def _now() -> datetime:
    return datetime.now()


def _missing_config(task: models.SnatchTask) -> str | None:
    """检查创建实例的必填配置，返回缺失项描述（无缺失返回 None）。"""
    missing = []
    if not task.compartment_id:
        missing.append("compartment_id")
    # 启动源二选一：镜像 或 现有引导卷
    if not getattr(task, "boot_volume_id", "") and not task.image_id:
        missing.append("image_id / boot_volume_id（二选一）")
    if not task.subnet_id:
        missing.append("subnet_id")
    if not task.availability_domain:
        missing.append("availability_domain")
    if "Flex" in (task.shape or "") and (task.ocpus is None or task.memory_in_gbs is None):
        missing.append("ocpus/memory_in_gbs（Flex 机型必填）")
    return "、".join(missing) if missing else None


def _pick_availability_domain(task) -> str:
    """多 AD 轮询：按 attempts 取模轮选本次尝试的可用域。

    availability_domains 为空/JSON 非法时回退到单个 availability_domain。
    """
    raw = getattr(task, "availability_domains", None)
    if raw:
        try:
            ads = json.loads(raw)
            if isinstance(ads, list) and ads:
                ads = [a.strip() for a in ads if isinstance(a, str) and a.strip()]
                if ads:
                    return ads[(task.attempts or 0) % len(ads)]
        except (json.JSONDecodeError, TypeError):
            log.warning("抢机任务 %s 的 availability_domains 解析失败，回退单 AD", getattr(task, "id", "?"))
    return task.availability_domain


def _build_launch_details(task: models.SnatchTask) -> "oci.core.models.LaunchInstanceDetails":
    """由任务配置构建 OCI 创建实例参数。

    启动源二选一：boot_volume_id（现有引导卷，系统盘数据保留）优先，
    否则用 image_id 从镜像新建。
    """
    boot_volume_id = getattr(task, "boot_volume_id", "") or ""
    if boot_volume_id:
        source_details = oci.core.models.InstanceSourceViaBootVolumeDetails(
            boot_volume_id=boot_volume_id
        )
    else:
        source_details = oci.core.models.InstanceSourceViaImageDetails(image_id=task.image_id)
    vnic_details = oci.core.models.CreateVnicDetails(
        subnet_id=task.subnet_id,
        assign_public_ip=bool(task.assign_public_ip),
        display_name=(task.display_name or task.name)[:255],
    )
    kwargs: dict = {
        "availability_domain": _pick_availability_domain(task),
        "compartment_id": task.compartment_id,
        "display_name": (task.display_name or f"{task.name}-{task.attempts + 1}")[:255],
        "shape": task.shape,
        "source_details": source_details,
        "create_vnic_details": vnic_details,
    }
    # 镜像模式保留顶层 image_id 兼容旧版 SDK；引导卷模式不需要
    if not boot_volume_id:
        kwargs["image_id"] = task.image_id  # 兼容旧版 SDK；主要通过 source_details 传递
    if task.ocpus is not None and task.memory_in_gbs is not None:
        kwargs["shape_config"] = oci.core.models.LaunchInstanceShapeConfigDetails(
            ocpus=task.ocpus, memory_in_gbs=task.memory_in_gbs
        )
    if task.ssh_public_key:
        kwargs["metadata"] = {"ssh_authorized_keys": task.ssh_public_key}
    # 部分 SDK 版本 LaunchInstanceDetails 不接受 image_id 顶层参数，防御性剔除
    try:
        return oci.core.models.LaunchInstanceDetails(**kwargs)
    except TypeError:
        kwargs.pop("image_id", None)
        return oci.core.models.LaunchInstanceDetails(**kwargs)


def _classify_error(exc: ServiceError) -> tuple[str, str]:
    """错误分类 -> (处置, 原因描述)。

    处置：retry=下次继续 / cooldown=429 冷却 / fail=转 failed 人工介入
    """
    status = exc.status or 0
    code = (exc.code or "").lower()
    msg = exc.message or ""
    if status == 429 or "toomanyrequests" in code or "rate" in code:
        return "cooldown", f"触发 OCI 频控，已冷却 {RATE_LIMIT_COOLDOWN_SEC}s"
    if status == 400 or "invalid" in code or "notauthorized" in code or "incorrect" in code:
        return "fail", f"参数/权限错误：[{exc.code}] {msg[:200]}"
    if "outofcapacity" in code or "out of capacity" in msg.lower() or "hostcapacity" in code:
        return "retry", f"暂无库存：[{exc.code}] {msg[:150]}"
    if status in (500, 502, 503):
        return "retry", f"OCI 服务端异常({status})：[{exc.code}] {msg[:150]}"
    return "retry", f"[{exc.code}] {msg[:200]}"


def _record_attempt(db, task: models.SnatchTask, *, ok: bool, error: str = "", instance_id: str = "") -> None:
    now = _now()
    task.attempts += 1
    task.last_attempt_at = now
    if ok:
        task.status = "success"
        task.created_instance_id = instance_id
        task.last_error = None
        task.next_attempt_at = None
    else:
        task.last_error = f"[{now:%m-%d %H:%M:%S} 第{task.attempts}次] {error}"
        if task.max_attempts and task.attempts >= task.max_attempts:
            task.status = "failed"
            task.last_error += "；已达最大尝试次数"
        log_line = task.last_error
    if ok:
        log_line = f"[{now:%m-%d %H:%M:%S} 第{task.attempts}次] ✅ 抢机成功，实例 {instance_id[-12:]}"
    # 最近尝试日志（JSON 数组，只保留最近 20 条）
    try:
        logs = json.loads(task.recent_logs) if task.recent_logs else []
        if not isinstance(logs, list):
            logs = []
    except (json.JSONDecodeError, TypeError):
        logs = []
    logs.append(log_line)
    task.recent_logs = json.dumps(logs[-20:], ensure_ascii=False)
    db.commit()


async def attempt_create(task_id: int) -> None:
    """单次抢机尝试（真实 OCI 调用）。"""
    db = SessionLocal()
    try:
        task = db.get(models.SnatchTask, task_id)
        if task is None or task.status != "running":
            return
        tenant = db.get(models.Tenant, task.tenant_id)
        if tenant is None:
            task.status = "failed"
            task.last_error = "关联的租户配置已被删除"
            db.commit()
            return

        # 必填配置校验
        missing = _missing_config(task)
        if missing:
            task.status = "failed"
            task.last_error = f"任务配置缺失：{missing}，请编辑任务补全后重新启动"
            db.commit()
            log.warning("抢机任务 %s 配置缺失已转 failed: %s", task_id, missing)
            return

        try:
            compute = oci_factory.get_compute_client(tenant)
        except ValueError as exc:
            _record_attempt(db, task, ok=False, error=f"租户配置异常：{exc}")
            return

        details = _build_launch_details(task)
        try:
            resp = compute.launch_instance(details)
        except (ConnectTimeout, RequestException) as exc:
            _record_attempt(db, task, ok=False, error=f"连接 OCI 超时：{exc}")
            return
        except ServiceError as exc:
            action, reason = _classify_error(exc)
            if action == "fail":
                task.status = "failed"
                task.last_error = reason
                task.attempts += 1
                task.last_attempt_at = _now()
                db.commit()
                log.warning("抢机任务 %s 参数错误转 failed: %s", task_id, reason)
            elif action == "cooldown":
                _record_attempt(db, task, ok=False, error=reason)
                task.next_attempt_at = _now() + timedelta(seconds=RATE_LIMIT_COOLDOWN_SEC)
                db.commit()
                log.warning("抢机任务 %s 触发频控，冷却 %ss", task_id, RATE_LIMIT_COOLDOWN_SEC)
            else:
                _record_attempt(db, task, ok=False, error=reason)
            return
        except Exception as exc:  # 未知异常不杀死任务，只记录
            _record_attempt(db, task, ok=False, error=f"未知异常：{str(exc)[:200]}")
            log.exception("抢机任务 %s 未知异常", task_id)
            return

        instance_id = resp.data.id
        task_name, task_shape, task_attempts = task.name, task.shape, task.attempts
        _record_attempt(db, task, ok=True, instance_id=instance_id)
        log.info("抢机任务 %s 成功！实例 %s", task_id, instance_id)
        # 抢机成功通知（Telegram/邮件，失败不影响主流程）
        try:
            from ..services.notification_service import send_to_all

            await asyncio.to_thread(
                send_to_all,
                title="🎉 抢机成功",
                body=f"任务「{task_name}」已创建实例：{instance_id}\nShape：{task_shape}\n尝试次数：{task_attempts}",
            )
        except Exception:
            log.exception("抢机成功通知发送失败（任务 %s）", task_id)
    finally:
        db.close()


async def poll_snatch_tasks() -> None:
    """定时入口：扫描 running 任务，按各自间隔与退避时间尝试创建。"""
    db = SessionLocal()
    try:
        now = _now()
        tasks = db.query(models.SnatchTask).filter(models.SnatchTask.status == "running").all()
        due: list[int] = []
        for t in tasks:
            if t.next_attempt_at and t.next_attempt_at > now:
                continue  # 频控冷却中
            if t.last_attempt_at:
                elapsed = (now - t.last_attempt_at).total_seconds()
                if elapsed < max(5, t.interval_sec or 15):
                    continue  # 未到该任务的轮询间隔
            due.append(t.id)
    finally:
        db.close()

    for task_id in due:
        try:
            await attempt_create(task_id)
        except Exception:
            log.exception("抢机任务 %s 执行异常", task_id)
        # 任务之间随机抖动，避免固定节奏触发 OCI 频控
        await asyncio.sleep(random.uniform(1.5, 4.0))
