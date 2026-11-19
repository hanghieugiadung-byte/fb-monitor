"""
Scheduler API routes — prefix: /api/scheduler
"""

from fastapi import APIRouter
from loguru import logger

from scheduler.engine import get_status, trigger_now

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.post("/trigger")
async def api_trigger_now():
    """
    Manually trigger the scrape cycle immediately.
    The job runs in the background; this endpoint returns at once.
    """
    logger.info("POST /api/scheduler/trigger called")
    result = await trigger_now()
    return result


@router.get("/status")
async def api_scheduler_status():
    """
    Return scheduler status and next scheduled run times.
    Response: { is_running, next_scrape, next_summary }
    """
    return get_status()
