"""每日健康报告：聚合真实数据生成中文日报，通过通知渠道定时发送。

数据来源（全部真实，无 mock）：
- 实例总览：inspection_service.inspect_all() 的实时巡检结果（按租户分组的总数/运行中/已停止）
- 抢机任务：snatch_tasks 表按状态计数
- 换 IP：ip_tasks 表今日创建的任务按状态计数
- 巡检告警：inspect_all() 本次运行发现的 issues
数据不足的章节直接省略，不编造。
"""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..core.audit import write_log
from ..db import models
from ..db.session import SessionLocal
from . import inspection_service, notification_service

log = logging.getLogger(__name__)

TZ = ZoneInfo("Asia/Shanghai")
WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

KEY_ENABLED = "daily_report_enabled"
KEY_TIME = "daily_report_time"
KEY_LAST_SENT = "daily_report_last_sent"
DEFAULT_TIME = "08:00"


def _get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(models.SystemSetting, key)
    return (row.value if row and row.value else default).strip()


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(models.SystemSetting, key)
    if row is None:
        db.add(models.SystemSetting(key=key, value=value, is_secret=False))
    else:
        row.value = value
    db.commit()


def validate_time(value: str) -> str:
    """校验 HH:MM（24 小时制），非法时抛 ValueError。"""
    v = (value or "").strip()
    try:
        hh, mm = v.split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        raise ValueError(f"时间格式非法，应为 HH:MM（如 08:00），当前：{value!r}")
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"时间超出范围，应为 00:00~23:59，当前：{value!r}")
    return f"{h:02d}:{m:02d}"


def get_report_config(db: Session) -> dict:
    try:
        time_str = validate_time(_get_setting(db, KEY_TIME, DEFAULT_TIME))
    except ValueError:
        time_str = DEFAULT_TIME
    return {
        "enabled": _get_setting(db, KEY_ENABLED, "0") == "1",
        "time": time_str,
        "last_sent": _get_setting(db, KEY_LAST_SENT, ""),
    }


def set_report_config(db: Session, enabled: bool, time: str) -> dict:
    time_str = validate_time(time)
    _set_setting(db, KEY_ENABLED, "1" if enabled else "0")
    _set_setting(db, KEY_TIME, time_str)
    return get_report_config(db)


def _status_counts(db: Session, model, date_col=None) -> dict[str, int]:
    q = db.query(model.status, func.count(model.id))
    if date_col is not None:
        q = q.filter(func.date(date_col) == date.today().isoformat())
    return dict(q.group_by(model.status).all())


def build_daily_report(db: Session) -> str:
    """生成日报正文。章节无数据时省略。"""
    now = datetime.now(TZ)
    lines = [f"📊 OCI 面板每日健康报告", f"{now.strftime('%Y-%m-%d')}（周{WEEKDAYS[now.weekday()]}）", ""]

    # 1. 实例总览 + 巡检（实时查询，单租户失败隔离）
    tenants = db.query(models.Tenant).order_by(models.Tenant.id).all()
    if not tenants:
        lines += ["暂无租户配置，请先添加租户后再查看日报。"]
        return "\n".join(lines).strip()

    try:
        inspection = inspection_service.inspect_all(db)
    except Exception as exc:
        log.exception("日报巡检聚合失败")
        inspection = {"per_tenant": [], "issues": [], "errors": [{"message": str(exc)[:200]}]}

    lines.append("🖥️ 实例总览")
    total = running = stopped = 0
    for pt in inspection.get("per_tenant", []):
        t_total = pt.get("total", 0) or 0
        t_running = pt.get("running", 0) or 0
        t_stopped = pt.get("stopped", 0) or 0
        total += t_total
        running += t_running
        stopped += t_stopped
        lines.append(f"▪ {pt.get('tenant', '未知租户')}：共 {t_total} 台（运行中 {t_running} / 已停止 {t_stopped}）")
    for e in inspection.get("errors", []):
        lines.append(f"▪ {e.get('tenant', '未知租户')}：查询失败（{(e.get('message') or '')[:60]}）")
    lines.append(f"合计：{total} 台（运行中 {running} / 已停止 {stopped}）")
    lines.append("")

    # 2. 抢机任务状态
    snatch = _status_counts(db, models.SnatchTask)
    if snatch:
        parts = []
        if snatch.get("running"):
            parts.append(f"进行中 {snatch['running']}")
        if snatch.get("success"):
            parts.append(f"已成功 {snatch['success']}")
        if snatch.get("failed"):
            parts.append(f"已失败 {snatch['failed']}")
        if snatch.get("paused"):
            parts.append(f"已暂停 {snatch['paused']}")
        if snatch.get("pending"):
            parts.append(f"待开始 {snatch['pending']}")
        if parts:
            lines.append("🎯 抢机任务")
            lines.append(" · ".join(parts))
            lines.append("")

    # 3. 今日换 IP
    ip_counts = _status_counts(db, models.IpTask, models.IpTask.created_at)
    if ip_counts:
        parts = []
        if ip_counts.get("success"):
            parts.append(f"成功 {ip_counts['success']} 次")
        if ip_counts.get("failed"):
            parts.append(f"失败 {ip_counts['failed']} 次")
        active = (ip_counts.get("pending") or 0) + (ip_counts.get("running") or 0)
        if active:
            parts.append(f"进行中 {active} 次")
        lines.append("🔄 换 IP（今日）")
        lines.append(" · ".join(parts) if parts else "今日暂无换 IP 任务")
        lines.append("")

    # 4. 巡检告警
    issues = inspection.get("issues", []) or []
    if issues:
        lines.append("🩺 巡检告警")
        for issue in issues[:20]:
            tenant = issue.get("tenant", "")
            inst = issue.get("instance", "")
            msg = (issue.get("message") or "")[:80]
            where = f"{tenant}/{inst}" if inst else tenant
            lines.append(f"⚠️ [{where}] {msg}")
        if len(issues) > 20:
            lines.append(f"…另有 {len(issues) - 20} 条告警，详见巡检页面")
        lines.append("")

    return "\n".join(lines).strip()


def send_daily_report(db: Session, user_id: int | None = None, mark_sent: bool = True) -> dict:
    """生成并通过所有已启用通知渠道发送日报。mark_sent=False 时不更新 last_sent（测试发送用）。"""
    tenants = db.query(models.Tenant).count()
    body = build_daily_report(db)
    title = "OCI 面板每日健康报告"
    if tenants == 0:
        log.info("日报：无租户配置，跳过自动发送")
        return {"dispatched": False, "reason": "no_tenants", "body": body}
    result = notification_service.send_to_all(title, body)
    total_channels = len(result.get("results", []))
    if mark_sent and (total_channels == 0 or result.get("sent", 0) > 0):
        # 无渠道可发，或至少一个渠道成功 → 视为今日已发送；全失败则不标记，5 分钟后重试
        _set_setting(db, KEY_LAST_SENT, datetime.now(TZ).date().isoformat())
    if user_id is not None:
        write_log(db, user_id, "report.send",
                  f"发送每日健康报告（渠道成功 {result.get('sent', 0)} / 失败 {result.get('failed', 0)}）")
    return {
        "dispatched": True,
        "body": body,
        "channels_ok": result.get("sent", 0),
        "channels_failed": result.get("failed", 0),
        "results": result.get("results", []),
    }


async def check_and_send_daily_report() -> None:
    """APScheduler 定时入口：每天到点发送一次。配置落库，docker 重启后自动恢复。"""
    db = SessionLocal()
    try:
        cfg = get_report_config(db)
        if not cfg["enabled"]:
            return
        now = datetime.now(TZ)
        today = now.date().isoformat()
        if cfg["last_sent"] == today:
            return
        hh, mm = (int(x) for x in cfg["time"].split(":"))
        if now.hour * 60 + now.minute < hh * 60 + mm:
            return
        if db.query(models.Tenant).count() == 0:
            return  # 无租户时静默跳过，不刷日志
        log.info("每日健康报告到点发送（配置时间 %s）", cfg["time"])
        result = send_daily_report(db)
        log.info("每日健康报告发送结果：%s", {k: v for k, v in result.items() if k != "body"})
    except Exception:
        log.exception("每日健康报告定时发送失败")
    finally:
        db.close()
