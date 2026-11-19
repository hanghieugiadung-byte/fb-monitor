from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from api.auth import verify_api_key
from api.deps import get_db
from api.schemas import ScrapeLogResponse
from storage.models import ScrapeLog

router = APIRouter(
    prefix="/api/logs",
    tags=["logs"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/latest", response_model=List[ScrapeLogResponse])
async def get_latest_logs(
    session: Session = Depends(get_db),
) -> List[ScrapeLog]:
    """Return the 10 most recent scrape logs."""
    stmt = (
        select(ScrapeLog)
        .order_by(ScrapeLog.started_at.desc())  # type: ignore[attr-defined]
        .limit(10)
    )
    return session.exec(stmt).all()


@router.get("/", response_model=List[ScrapeLogResponse])
async def list_logs(
    group_id: Optional[int] = Query(default=None),
    status: Optional[str] = Query(default=None, description="Filter by status: running, success, error"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
) -> List[ScrapeLog]:
    """Return paginated scrape logs with optional filters."""
    stmt = select(ScrapeLog)
    if group_id is not None:
        stmt = stmt.where(ScrapeLog.group_id == group_id)
    if status is not None:
        stmt = stmt.where(ScrapeLog.status == status)
    stmt = stmt.order_by(ScrapeLog.started_at.desc()).offset(skip).limit(limit)  # type: ignore[attr-defined]
    return session.exec(stmt).all()
