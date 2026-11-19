"""
Core job functions executed by APScheduler for fb-monitor.
"""

from datetime import datetime, timezone, date
from loguru import logger
from sqlmodel import select

from config import get_config
from storage.database import get_session
from storage.models import Group, Keyword, Post, ScrapeLog
from scraper.browser import BrowserManager
from scraper.group_scraper import GroupScraper
from scraper.post_data import PostData
from notifier.telegram import TelegramNotifier

config = get_config()


async def run_scrape_cycle() -> None:
    """
    Main scheduled job: scrape all active groups for all active keywords,
    deduplicate posts, save to DB, and send Telegram alerts.
    """
    logger.info("=== run_scrape_cycle started ===")
    total_found = 0
    total_sent = 0

    # 1. Load active groups and keywords (synchronous DB query)
    with get_session() as session:
        groups = session.exec(select(Group).where(Group.is_active == True)).all()
        keywords = session.exec(select(Keyword).where(Keyword.is_active == True)).all()

    if not groups:
        logger.warning("No active groups found — skipping cycle")
        return
    if not keywords:
        logger.warning("No active keywords found — skipping cycle")
        return

    keyword_texts = [kw.text for kw in keywords]
    logger.info(f"Scraping {len(groups)} group(s) with {len(keyword_texts)} keyword(s)")

    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    try:
        async with BrowserManager(session_file=config.fb_session_file, headless=True) as bm:
            page = await bm.get_page()
            scraper = GroupScraper(page=page, max_posts_per_group=config.max_posts_per_group)

            for group in groups:
                log_entry_id: int | None = None

                # 2. Create ScrapeLog entry with status="running"
                with get_session() as session:
                    log_entry = ScrapeLog(
                        group_id=group.id,
                        started_at=datetime.now(timezone.utc),
                        status="running",
                    )
                    session.add(log_entry)
                    session.flush()
                    session.refresh(log_entry)
                    log_entry_id = log_entry.id

                posts_found = 0
                posts_sent = 0

                try:
                    # 3. Scrape group
                    post_data_list: list[PostData] = await scraper.scrape_group(group, keyword_texts)
                    posts_found = len(post_data_list)

                    for post_data in post_data_list:
                        # 4. Dedup: check if post_id already in DB
                        saved_post_id: int | None = None
                        with get_session() as session:
                            existing = session.exec(
                                select(Post).where(Post.post_id == post_data.post_id)
                            ).first()
                            if existing:
                                logger.debug(f"Skipping duplicate post {post_data.post_id}")
                                continue

                            # Save new post
                            new_post = Post(
                                post_id=post_data.post_id,
                                group_id=group.id,
                                author_name=post_data.author_name,
                                content=post_data.content,
                                post_url=post_data.post_url,
                                scraped_at=datetime.now(timezone.utc),
                                is_sent=False,
                                matched_keywords=post_data.matched_keyword,
                            )
                            session.add(new_post)
                            session.flush()
                            session.refresh(new_post)
                            saved_post_id = new_post.id

                        # 5. Send Telegram alert for new post
                        if saved_post_id:
                            try:
                                sent_ok = await notifier.send_post_alert(post_data, group_name=group.name)
                                if sent_ok:
                                    with get_session() as session:
                                        p = session.get(Post, saved_post_id)
                                        if p:
                                            p.is_sent = True
                                            session.add(p)
                                    posts_sent += 1
                            except Exception as notify_err:
                                logger.error(f"Telegram alert failed for post {post_data.post_id}: {notify_err}")

                    # 6. Update group's last_scraped_at & ScrapeLog → success
                    with get_session() as session:
                        db_group = session.get(Group, group.id)
                        if db_group:
                            db_group.last_scraped_at = datetime.now(timezone.utc)
                            session.add(db_group)

                        if log_entry_id:
                            log_entry = session.get(ScrapeLog, log_entry_id)
                            if log_entry:
                                log_entry.finished_at = datetime.now(timezone.utc)
                                log_entry.posts_found = posts_found
                                log_entry.posts_sent = posts_sent
                                log_entry.status = "success"
                                session.add(log_entry)

                    logger.info(f"Group '{group.name}': found={posts_found}, sent={posts_sent}")
                    total_found += posts_found
                    total_sent += posts_sent

                except Exception as e:
                    logger.error(f"Error scraping group '{group.name}': {e}")
                    if log_entry_id:
                        try:
                            with get_session() as session:
                                log_entry = session.get(ScrapeLog, log_entry_id)
                                if log_entry:
                                    log_entry.finished_at = datetime.now(timezone.utc)
                                    log_entry.status = "error"
                                    log_entry.error_msg = str(e)
                                    session.add(log_entry)
                        except Exception as db_err:
                            logger.error(f"Failed to update ScrapeLog for group '{group.name}': {db_err}")

    except Exception as browser_err:
        logger.error(f"Failed to initialize Playwright browser: {browser_err}")

    # 7. Summary log
    logger.info(f"=== run_scrape_cycle finished — total found={total_found}, sent={total_sent} ===")


async def run_daily_summary() -> None:
    """
    Daily summary job: collect today's stats and send a Telegram summary.
    """
    logger.info("=== run_daily_summary started ===")

    today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)

    with get_session() as session:
        posts_today = session.exec(
            select(Post).where(Post.scraped_at >= today_start)
        ).all()
        sent_today = [p for p in posts_today if p.is_sent]

        errors_today = session.exec(
            select(ScrapeLog).where(
                ScrapeLog.started_at >= today_start,
                ScrapeLog.status == "error",
            )
        ).all()

        active_groups = session.exec(select(Group).where(Group.is_active == True)).all()
        active_keywords = session.exec(select(Keyword).where(Keyword.is_active == True)).all()

    stats = {
        "date": date.today().isoformat(),
        "posts_found": len(posts_today),
        "alerts_sent": len(sent_today),
        "errors": len(errors_today),
        "active_groups": len(active_groups),
        "active_keywords": len(active_keywords),
    }

    notifier = TelegramNotifier(
        bot_token=config.TELEGRAM_BOT_TOKEN,
        chat_id=config.TELEGRAM_CHAT_ID,
    )

    try:
        await notifier.send_summary(stats)
        logger.info(f"Daily summary sent: {stats}")
    except Exception as e:
        logger.error(f"Failed to send daily summary: {e}")
