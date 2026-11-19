from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, func, select

from api.auth import verify_api_key
from api.deps import get_db
from api.schemas import DashboardStats, PostResponse
from storage.models import Group, Keyword, Post, ScrapeLog

router = APIRouter(
    prefix="/api/posts",
    tags=["posts"],
    dependencies=[Depends(verify_api_key)],
)


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    session: Session = Depends(get_db),
) -> DashboardStats:
    """Return aggregate dashboard statistics."""
    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)

    total_groups = session.exec(select(func.count(Group.id))).one()
    active_groups = session.exec(
        select(func.count(Group.id)).where(Group.is_active == True)  # noqa: E712
    ).one()
    total_keywords = session.exec(select(func.count(Keyword.id))).one()
    active_keywords = session.exec(
        select(func.count(Keyword.id)).where(Keyword.is_active == True)  # noqa: E712
    ).one()
    posts_today = session.exec(
        select(func.count(Post.id)).where(Post.scraped_at >= today_start)
    ).one()
    posts_sent_today = session.exec(
        select(func.count(Post.id)).where(
            Post.scraped_at >= today_start,
            Post.is_sent == True,  # noqa: E712
        )
    ).one()

    # Last completed scrape
    last_log = session.exec(
        select(ScrapeLog)
        .where(ScrapeLog.finished_at.isnot(None))  # type: ignore[attr-defined]
        .order_by(ScrapeLog.finished_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    ).first()
    last_scrape_time = last_log.finished_at if last_log else None

    return DashboardStats(
        total_groups=total_groups,
        active_groups=active_groups,
        total_keywords=total_keywords,
        active_keywords=active_keywords,
        posts_today=posts_today,
        posts_sent_today=posts_sent_today,
        last_scrape_time=last_scrape_time,
    )


@router.get("/", response_model=List[PostResponse])
async def list_posts(
    group_id: Optional[int] = Query(default=None),
    is_sent: Optional[bool] = Query(default=None),
    keyword: Optional[str] = Query(default=None, description="Filter posts whose matched_keywords contains this string"),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    session: Session = Depends(get_db),
) -> List[Post]:
    """Return a paginated list of posts with optional filters."""
    stmt = select(Post)

    if group_id is not None:
        stmt = stmt.where(Post.group_id == group_id)
    if is_sent is not None:
        stmt = stmt.where(Post.is_sent == is_sent)
    if keyword:
        stmt = stmt.where(Post.matched_keywords.contains(keyword))  # type: ignore[attr-defined]
    if date_from:
        stmt = stmt.where(Post.scraped_at >= datetime.combine(date_from, datetime.min.time(), tzinfo=timezone.utc))
    if date_to:
        stmt = stmt.where(Post.scraped_at <= datetime.combine(date_to, datetime.max.time(), tzinfo=timezone.utc))

    stmt = stmt.order_by(Post.scraped_at.desc()).offset(skip).limit(limit)  # type: ignore[attr-defined]
    return session.exec(stmt).all()


@router.get("/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: int,
    session: Session = Depends(get_db),
) -> Post:
    """Return a single post by its database id."""
    post = session.get(Post, post_id)
    if not post:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return post
