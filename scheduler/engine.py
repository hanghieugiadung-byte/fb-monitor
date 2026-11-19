"""
APScheduler engine for fb-monitor.
Manages the AsyncIOScheduler lifecycle and exposes utility functions
for starting, stopping, and manually triggering the scrape cycle.
"""

import asyncio
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from config import get_config

# Module-level scheduler instance
_scheduler: AsyncIOScheduler | None = None
_is_running: bool = False


def _build_scheduler() -> AsyncIOScheduler:
    config = get_config()
    scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")

    # Import here to avoid circular imports at module load time
    from scheduler.jobs import run_scrape_cycle, run_daily_summary

    # Interval job: scrape cycle
    scheduler.add_job(
        run_scrape_cycle,
        trigger=IntervalTrigger(minutes=config.SCRAPE_INTERVAL_MINUTES),
        id="scrape_cycle",
        name="FB Group Scrape Cycle",
        replace_existing=True,
        max_instances=1,  # prevent overlap
        coalesce=True,
    )

    # Daily summary at 08:00 Vietnam time
    scheduler.add_job(
        run_daily_summary,
        trigger=CronTrigger(hour=8, minute=0, timezone="Asia/Ho_Chi_Minh"),
        id="daily_summary",
        name="Daily Summary Report",
        replace_existing=True,
        max_instances=1,
    )

    logger.info(
        f"Scheduler built: scrape every {config.SCRAPE_INTERVAL_MINUTES} min, "
        "daily summary at 08:00 (Asia/Ho_Chi_Minh)"
    )
    return scheduler


async def start_scheduler() -> None:
    """Start the APScheduler. Called from FastAPI startup event."""
    global _scheduler, _is_running
    if _is_running:
        logger.warning("Scheduler already running — skipping start")
        return
    _scheduler = _build_scheduler()
    _scheduler.start()
    _is_running = True
    logger.info("Scheduler started")


async def stop_scheduler() -> None:
    """Stop the APScheduler. Called from FastAPI shutdown event."""
    global _scheduler, _is_running
    if _scheduler and _is_running:
        _scheduler.shutdown(wait=False)
        _is_running = False
        logger.info("Scheduler stopped")


async def trigger_now() -> dict:
    """
    Manually trigger run_scrape_cycle immediately (from UI / API).
    Runs the job in a background task so the HTTP response returns quickly.
    """
    from scheduler.jobs import run_scrape_cycle

    logger.info("Manual trigger: run_scrape_cycle")
    asyncio.create_task(run_scrape_cycle())
    return {"triggered": True, "message": "Scrape cycle started in background"}


def get_status() -> dict:
    """Return current scheduler status and next run time."""
    global _scheduler, _is_running

    if not _scheduler or not _is_running:
        return {
            "is_running": False,
            "next_scrape": None,
            "next_summary": None,
        }

    scrape_job = _scheduler.get_job("scrape_cycle")
    summary_job = _scheduler.get_job("daily_summary")

    def fmt(job) -> str | None:
        if job and job.next_run_time:
            return job.next_run_time.isoformat()
        return None

    return {
        "is_running": _is_running,
        "next_scrape": fmt(scrape_job),
        "next_summary": fmt(summary_job),
    }
