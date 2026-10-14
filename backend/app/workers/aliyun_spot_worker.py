"""阿里云抢占式实例 worker：真实 ECS RunInstances 调用。

设计（对标 snatch_worker）：
- APScheduler 定时调用 poll_spot_tasks()（复用 snatch 扫描节拍 15s）
- 每次扫描 status=running 且未到下次尝试时间的任务，按任务自身 interval_sec 控制
- 单次尝试：run_spot_instance；成功 -> success；无库存/出价过低 -> 记录 last_error 继续
- 参数错误 -> failed 人工介入；所有状态落库，重启后自动续跑
"""
import asyncio
import json
import logging
import random
from datetime import datetime, timedelta

from ..db import models
from ..db.session import SessionLocal
from ..providers import get_provider
from ..providers.base import ProviderError

log = logging.getLogger(__name__)

RATE_LIMIT_COOLDOWN_SEC = 120


def _now() -> datetime:
    return datetime.now()


def _record_attempt(db, task, ok: bool, error: str = "", instance_id: str = "") -> None:
    task.attempts += 1
    task.last_attempt_at = _now()
    entry = {
        "time": _now().strftime("%Y-%m-%d %H:%M:%S"),
        "ok": ok,
        "error": error[:300] if error else "",
        "instance_id": instance_id,
    }
    try:
        logs = json.loads(task.recent_logs) if task.recent_logs else []
    except Exception:
        logs = []
    logs.append(entry)
    task.recent_logs = json.dumps(logs[-20:], ensure_ascii=False)
    if ok:
        task.status = "success"
        task.created_instance_id = instance_id
        task.last_error = None
    else:
        task.last_error = error[:500]
    db.commit()


def _missing_config(task: models.AliyunSpotTask) -> str | None:
    missing = []
    if not task.region_id:
        missing.append("region_id")
    if not task.instance_type:
        missing.append("instance_type")
    if not task.image_id:
        missing.append("image_id")
    if not task.vswitch_id:
        missing.append("vswitch_id")
    if not task.security_group_id:
        missing.append("security_group_id")
    if task.spot_strategy == "SpotWithPriceLimit" and not task.spot_price_limit:
        missing.append("spot_price_limit（限价策略必填）")
    return "、".join(missing) if missing else None


def _classify_error(exc: Exception) -> tuple[str, str]:
    """返回 (action, reason)：action = retry / fail / cooldown。"""
    msg = str(exc)
    # 无库存 / 出价相关 -> 继续重试
    retry_keys = ["Insufficient", "NoStock", "StockExhausted", "PriceTooLow",
                  "InvalidSpotPrice", "OperationDenied", "Throttling"]
    if any(k in msg for k in retry_keys):
        if "Throttling" in msg or "频控" in msg or "Request was denied due to request throttling" in msg:
            return "cooldown", f"触发阿里云频控，冷却 {RATE_LIMIT_COOLDOWN_SEC}s：{msg[:200]}"
        return "retry", f"暂不可用（无库存/出价/配额）：{msg[:200]}"
    # 参数错误 -> 人工介入
    fail_keys = ["InvalidParameter", "InvalidInstanceType", "InvalidImageId",
                 "InvalidVSwitchId", "InvalidSecurityGroupId", "Forbidden",
                 "Unauthorized", "InvalidAccessKeyId"]
    if any(k in msg for k in fail_keys):
        return "fail", f"参数/权限错误：{msg[:300]}"
    return "retry", f"调用失败：{msg[:200]}"


async def attempt_create(task_id: int) -> None:
    db = SessionLocal()
    try:
        task = db.get(models.AliyunSpotTask, task_id)
        if task is None or task.status != "running":
            return
        tenant = db.get(models.Tenant, task.tenant_id)
        if tenant is None:
            task.status = "failed"
            task.last_error = "关联的租户配置已被删除"
            db.commit()
            return
        if (getattr(tenant, "provider", None) or "") != "aliyun":
            task.status = "failed"
            task.last_error = "关联租户不是阿里云账号"
            db.commit()
            return

        missing = _missing_config(task)
        if missing:
            task.status = "failed"
            task.last_error = f"任务配置缺失：{missing}，请编辑任务补全后重新启动"
            db.commit()
            log.warning("抢占式任务 %s 配置缺失已转 failed: %s", task_id, missing)
            return

        try:
            provider = get_provider(tenant)
        except ProviderError as exc:
            _record_attempt(db, task, ok=False, error=f"租户配置异常：{exc.message}")
            return

        spec = {
            "region_id": task.region_id,
            "zone_id": task.zone_id,
            "instance_type": task.instance_type,
            "image_id": task.image_id,
            "vswitch_id": task.vswitch_id,
            "security_group_id": task.security_group_id,
            "spot_strategy": task.spot_strategy,
            "spot_price_limit": task.spot_price_limit or "",
            "system_disk_category": task.system_disk_category,
            "system_disk_size": task.system_disk_size,
            "bandwidth_out": task.bandwidth_out,
            "instance_name": task.instance_name or f"panel-spot-{task_id}",
        }
        try:
            # RunInstances 是同步 HTTP 调用，丢到线程池避免阻塞事件循环
            result = await asyncio.to_thread(provider.run_spot_instance, spec)
        except Exception as exc:
            action, reason = _classify_error(exc)
            if action == "fail":
                task.status = "failed"
                task.last_error = reason
                task.attempts += 1
                task.last_attempt_at = _now()
                db.commit()
                log.warning("抢占式任务 %s 参数错误转 failed: %s", task_id, reason)
            elif action == "cooldown":
                _record_attempt(db, task, ok=False, error=reason)
                task.next_attempt_at = _now() + timedelta(seconds=RATE_LIMIT_COOLDOWN_SEC)
                db.commit()
            else:
                _record_attempt(db, task, ok=False, error=reason)
            return

        ids = result.get("instance_ids", [])
        instance_id = ids[0] if ids else ""
        _record_attempt(db, task, ok=True, instance_id=instance_id)
        log.info("抢占式任务 %s 成功！实例 %s", task_id, instance_id)
    finally:
        db.close()


async def poll_spot_tasks() -> None:
    """定时入口：扫描 running 的抢占式任务，按各自间隔尝试创建。"""
    db = SessionLocal()
    try:
        now = _now()
        tasks = db.query(models.AliyunSpotTask).filter(models.AliyunSpotTask.status == "running").all()
        due: list[int] = []
        for t in tasks:
            if t.next_attempt_at and t.next_attempt_at > now:
                continue
            if t.last_attempt_at:
                elapsed = (now - t.last_attempt_at).total_seconds()
                if elapsed < max(10, t.interval_sec or 60):
                    continue
            due.append(t.id)
    finally:
        db.close()

    for task_id in due:
        try:
            await attempt_create(task_id)
        except Exception:
            log.exception("抢占式任务 %s 执行异常", task_id)
        await asyncio.sleep(random.uniform(1.5, 4.0))
