from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Group(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    fb_url: str
    is_active: bool = Field(default=True)
    last_scraped_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=utc_now)


class Keyword(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str = Field(unique=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class Post(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    post_id: str = Field(unique=True)
    group_id: int = Field(foreign_key="group.id")
    author_name: Optional[str] = Field(default=None)
    content: str
    post_url: str
    scraped_at: datetime = Field(default_factory=utc_now)
    is_sent: bool = Field(default=False)
    matched_keywords: str = Field(default="")


class ScrapeLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="group.id")
    started_at: datetime
    finished_at: Optional[datetime] = Field(default=None)
    posts_found: int = Field(default=0)
    posts_sent: int = Field(default=0)
    status: str = Field(default="running")
    error_msg: Optional[str] = Field(default=None)
