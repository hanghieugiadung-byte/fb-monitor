"""
FB Monitor — Web Application adhering to viseshrp/fbn.
FastAPI backend with Multi-Account, Selective Scraping & Group Discovery.
"""

from contextlib import asynccontextmanager
import uvicorn
import secrets
from datetime import datetime, timezone
from fastapi import FastAPI, Request, HTTPException, Depends, status, UploadFile, File
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlmodel import select, delete
from typing import Optional, List

from core.db import (
    init_db,
    get_db_session,
    get_app_config,
    update_app_config,
    AppConfig,
    AccountItem,
    GroupItem,
    KeywordItem,
    SeenPost,
    RunLog,
    TopicItem,
    MonitorSchedule,
    utc_now,
)
from core.cookie_manager import parse_facebook_cookies
from core.fbn_scraper import extract_group_identifier
from core.notifier import test_telegram_connection
from core.fbn_service import (
    run_doctor,
    run_check_once,
    discover_groups,
    start_monitor,
    stop_monitor,
    is_monitoring,
    check_group_permission_service,
)

import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    cfg = get_app_config()
    if cfg.monitor_active:
        start_monitor()
    yield
    # Shutdown
    stop_monitor()


security = HTTPBasic(auto_error=False)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")


def verify_credentials(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if not ADMIN_PASSWORD:
        return True
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yêu cầu đăng nhập quản trị",
            headers={"WWW-Authenticate": "Basic"},
        )
    is_user_ok = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    is_pass_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (is_user_ok and is_pass_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tài khoản hoặc mật khẩu không chính xác",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


app = FastAPI(
    title="FB Monitor (fbn style)",
    description="Facebook Group Keyword Tracker, Multi-Account & Discovery",
    version="2.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_credentials)],
)


# ── Page Routes ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def index_page(request: Request):
    """Render the unified dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="fbn_app.html",
        context={},
    )


# ── API: App State ──────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    """Return the entire state of the system for reactive frontend UI."""
    cfg = get_app_config()
    with get_db_session() as session:
        accounts = session.exec(select(AccountItem).order_by(AccountItem.created_at.desc())).all()
        groups = session.exec(select(GroupItem).order_by(GroupItem.created_at.desc())).all()
        keywords = session.exec(select(KeywordItem).order_by(KeywordItem.created_at.desc())).all()
        topics = session.exec(select(TopicItem).order_by(TopicItem.name.asc())).all()
        schedules = session.exec(select(MonitorSchedule).order_by(MonitorSchedule.created_at.desc())).all()
        seen_posts = session.exec(select(SeenPost).order_by(SeenPost.scraped_at.desc()).limit(150)).all()
        recent_posts = seen_posts[:10]
        logs = session.exec(select(RunLog).order_by(RunLog.started_at.desc()).limit(50)).all()

    return {
        "config": {
            "fb_cookies": cfg.fb_cookies,
            "telegram_bot_token": cfg.telegram_bot_token,
            "telegram_chat_id": cfg.telegram_chat_id,
            "scrape_interval_minutes": cfg.scrape_interval_minutes,
            "max_posts_per_scan": cfg.max_posts_per_scan,
            "monitor_active": cfg.monitor_active,
            "active_account_id": cfg.active_account_id,
            "is_monitoring_running": is_monitoring(),
        },
        "accounts": [a.model_dump() for a in accounts],
        "groups": [g.model_dump() for g in groups],
        "keywords": [k.model_dump() for k in keywords],
        "topics": [t.model_dump() for t in topics],
        "schedules": [s.model_dump() for s in schedules],
        "recent_posts": [p.model_dump() for p in recent_posts],
        "seen_posts": [p.model_dump() for p in seen_posts],
        "logs": [l.model_dump() for l in logs],
    }


# ── API: Settings ───────────────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    fb_cookies: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    scrape_interval_minutes: Optional[int] = None
    max_posts_per_scan: Optional[int] = None
    active_account_id: Optional[int] = None


@app.post("/api/settings")
async def save_settings(payload: SettingsPayload):
    """Update settings in database."""
    cfg = update_app_config(
        fb_cookies=payload.fb_cookies,
        telegram_bot_token=payload.telegram_bot_token,
        telegram_chat_id=payload.telegram_chat_id,
        scrape_interval_minutes=payload.scrape_interval_minutes,
        max_posts_per_scan=payload.max_posts_per_scan,
        active_account_id=payload.active_account_id,
    )
    return {"status": "success", "config": cfg.model_dump()}


# ── API: Multi-Account Management ───────────────────────────────────────────

class AccountCreatePayload(BaseModel):
    name: str
    cookies: str


@app.post("/api/accounts")
async def add_account(payload: AccountCreatePayload):
    """Add a Facebook account to the pool."""
    name_clean = payload.name.strip()
    cookies_raw = payload.cookies.strip()
    if not name_clean or not cookies_raw:
        raise HTTPException(status_code=400, detail="Vui lòng nhập tên tài khoản và cookie")

    cookies_list, c_user, err = parse_facebook_cookies(cookies_raw)

    with get_db_session() as session:
        acc = AccountItem(
            name=name_clean,
            cookies=cookies_raw,
            c_user=c_user,
            is_active=True,
            status="ready" if not err else "warning",
            status_msg=err or "Đã nạp cookie",
        )
        session.add(acc)
        session.commit()
        session.refresh(acc)
        return acc.model_dump()


@app.post("/api/accounts/{account_id}/toggle")
async def toggle_account(account_id: int):
    """Toggle active status of an account."""
    with get_db_session() as session:
        acc = session.get(AccountItem, account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
        acc.is_active = not acc.is_active
        session.add(acc)
        session.commit()
        return {"status": "success", "is_active": acc.is_active}


@app.post("/api/accounts/{account_id}/test")
async def test_account(account_id: int):
    """Run diagnostics on a specific account."""
    res = await run_doctor(account_id=account_id)
    return res


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int):
    """Delete an account from the pool."""
    with get_db_session() as session:
        acc = session.get(AccountItem, account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Không tìm thấy tài khoản")
        session.delete(acc)
        session.commit()
        return {"status": "success"}


# ── API: Group Discovery Search ─────────────────────────────────────────────

class DiscoverPayload(BaseModel):
    keyword: str
    min_members: int = 0
    privacy: str = "all"
    max_results: int = 15
    account_id: Optional[int] = None


@app.post("/api/groups/discover")
async def api_discover(payload: DiscoverPayload):
    """Search & discover Facebook groups based on keyword and filtering conditions."""
    if not payload.keyword.strip():
        raise HTTPException(status_code=400, detail="Vui lòng nhập từ khóa tìm nhóm")

    return await discover_groups(
        keyword=payload.keyword,
        min_members=payload.min_members,
        privacy_filter=payload.privacy,
        max_results=payload.max_results,
        account_id=payload.account_id,
    )


# ── API: Doctor (Diagnostics) ───────────────────────────────────────────────

@app.post("/api/doctor")
async def api_doctor():
    """Run diagnostics on Chromium, Facebook cookies, and Telegram."""
    return await run_doctor()


# ── API: Check (Selective / Single Scan) ────────────────────────────────────

class CheckPayload(BaseModel):
    dry_run: bool = False
    group_ids: Optional[List[int]] = None
    keyword_ids: Optional[List[int]] = None
    account_id: Optional[int] = None


@app.post("/api/check")
async def api_check(payload: CheckPayload):
    """Run a scan with selective groups, keywords, and account."""
    return await run_check_once(
        dry_run=payload.dry_run,
        run_type="check",
        group_ids=payload.group_ids,
        keyword_ids=payload.keyword_ids,
        account_id=payload.account_id,
    )


# ── API: Monitor (Background Daemon Toggle) ──────────────────────────────────

@app.post("/api/monitor/toggle")
async def api_toggle_monitor():
    """Toggle continuous background monitoring."""
    cfg = get_app_config()
    new_state = not cfg.monitor_active
    update_app_config(monitor_active=new_state)

    if new_state:
        start_monitor()
    else:
        stop_monitor()

    return {"status": "success", "monitor_active": new_state}


# ── API: Telegram Test ──────────────────────────────────────────────────────

class TelegramTestPayload(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


@app.post("/api/telegram/test")
async def api_test_telegram(payload: TelegramTestPayload):
    """Send test message to Telegram."""
    cfg = get_app_config()
    token = payload.bot_token or cfg.telegram_bot_token
    chat = payload.chat_id or cfg.telegram_chat_id

    ok, msg = await test_telegram_connection(token, chat)
    return {"success": ok, "message": msg}


# ── API: Groups Management ──────────────────────────────────────────────────

class GroupCreatePayload(BaseModel):
    name: str
    fb_url: str
    member_count: Optional[int] = None
    privacy: str = "unknown"
    topic_name: str = "Chưa phân loại"
    is_joined: bool = False
    post_permission: str = "unknown"
    post_permission_text: str = "Chưa kiểm tra"


@app.post("/api/groups")
async def add_group(payload: GroupCreatePayload):
    """Add a Facebook group target."""
    clean_id = extract_group_identifier(payload.fb_url)
    with get_db_session() as session:
        existing = session.exec(select(GroupItem).where(GroupItem.clean_group_id == clean_id)).first()
        if existing:
            existing.name = payload.name.strip()
            existing.is_active = True
            if payload.member_count:
                existing.member_count = payload.member_count
            if payload.privacy != "unknown":
                existing.privacy = payload.privacy
            if payload.topic_name and payload.topic_name != "Chưa phân loại":
                existing.topic_name = payload.topic_name
            if payload.post_permission != "unknown":
                existing.post_permission = payload.post_permission
                existing.post_permission_text = payload.post_permission_text
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing.model_dump()

        grp = GroupItem(
            name=payload.name.strip(),
            fb_url=payload.fb_url.strip(),
            clean_group_id=clean_id,
            member_count=payload.member_count,
            privacy=payload.privacy,
            topic_name=payload.topic_name or "Chưa phân loại",
            is_joined=payload.is_joined,
            post_permission=payload.post_permission,
            post_permission_text=payload.post_permission_text,
            is_active=True,
        )
        session.add(grp)
        session.commit()
        session.refresh(grp)
        return grp.model_dump()


@app.post("/api/groups/{group_id}/toggle")
async def toggle_group(group_id: int):
    """Toggle active status of a group."""
    with get_db_session() as session:
        grp = session.get(GroupItem, group_id)
        if not grp:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
        grp.is_active = not grp.is_active
        session.add(grp)
        session.commit()
        return {"status": "success", "is_active": grp.is_active}


class GroupTopicPayload(BaseModel):
    topic_name: str


@app.post("/api/groups/{group_id}/topic")
async def update_group_topic(group_id: int, payload: GroupTopicPayload):
    """Update topic/category of a group."""
    with get_db_session() as session:
        grp = session.get(GroupItem, group_id)
        if not grp:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
        grp.topic_name = payload.topic_name.strip() or "Chưa phân loại"
        session.add(grp)
        session.commit()
        session.refresh(grp)
        return grp.model_dump()


@app.post("/api/groups/{group_id}/joined")
async def toggle_group_joined(group_id: int):
    """Toggle joined status of a group."""
    with get_db_session() as session:
        grp = session.get(GroupItem, group_id)
        if not grp:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
        grp.is_joined = not grp.is_joined
        session.add(grp)
        session.commit()
        return {"status": "success", "is_joined": grp.is_joined}


@app.post("/api/groups/{group_id}/check-permission")
async def api_check_group_permission(group_id: int):
    """Check posting and commenting permission for a group."""
    return await check_group_permission_service(group_id)


# ── API: Topics Management ──────────────────────────────────────────────────

class TopicCreatePayload(BaseModel):
    name: str
    color: str = "blue"


@app.post("/api/topics")
async def create_topic(payload: TopicCreatePayload):
    """Create a new topic."""
    name_clean = payload.name.strip()
    if not name_clean:
        raise HTTPException(status_code=400, detail="Tên chủ đề không được để trống")
    with get_db_session() as session:
        existing = session.exec(select(TopicItem).where(TopicItem.name == name_clean)).first()
        if existing:
            return existing.model_dump()
        t = TopicItem(name=name_clean, color=payload.color or "blue")
        session.add(t)
        session.commit()
        session.refresh(t)
        return t.model_dump()


@app.delete("/api/topics/{topic_id}")
async def delete_topic(topic_id: int):
    """Delete a topic."""
    with get_db_session() as session:
        t = session.get(TopicItem, topic_id)
        if not t:
            raise HTTPException(status_code=404, detail="Không tìm thấy chủ đề")
        session.delete(t)
        session.commit()
        return {"status": "success"}


# ── API: Schedules Management (Flexible Auto-Scan) ─────────────────────────

class ScheduleCreatePayload(BaseModel):
    name: str
    account_id: Optional[int] = None
    group_ids: List[int] = []
    keyword_ids: List[int] = []
    interval_minutes: int = 10
    start_time: str = "00:00"
    end_time: str = "23:59"


@app.post("/api/schedules")
async def create_schedule(payload: ScheduleCreatePayload):
    """Create or update an automated scanning schedule."""
    import json
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Vui lòng đặt tên cho lịch quét")
    with get_db_session() as session:
        sched = MonitorSchedule(
            name=payload.name.strip(),
            account_id=payload.account_id,
            group_ids_json=json.dumps(payload.group_ids),
            keyword_ids_json=json.dumps(payload.keyword_ids),
            interval_minutes=max(1, payload.interval_minutes),
            start_time=payload.start_time or "00:00",
            end_time=payload.end_time or "23:59",
            is_active=True,
        )
        session.add(sched)
        session.commit()
        session.refresh(sched)
        return sched.model_dump()


@app.post("/api/schedules/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: int):
    """Toggle active status of a schedule."""
    with get_db_session() as session:
        sched = session.get(MonitorSchedule, schedule_id)
        if not sched:
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")
        sched.is_active = not sched.is_active
        session.add(sched)
        session.commit()
        return {"status": "success", "is_active": sched.is_active}


@app.delete("/api/schedules/{schedule_id}")
async def delete_schedule(schedule_id: int):
    """Delete a schedule."""
    with get_db_session() as session:
        sched = session.get(MonitorSchedule, schedule_id)
        if not sched:
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")
        session.delete(sched)
        session.commit()
        return {"status": "success"}


@app.post("/api/schedules/{schedule_id}/run-now")
async def run_schedule_now(schedule_id: int):
    """Execute a schedule immediately (test run)."""
    import json
    with get_db_session() as session:
        sched = session.get(MonitorSchedule, schedule_id)
        if not sched:
            raise HTTPException(status_code=404, detail="Không tìm thấy lịch")
        grp_ids = json.loads(sched.group_ids_json) if sched.group_ids_json else None
        kw_ids = json.loads(sched.keyword_ids_json) if sched.keyword_ids_json else None
        acc_id = sched.account_id
        name = sched.name

    res = await run_check_once(
        dry_run=False,
        run_type=f"manual-schedule:{name}",
        group_ids=grp_ids,
        keyword_ids=kw_ids,
        account_id=acc_id,
    )
    with get_db_session() as session:
        db_sched = session.get(MonitorSchedule, schedule_id)
        if db_sched:
            db_sched.last_run_at = utc_now()
            session.add(db_sched)
            session.commit()
    return res


@app.delete("/api/groups/{group_id}")
async def delete_group(group_id: int):
    """Delete a group."""
    with get_db_session() as session:
        grp = session.get(GroupItem, group_id)
        if not grp:
            raise HTTPException(status_code=404, detail="Không tìm thấy nhóm")
        session.delete(grp)
        session.commit()
        return {"status": "success"}


# ── API: Keywords Management ────────────────────────────────────────────────

class KeywordCreatePayload(BaseModel):
    text: str


@app.post("/api/keywords")
async def add_keyword(payload: KeywordCreatePayload):
    """Add target keywords (supports comma or newline separated values)."""
    raw = payload.text.replace("\n", ",")
    items = [x.strip().lower() for x in raw.split(",") if x.strip()]
    if not items:
        raise HTTPException(status_code=400, detail="Từ khóa không được để trống")

    results = []
    with get_db_session() as session:
        for text_clean in items:
            existing = session.exec(select(KeywordItem).where(KeywordItem.text == text_clean)).first()
            if existing:
                results.append(existing.model_dump())
            else:
                kw = KeywordItem(text=text_clean, is_active=True)
                session.add(kw)
                session.commit()
                session.refresh(kw)
                results.append(kw.model_dump())
        return results[-1] if results else {}


@app.post("/api/keywords/{keyword_id}/toggle")
async def toggle_keyword(keyword_id: int):
    """Toggle active status of a keyword."""
    with get_db_session() as session:
        kw = session.get(KeywordItem, keyword_id)
        if not kw:
            raise HTTPException(status_code=404, detail="Không tìm thấy từ khóa")
        kw.is_active = not kw.is_active
        session.add(kw)
        session.commit()
        return {"status": "success", "is_active": kw.is_active}


@app.delete("/api/keywords/{keyword_id}")
async def delete_keyword(keyword_id: int):
    """Delete a keyword."""
    with get_db_session() as session:
        kw = session.get(KeywordItem, keyword_id)
        if not kw:
            raise HTTPException(status_code=404, detail="Không tìm thấy từ khóa")
        session.delete(kw)
        session.commit()
        return {"status": "success"}


# ── API: Posts Management ───────────────────────────────────────────────────

@app.post("/api/posts/clear")
async def clear_seen_posts():
    """Clear all seen posts from database to allow fresh scanning."""
    with get_db_session() as session:
        session.exec(delete(SeenPost))
        session.commit()
    return {"status": "success", "message": "Đã xóa toàn bộ bài viết đã lưu"}


# ── API: Data Sync & Backup (Export / Import) ───────────────────────────────

@app.get("/api/data/export")
async def export_data():
    """Export groups, keywords, and topics as JSON for syncing between Local and VPS."""
    with get_db_session() as session:
        groups = session.exec(select(GroupItem)).all()
        keywords = session.exec(select(KeywordItem)).all()
        topics = session.exec(select(TopicItem)).all()

    data = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "topics": [t.model_dump(exclude={"id", "created_at"}) for t in topics],
        "keywords": [k.model_dump(exclude={"id", "created_at"}) for k in keywords],
        "groups": [g.model_dump(exclude={"id", "last_scraped_at", "created_at"}) for g in groups],
    }
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f"attachment; filename=fb_monitor_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"},
    )


class ImportDataPayload(BaseModel):
    topics: Optional[List[dict]] = None
    keywords: Optional[List[dict]] = None
    groups: Optional[List[dict]] = None


@app.post("/api/data/import")
async def import_data(payload: ImportDataPayload):
    """Import and seamlessly merge groups, keywords, and topics without duplicates."""
    added_topics = 0
    added_keywords = 0
    added_groups = 0

    with get_db_session() as session:
        # 1. Topics
        if payload.topics:
            for t_data in payload.topics:
                t_name = (t_data.get("name") or "").strip()
                if not t_name:
                    continue
                exist_t = session.exec(select(TopicItem).where(TopicItem.name == t_name)).first()
                if not exist_t:
                    new_t = TopicItem(name=t_name, color=t_data.get("color", "blue"))
                    session.add(new_t)
                    added_topics += 1
            session.commit()

        # 2. Keywords
        if payload.keywords:
            for k_data in payload.keywords:
                k_text = (k_data.get("text") or "").strip()
                if not k_text:
                    continue
                exist_k = session.exec(select(KeywordItem).where(KeywordItem.text == k_text)).first()
                if not exist_k:
                    new_k = KeywordItem(text=k_text, is_active=k_data.get("is_active", True))
                    session.add(new_k)
                    added_keywords += 1
            session.commit()

        # 3. Groups
        if payload.groups:
            for g_data in payload.groups:
                fb_url = (g_data.get("fb_url") or "").strip()
                g_name = (g_data.get("name") or "").strip()
                if not fb_url:
                    continue
                cid = g_data.get("clean_group_id") or extract_group_identifier(fb_url)
                exist_g = session.exec(select(GroupItem).where(GroupItem.clean_group_id == cid)).first()
                if not exist_g:
                    new_g = GroupItem(
                        name=g_name or cid,
                        fb_url=fb_url,
                        clean_group_id=cid,
                        member_count=g_data.get("member_count", 0),
                        privacy=g_data.get("privacy", "unknown"),
                        topic_name=g_data.get("topic_name", "Chưa phân loại"),
                        is_joined=g_data.get("is_joined", False),
                        is_active=g_data.get("is_active", True),
                        post_permission=g_data.get("post_permission", "unknown"),
                        post_permission_text=g_data.get("post_permission_text", "Chưa kiểm tra"),
                        comment_permission=g_data.get("comment_permission", "open"),
                        comment_permission_text=g_data.get("comment_permission_text", "Bình luận mở"),
                    )
                    session.add(new_g)
                    added_groups += 1
            session.commit()

    return {
        "status": "success",
        "added_topics": added_topics,
        "added_keywords": added_keywords,
        "added_groups": added_groups,
        "message": f"Đã nhập thành công: {added_groups} nhóm mới, {added_keywords} từ khóa mới, {added_topics} chủ đề mới!",
    }


# ── Main Entry Point ────────────────────────────────────────────────────────

def is_port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


if __name__ == "__main__":
    port = 8000
    if is_port_in_use(port):
        for candidate in [8080, 8001, 8002, 8888]:
            if not is_port_in_use(candidate):
                port = candidate
                print(f"\n⚠️  Cổng 8000 đang có tiến trình khác chạy!")
                print(f"👉 Ứng dụng tự động khởi động tại: http://localhost:{port}\n")
                break

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )
