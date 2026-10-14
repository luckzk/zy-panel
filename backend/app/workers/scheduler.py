"""APScheduler 调度器：后台定时任务统一入口。"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .ip_worker import run_ip_tasks
from .scheduled_worker import run_scheduled_tasks
from .snatch_worker import poll_snatch_tasks
from .aliyun_spot_worker import poll_spot_tasks
from ..services.report_service import check_and_send_daily_report

log = logging.getLogger(__name__)

SNATCH_POLL_INTERVAL_SEC = 15  # 全局扫描节拍；各任务的实际间隔由任务自身 interval_sec 控制
IP_CHANGE_POLL_INTERVAL_SEC = 30  # 换 IP 任务轮询间隔
SCHEDULED_TASK_INTERVAL_SEC = 60  # 定时任务（cron）扫描间隔
DAILY_REPORT_CHECK_INTERVAL_SEC = 300  # 每日报告到点检查间隔（具体发送时间由 daily_report_time 配置决定）

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


def start_scheduler() -> None:
    """注册定时任务并启动（应用 lifespan 中调用）。"""
    scheduler.add_job(
        poll_snatch_tasks,
        "interval",
        seconds=SNATCH_POLL_INTERVAL_SEC,
        id="snatch-poll",
        replace_existing=True,
        max_instances=1,  # 防止上次未跑完又触发
    )
    scheduler.add_job(
        poll_spot_tasks,
        "interval",
        seconds=SNATCH_POLL_INTERVAL_SEC,  # 复用抢机扫描节拍；各任务实际间隔由自身 interval_sec 控制
        id="aliyun-spot-poll",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        run_ip_tasks,
        "interval",
        seconds=IP_CHANGE_POLL_INTERVAL_SEC,
        id="ip-change-poll",
        replace_existing=True,
        max_instances=1,  # 防止上次未跑完又触发
    )
    scheduler.add_job(
        run_scheduled_tasks,
        "interval",
        seconds=SCHEDULED_TASK_INTERVAL_SEC,
        id="scheduled-tasks",
        replace_existing=True,
        max_instances=1,  # 防止上次未跑完又触发
    )
    scheduler.add_job(
        check_and_send_daily_report,
        "interval",
        seconds=DAILY_REPORT_CHECK_INTERVAL_SEC,
        id="daily-report",
        replace_existing=True,
        max_instances=1,  # 巡检聚合可能较慢，防止重叠
    )
    # TODO: 流量定时采集、配额定时刷新
    scheduler.start()
    log.info(
        "APScheduler 已启动，抢机轮询间隔 %ss，换 IP 轮询间隔 %ss，定时任务扫描间隔 %ss，每日报告检查间隔 %ss",
        SNATCH_POLL_INTERVAL_SEC,
        IP_CHANGE_POLL_INTERVAL_SEC,
        SCHEDULED_TASK_INTERVAL_SEC,
        DAILY_REPORT_CHECK_INTERVAL_SEC,
    )


def shutdown_scheduler() -> None:
    scheduler.shutdown(wait=False)
