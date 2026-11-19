from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


# ── Group schemas ────────────────────────────────────────────────────────────

class GroupCreate(BaseModel):
    name: str
    fb_url: str

    @field_validator("fb_url")
    @classmethod
    def validate_fb_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        normalized = v.replace("https://", "").replace("http://", "").replace("www.", "")
        if not normalized.startswith("facebook.com/groups/"):
            raise ValueError("fb_url must start with facebook.com/groups/")
        return v


class GroupUpdate(BaseModel):
    name: Optional[str] = None
    fb_url: Optional[str] = None
    is_active: Optional[bool] = None

    @field_validator("fb_url")
    @classmethod
    def validate_fb_url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip().rstrip("/")
        normalized = v.replace("https://", "").replace("http://", "").replace("www.", "")
        if not normalized.startswith("facebook.com/groups/"):
            raise ValueError("fb_url must start with facebook.com/groups/")
        return v


class GroupResponse(BaseModel):
    id: int
    name: str
    fb_url: str
    is_active: bool
    last_scraped_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Keyword schemas ──────────────────────────────────────────────────────────

class KeywordCreate(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def normalize_text(cls, v: str) -> str:
        return v.strip().lower()


class KeywordUpdate(BaseModel):
    is_active: Optional[bool] = None


class KeywordResponse(BaseModel):
    id: int
    text: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class KeywordBulkCreate(BaseModel):
    texts: list[str]

    @field_validator("texts")
    @classmethod
    def normalize_texts(cls, v: list[str]) -> list[str]:
        return [t.strip().lower() for t in v if t.strip()]


# ── Post schemas ─────────────────────────────────────────────────────────────

class PostResponse(BaseModel):
    id: int
    post_id: str
    group_id: int
    author_name: Optional[str] = None
    content: str
    post_url: str
    scraped_at: datetime
    is_sent: bool
    matched_keywords: str

    model_config = {"from_attributes": True}


# ── ScrapeLog schemas ────────────────────────────────────────────────────────

class ScrapeLogResponse(BaseModel):
    id: int
    group_id: int
    started_at: datetime
    finished_at: Optional[datetime] = None
    posts_found: int
    posts_sent: int
    status: str
    error_msg: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Dashboard stats ──────────────────────────────────────────────────────────

class DashboardStats(BaseModel):
    total_groups: int
    active_groups: int
    total_keywords: int
    active_keywords: int
    posts_today: int
    posts_sent_today: int
    last_scrape_time: Optional[datetime] = None
