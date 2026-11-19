"""
Database models and session management for FB Monitor (fbn style).
Supports Multi-Account, Group Discovery, Selective Scraping, Seen Posts, and Logs.
"""

from datetime import datetime, timezone
from typing import Optional, List
import os
from sqlmodel import SQLModel, Field, create_engine, Session, select

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    data_dir = os.environ.get("DATA_DIR", "")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
        db_file = os.path.join(data_dir, "fb_monitor.db")
    else:
        db_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fb_monitor.db")
    DATABASE_URL = f"sqlite:///{os.path.abspath(db_file)}"

engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AppConfig(SQLModel, table=True):
    """Application global settings."""
    id: int = Field(default=1, primary_key=True)
    fb_cookies: str = Field(default="", description="Default/fallback cookies")
    telegram_bot_token: str = Field(default="", description="Telegram Bot Token")
    telegram_chat_id: str = Field(default="", description="Telegram Chat ID or Channel ID")
    scrape_interval_minutes: int = Field(default=10, description="Interval between automatic monitor checks")
    max_posts_per_scan: int = Field(default=20, description="Max posts to parse per group per scan")
    monitor_active: bool = Field(default=False, description="Whether continuous background monitoring is enabled")
    last_monitor_run: Optional[datetime] = Field(default=None)
    active_account_id: Optional[int] = Field(default=None, description="Active account ID or None for round-robin")


class AccountItem(SQLModel, table=True):
    """Multiple Facebook accounts for rotation and resilience."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="Account nickname or description")
    cookies: str = Field(description="Facebook cookies in header or JSON format")
    c_user: Optional[str] = Field(default=None, description="Extracted Facebook UID")
    is_active: bool = Field(default=True)
    status: str = Field(default="ready", description="'ready', 'valid', 'expired', 'checkpoint', 'error'")
    status_msg: Optional[str] = Field(default=None)
    last_used_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class TopicItem(SQLModel, table=True):
    """Custom topics/categories to organize and classify groups."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True, description="Topic name")
    color: str = Field(default="blue", description="Badge color (blue, emerald, purple, amber, rose, cyan)")
    created_at: datetime = Field(default_factory=utc_now)


class GroupItem(SQLModel, table=True):
    """Target Facebook groups to monitor and repository."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="User-friendly name of the group")
    fb_url: str = Field(description="Group URL or numeric group ID")
    clean_group_id: str = Field(default="", description="Extracted clean group ID or alias")
    member_count: Optional[int] = Field(default=None, description="Approximate member count")
    privacy: str = Field(default="unknown", description="'public', 'private', or 'unknown'")
    topic_name: str = Field(default="Chưa phân loại", description="Topic/Category name")
    is_joined: bool = Field(default=False, description="Has joined or requested to join")
    post_permission: str = Field(default="unknown", description="'free', 'approval', 'admin_only', 'unknown'")
    post_permission_text: str = Field(default="Chưa kiểm tra", description="Human readable approval status")
    comment_permission: str = Field(default="unknown", description="'open', 'restricted', 'unknown'")
    comment_permission_text: str = Field(default="Chưa kiểm tra", description="Human readable comment status")
    is_active: bool = Field(default=True)
    last_scraped_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class MonitorSchedule(SQLModel, table=True):
    """Automated scheduled scan profile with custom account, groups, keywords, and time slot."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(description="Tên lịch / Ca quét (VD: Ca sáng - Gia dụng)")
    account_id: Optional[int] = Field(default=None, description="ID tài khoản cào (None = tự động xoay vòng)")
    group_ids_json: str = Field(default="[]", description="JSON list of GroupItem IDs")
    keyword_ids_json: str = Field(default="[]", description="JSON list of KeywordItem IDs")
    interval_minutes: int = Field(default=10, description="Tần suất quét (phút)")
    start_time: str = Field(default="00:00", description="Khung giờ bắt đầu (HH:MM)")
    end_time: str = Field(default="23:59", description="Khung giờ kết thúc (HH:MM)")
    is_active: bool = Field(default=True, description="Trạng thái bật/tắt lịch")
    last_run_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class KeywordItem(SQLModel, table=True):
    """Target keywords to filter posts (if empty, all new posts are notified like in fbn)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str = Field(unique=True, description="Keyword or phrase")
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class SeenPost(SQLModel, table=True):
    """Seen posts database (deduplication store)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: str = Field(unique=True, index=True, description="Canonical Facebook post ID")
    group_name: str = Field(default="")
    group_id_val: str = Field(default="")
    author_name: str = Field(default="Ẩn danh")
    author_url: str = Field(default="", description="URL to author's posts in this group")
    content: str = Field(default="")
    post_url: str = Field(default="")
    matched_keywords: str = Field(default="")
    scraped_at: datetime = Field(default_factory=utc_now)
    is_notified: bool = Field(default=False)


class RunLog(SQLModel, table=True):
    """Execution history of check / monitor runs."""
    id: Optional[int] = Field(default=None, primary_key=True)
    run_type: str = Field(default="check", description="'check' (manual) or 'monitor' (background)")
    account_used: Optional[str] = Field(default=None, description="Account name used for this scan")
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: Optional[datetime] = Field(default=None)
    status: str = Field(default="running", description="'running', 'success', 'error', 'warning'")
    posts_found: int = Field(default=0)
    posts_new: int = Field(default=0)
    posts_sent: int = Field(default=0)
    message: str = Field(default="")
    error_detail: Optional[str] = Field(default=None)


from sqlalchemy import text


def init_db():
    """Create all tables and initialize default config if empty."""
    SQLModel.metadata.create_all(engine)

    # Safe column migrations for existing SQLite database
    with engine.connect() as conn:
        for col_stmt in [
            "ALTER TABLE appconfig ADD COLUMN active_account_id INTEGER",
            "ALTER TABLE groupitem ADD COLUMN member_count INTEGER",
            "ALTER TABLE groupitem ADD COLUMN privacy TEXT DEFAULT 'unknown'",
            "ALTER TABLE groupitem ADD COLUMN topic_name TEXT DEFAULT 'Chưa phân loại'",
            "ALTER TABLE groupitem ADD COLUMN is_joined BOOLEAN DEFAULT 0",
            "ALTER TABLE groupitem ADD COLUMN post_permission TEXT DEFAULT 'unknown'",
            "ALTER TABLE groupitem ADD COLUMN post_permission_text TEXT DEFAULT 'Chưa kiểm tra'",
            "ALTER TABLE groupitem ADD COLUMN comment_permission TEXT DEFAULT 'unknown'",
            "ALTER TABLE groupitem ADD COLUMN comment_permission_text TEXT DEFAULT 'Chưa kiểm tra'",
            "ALTER TABLE runlog ADD COLUMN account_used TEXT",
            "ALTER TABLE seenpost ADD COLUMN author_url TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(text(col_stmt))
                conn.commit()
            except Exception:
                pass
    with Session(engine) as session:
        # Seed default topics if none exist
        existing_topics = session.exec(select(TopicItem)).all()
        if not existing_topics:
            default_topics = [
                ("Điện máy & Gia dụng", "blue"),
                ("Việc làm & Tuyển dụng", "emerald"),
                ("Bất động sản & Nhà đất", "purple"),
                ("Kinh doanh & Bán lẻ", "amber"),
            ]
            for t_name, t_color in default_topics:
                session.add(TopicItem(name=t_name, color=t_color))
            session.commit()

        cfg = session.get(AppConfig, 1)
        if not cfg:
            cfg = AppConfig(id=1)
            session.add(cfg)
            session.commit()

        # Migrate existing fb_cookies from AppConfig to AccountItem if no accounts exist yet
        accounts = session.exec(select(AccountItem)).all()
        if not accounts and cfg.fb_cookies:
            from core.cookie_manager import parse_facebook_cookies
            _, c_user, _ = parse_facebook_cookies(cfg.fb_cookies)
            acc = AccountItem(
                name="Tài khoản #1",
                cookies=cfg.fb_cookies,
                c_user=c_user,
                is_active=True,
                status="ready",
            )
            session.add(acc)
            session.commit()


def get_db_session() -> Session:
    """Return an active SQLModel session."""
    return Session(engine)


def get_app_config() -> AppConfig:
    """Fetch current application configuration."""
    with Session(engine) as session:
        cfg = session.get(AppConfig, 1)
        if not cfg:
            cfg = AppConfig(id=1)
            session.add(cfg)
            session.commit()
            session.refresh(cfg)
        return cfg


def update_app_config(
    fb_cookies: Optional[str] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    scrape_interval_minutes: Optional[int] = None,
    max_posts_per_scan: Optional[int] = None,
    monitor_active: Optional[bool] = None,
    active_account_id: Optional[int] = None,
) -> AppConfig:
    """Update settings in database."""
    with Session(engine) as session:
        cfg = session.get(AppConfig, 1)
        if not cfg:
            cfg = AppConfig(id=1)
            session.add(cfg)

        if fb_cookies is not None:
            cfg.fb_cookies = fb_cookies.strip()
        if telegram_bot_token is not None:
            cfg.telegram_bot_token = telegram_bot_token.strip()
        if telegram_chat_id is not None:
            cfg.telegram_chat_id = telegram_chat_id.strip()
        if scrape_interval_minutes is not None:
            cfg.scrape_interval_minutes = max(1, scrape_interval_minutes)
        if max_posts_per_scan is not None:
            cfg.max_posts_per_scan = max(1, max_posts_per_scan)
        if monitor_active is not None:
            cfg.monitor_active = monitor_active
        if active_account_id is not None:
            cfg.active_account_id = active_account_id if active_account_id > 0 else None

        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        return cfg
