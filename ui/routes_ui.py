from datetime import datetime, date, timezone
from typing import Optional

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from storage.database import get_session
from storage.models import Group, Keyword, Post, ScrapeLog

router = APIRouter()
templates = Jinja2Templates(directory="templates")


def render_template(request: Request, name: str, context: dict) -> HTMLResponse:
    """Helper to render Jinja2 templates compatibly across all Starlette/FastAPI versions."""
    context["request"] = request
    try:
        return templates.TemplateResponse(request=request, name=name, context=context)
    except TypeError:
        # Fallback for older Starlette versions where signature was (name, context)
        return templates.TemplateResponse(name, context)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, session: Session = Depends(get_session)):
    # Stat counts
    total_groups = session.exec(select(func.count(Group.id))).one()
    active_keywords = session.exec(
        select(func.count(Keyword.id)).where(Keyword.is_active == True)
    ).one()

    today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
    posts_today = session.exec(
        select(func.count(Post.id)).where(Post.scraped_at >= today_start)
    ).one()
    sent_today = session.exec(
        select(func.count(Post.id)).where(
            Post.scraped_at >= today_start,
            Post.is_sent == True,
        )
    ).one()

    # Recent 10 posts
    recent_posts = session.exec(
        select(Post).order_by(Post.scraped_at.desc()).limit(10)
    ).all()

    # Enrich posts with group names
    group_map = {g.id: g.name for g in session.exec(select(Group)).all()}

    # Last scrape log
    last_log: Optional[ScrapeLog] = session.exec(
        select(ScrapeLog).order_by(ScrapeLog.started_at.desc()).limit(1)
    ).first()

    stats = {
        "total_groups": total_groups,
        "active_keywords": active_keywords,
        "posts_today": posts_today,
        "sent_today": sent_today,
    }

    return render_template(
        request=request,
        name="dashboard.html",
        context={
            "stats": stats,
            "recent_posts": recent_posts,
            "group_map": group_map,
            "last_log": last_log,
        },
    )


@router.get("/groups", response_class=HTMLResponse)
async def groups_page(request: Request, session: Session = Depends(get_session)):
    groups = session.exec(select(Group).order_by(Group.created_at.desc())).all()
    return render_template(
        request=request,
        name="groups.html",
        context={"groups": groups},
    )


@router.get("/keywords", response_class=HTMLResponse)
async def keywords_page(request: Request, session: Session = Depends(get_session)):
    keywords = session.exec(select(Keyword).order_by(Keyword.created_at.desc())).all()
    return render_template(
        request=request,
        name="keywords.html",
        context={"keywords": keywords},
    )


@router.get("/posts", response_class=HTMLResponse)
async def posts_page(
    request: Request,
    session: Session = Depends(get_session),
    page: int = 1,
    group_id: Optional[int] = None,
    keyword: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sent: Optional[str] = None,
):
    per_page = 20
    query = select(Post)

    if group_id:
        query = query.where(Post.group_id == group_id)
    if keyword:
        query = query.where(Post.matched_keywords.contains(keyword))
    if date_from:
        dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        query = query.where(Post.scraped_at >= dt_from)
    if date_to:
        dt_to = datetime.fromisoformat(date_to + "T23:59:59").replace(tzinfo=timezone.utc)
        query = query.where(Post.scraped_at <= dt_to)
    if sent == "yes":
        query = query.where(Post.is_sent == True)
    elif sent == "no":
        query = query.where(Post.is_sent == False)

    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    posts = session.exec(
        query.order_by(Post.scraped_at.desc()).offset((page - 1) * per_page).limit(per_page)
    ).all()

    groups = session.exec(select(Group)).all()
    group_map = {g.id: g.name for g in groups}
    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        request=request,
        name="posts.html",
        context={
            "posts": posts,
            "groups": groups,
            "group_map": group_map,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "filters": {
                "group_id": group_id,
                "keyword": keyword,
                "date_from": date_from,
                "date_to": date_to,
                "sent": sent,
            },
        },
    )


@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request, session: Session = Depends(get_session)):
    logs = session.exec(
        select(ScrapeLog).order_by(ScrapeLog.started_at.desc()).limit(100)
    ).all()
    group_map = {g.id: g.name for g in session.exec(select(Group)).all()}
    return render_template(
        request=request,
        name="logs.html",
        context={"logs": logs, "group_map": group_map},
    )
