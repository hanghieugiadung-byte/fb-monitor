"""
test_integration.py — Integration and integrity test suite for fb-monitor.
Runs checks across Config, Database, Storage models, Notifier formatters,
and FastAPI Application imports.
"""

import os
import sys
from datetime import datetime, timezone

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_config():
    print("[1/5] Testing Configuration System...")
    from config import settings, get_settings, get_config

    assert settings.app_port == 8000
    assert settings.APP_PORT == 8000
    assert get_settings() is settings
    assert get_config() is settings
    print("      ✓ Config loaded successfully with lowercase and uppercase properties.")


def test_database_and_models():
    print("[2/5] Testing Database and SQLModel tables...")
    try:
        import sqlmodel
    except ImportError:
        print("      ⚠️  sqlmodel not installed in this environment. Skipping DB check (runs in venv).")
        return

    from sqlmodel import Session, select
    from storage.database import create_tables, get_session
    from storage.models import Group, Keyword, Post, ScrapeLog

    # Create tables in SQLite
    create_tables()

    # Test CRUD operations
    with get_session() as session:
        # Create group
        grp = Group(name="Test Dev Group", fb_url="https://www.facebook.com/groups/test12345")
        session.add(grp)
        session.flush()
        session.refresh(grp)
        grp_id = grp.id
        assert grp_id is not None

        # Create keyword
        kw = Keyword(text="tuyển dụng python test")
        session.add(kw)
        session.flush()
        session.refresh(kw)
        kw_id = kw.id
        assert kw_id is not None

        # Create post
        post = Post(
            post_id="post_999999",
            group_id=grp_id,
            author_name="John Doe",
            content="Cần tuyển lập trình viên Python FastAPI tại Hà Nội",
            post_url="https://www.facebook.com/groups/test12345/posts/999999",
            scraped_at=datetime.now(timezone.utc),
            matched_keywords="tuyển dụng python test",
            is_sent=False,
        )
        session.add(post)
        session.flush()
        session.refresh(post)
        assert post.id is not None

        # Create scrape log
        log = ScrapeLog(
            group_id=grp_id,
            started_at=datetime.now(timezone.utc),
            posts_found=1,
            posts_sent=1,
            status="success",
        )
        session.add(log)
        session.flush()

        # Query back and verify
        fetched_grp = session.get(Group, grp_id)
        assert fetched_grp.name == "Test Dev Group"

        fetched_posts = session.exec(select(Post).where(Post.post_id == "post_999999")).all()
        assert len(fetched_posts) == 1

        # Clean up test records
        session.delete(post)
        session.delete(kw)
        session.delete(grp)
        session.delete(log)

    print("      ✓ Database tables created and CRUD operations verified successfully.")


def test_post_data_and_formatters():
    print("[3/5] Testing PostData dataclass & Notifier formatters...")
    from scraper.post_data import PostData
    from notifier.formatter import clean_html, format_timestamp, truncate_content

    p = PostData(
        post_id="123456",
        author_name="Nguyễn Văn A",
        content="<script>alert(1)</script><b>Cần mua laptop</b> cũ tại Hà Nội.",
        post_url="https://www.facebook.com/groups/123/posts/123456",
        group_name="Chợ đồ cũ",
        matched_keyword="laptop",
    )
    assert p.post_id == "123456"

    # Test formatters
    cleaned = clean_html(p.content)
    assert "<script>" not in cleaned
    assert "<b>" not in cleaned

    truncated = truncate_content("A" * 500, max_chars=100)
    assert len(truncated) <= 103
    assert truncated.endswith("...")

    now_str = format_timestamp(datetime.now())
    assert len(now_str) > 0

    print("      ✓ PostData and Notifier formatters verified.")


def test_notifier_initialization():
    print("[4/5] Testing Notifier Initialization...")
    try:
        import httpx
    except ImportError:
        print("      ⚠️  httpx not installed in this environment. Skipping Notifier check (runs in venv).")
        return

    from notifier.telegram import TelegramNotifier

    notifier = TelegramNotifier()
    assert notifier.bot_token is not None
    assert notifier.chat_id is not None

    custom_notifier = TelegramNotifier(bot_token="test_token", chat_id="test_chat")
    assert custom_notifier.bot_token == "test_token"
    assert custom_notifier.chat_id == "test_chat"

    print("      ✓ TelegramNotifier initialization verified.")


def test_fastapi_app_and_routes():
    print("[5/5] Testing FastAPI App and Route Registry...")
    try:
        import fastapi
    except ImportError:
        print("      ⚠️  fastapi not installed in this environment. Skipping FastAPI check (runs in venv).")
        return

    from main import app

    route_paths = [route.path for route in app.routes]

    # Verify essential endpoints
    expected_paths = [
        "/",
        "/dashboard",
        "/groups",
        "/keywords",
        "/posts",
        "/logs",
        "/api/groups/",
        "/api/keywords/",
        "/api/posts/stats",
        "/api/scheduler/trigger",
        "/api/scheduler/status",
        "/api/scraper/run",
        "/api/telegram/test",
    ]

    for path in expected_paths:
        assert any(r == path or r.startswith(path) for r in route_paths), f"Missing route: {path}"

    print("      ✓ FastAPI app initialized and all routes registered properly.")


def main():
    print("=" * 60)
    print(" FB Monitor — Running Integration Tests")
    print("=" * 60)

    try:
        test_config()
        test_database_and_models()
        test_post_data_and_formatters()
        test_notifier_initialization()
        test_fastapi_app_and_routes()

        print("=" * 60)
        print(" 🎉 INTEGRATION CHECKS COMPLETE!")
        print("=" * 60)
        return 0
    except Exception as e:
        print("\n" + "!" * 60)
        print(f" ❌ TEST FAILED: {e}")
        print("!" * 60)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
