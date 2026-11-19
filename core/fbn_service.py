"""
Orchestration service for FB Monitor (fbn style).
Implements:
1. Multi-account pool & rotation
2. Selective group & keyword scraping
3. Group discovery search with criteria
4. run_doctor() -> Diagnostics (Chromium, Cookie, Telegram)
5. run_check_once() -> Single scan run across selected groups with live log
6. start_monitor() / stop_monitor() -> Continuous background polling
"""

import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from loguru import logger
from sqlmodel import select

from core.db import (
    get_db_session,
    get_app_config,
    AppConfig,
    AccountItem,
    GroupItem,
    KeywordItem,
    SeenPost,
    RunLog,
    MonitorSchedule,
    TopicItem,
    utc_now,
)
from core.fbn_scraper import FbnScraper
from core.notifier import test_telegram_connection, send_post_notification

# Global scheduler reference
_monitor_task: Optional[asyncio.Task] = None
_is_monitoring: bool = False


def get_active_scraping_account(account_id: Optional[int] = None) -> Tuple[Optional[AccountItem], str]:
    """
    Select an account to use for scraping:
    1. If account_id specified, use it.
    2. Else if cfg.active_account_id set, use it.
    3. Else round-robin: pick active account with oldest last_used_at.
    4. Fallback to AppConfig.fb_cookies.
    Returns: (account_item_or_none, cookies_string)
    """
    cfg = get_app_config()

    with get_db_session() as session:
        if account_id:
            acc = session.get(AccountItem, account_id)
            if acc and acc.cookies:
                return acc, acc.cookies

        if cfg.active_account_id:
            acc = session.get(AccountItem, cfg.active_account_id)
            if acc and acc.cookies and acc.is_active:
                return acc, acc.cookies

        # Round-robin across active accounts
        active_accounts = session.exec(
            select(AccountItem).where(AccountItem.is_active == True).order_by(AccountItem.last_used_at.asc())
        ).all()
        if active_accounts:
            picked = active_accounts[0]
            return picked, picked.cookies

    # Fallback to AppConfig.fb_cookies
    return None, cfg.fb_cookies


async def run_doctor(account_id: Optional[int] = None) -> Dict[str, Any]:
    """Execute complete system diagnostics."""
    cfg = get_app_config()
    acc, cookies = get_active_scraping_account(account_id)

    # 1. Run Facebook & Browser check
    scraper = FbnScraper(raw_cookies=cookies)
    fb_diag = await scraper.run_doctor()

    # Update account status in DB if specific account
    if acc:
        with get_db_session() as session:
            db_acc = session.get(AccountItem, acc.id)
            if db_acc:
                db_acc.status = "valid" if fb_diag["session_valid"] else "expired"
                db_acc.status_msg = fb_diag["message"]
                if fb_diag["c_user"]:
                    db_acc.c_user = fb_diag["c_user"]
                session.add(db_acc)
                session.commit()

    # 2. Run Telegram check
    tg_ok, tg_msg = await test_telegram_connection(
        bot_token=cfg.telegram_bot_token,
        chat_id=cfg.telegram_chat_id,
    )

    # 3. Check targets in database
    with get_db_session() as session:
        groups_count = len(session.exec(select(GroupItem).where(GroupItem.is_active == True)).all())
        keywords_count = len(session.exec(select(KeywordItem).where(KeywordItem.is_active == True)).all())
        seen_count = len(session.exec(select(SeenPost)).all())
        accounts_count = len(session.exec(select(AccountItem).where(AccountItem.is_active == True)).all())

    return {
        "browser_ok": fb_diag["browser_ok"],
        "browser_version": fb_diag["browser_version"],
        "cookie_ok": fb_diag["session_valid"],
        "cookie_msg": fb_diag["message"],
        "c_user": fb_diag["c_user"],
        "account_name": acc.name if acc else "Tài khoản mặc định",
        "active_accounts": accounts_count,
        "telegram_ok": tg_ok,
        "telegram_msg": tg_msg,
        "active_groups": groups_count,
        "active_keywords": keywords_count,
        "seen_posts_total": seen_count,
        "monitor_active": cfg.monitor_active,
    }


async def discover_groups(
    keyword: str,
    min_members: int = 0,
    privacy_filter: str = "all",
    max_results: int = 15,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Search & discover Facebook groups matching keyword and criteria."""
    acc, cookies = get_active_scraping_account(account_id)
    if not cookies:
        return {
            "status": "error",
            "message": "Chưa có tài khoản Facebook nào có Cookie để thực hiện tìm kiếm nhóm.",
            "groups": [],
            "logs": ["LỖI: Chưa có Cookie hợp lệ."],
        }

    scraper = FbnScraper(raw_cookies=cookies)
    groups, logs = await scraper.search_facebook_groups(
        keyword=keyword,
        min_members=min_members,
        privacy_filter=privacy_filter,
        max_results=max_results,
    )
    return {
        "status": "success",
        "account_used": acc.name if acc else "Mặc định",
        "groups": groups,
        "logs": logs,
    }


async def run_check_once(
    dry_run: bool = False,
    run_type: str = "check",
    group_ids: Optional[List[int]] = None,
    keyword_ids: Optional[List[int]] = None,
    account_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Perform a scan across selected groups and keywords.
    Deduplicates with SeenPost table and sends Telegram notifications.
    """
    cfg = get_app_config()
    acc, cookies = get_active_scraping_account(account_id)
    account_label = acc.name if acc else "Tài khoản mặc định"

    logs: List[str] = []
    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Khởi động quét ({'Quét thử - Dry Run' if dry_run else 'Quét thật'})")
    logs.append(f"Tài khoản thực hiện: {account_label}")

    if not cookies:
        logs.append("LỖI: Chưa có Cookie tài khoản Facebook nào hợp lệ. Vui lòng thêm tài khoản trước.")
        return {
            "status": "error",
            "posts_found": 0,
            "posts_new": 0,
            "posts_sent": 0,
            "logs": logs,
        }

    # Load targets (with selective filtering)
    with get_db_session() as session:
        if group_ids:
            groups = session.exec(select(GroupItem).where(GroupItem.id.in_(group_ids))).all()
        else:
            groups = session.exec(select(GroupItem).where(GroupItem.is_active == True)).all()

        if keyword_ids is not None:
            keywords = session.exec(select(KeywordItem).where(KeywordItem.id.in_(keyword_ids))).all()
        else:
            keywords = session.exec(select(KeywordItem).where(KeywordItem.is_active == True)).all()

    if not groups:
        logs.append("⚠️ Không có nhóm nào được chọn để quét. Vui lòng chọn ít nhất 1 nhóm.")
        return {
            "status": "warning",
            "posts_found": 0,
            "posts_new": 0,
            "posts_sent": 0,
            "logs": logs,
        }

    keyword_list = [kw.text.strip() for kw in keywords if kw.text.strip()]
    if keyword_list:
        logs.append(f"Lọc theo {len(keyword_list)} từ khóa: {', '.join(keyword_list[:6])}...")
    else:
        logs.append("Không đặt từ khóa: Sẽ thu thập tất cả bài viết mới trong nhóm (chuẩn fbn).")

    scraper = FbnScraper(raw_cookies=cookies)
    total_found = 0
    total_new = 0
    total_sent = 0

    for grp in groups:
        logs.append(f"--- Đang quét: {grp.name} ---")
        posts, scrape_logs = await scraper.scrape_group(
            group_url_or_id=grp.fb_url,
            group_name=grp.name,
            keywords=keyword_list,
            max_posts=cfg.max_posts_per_scan,
        )
        logs.extend(scrape_logs)
        total_found += len(posts)

        with get_db_session() as session:
            for p in posts:
                post_id = p["post_id"]

                # Check if seen
                existing = session.exec(select(SeenPost).where(SeenPost.post_id == post_id)).first()
                if existing:
                    logs.append(f"○ Bỏ qua bài đã quét trước đó: ID {post_id}")
                    continue

                total_new += 1
                logs.append(f"★ Phát hiện bài mới: '{p['author_name']}': {p['content'][:50]}... | Link: {p['post_url']}")

                # Send notification if not dry_run
                sent_ok = False
                if not dry_run:
                    sent_ok, err_msg = await send_post_notification(
                        bot_token=cfg.telegram_bot_token,
                        chat_id=cfg.telegram_chat_id,
                        group_name=p["group_name"],
                        author_name=p["author_name"],
                        content=p["content"],
                        post_url=p["post_url"],
                        matched_keyword=p["matched_keyword"],
                        author_url=p.get("author_url", ""),
                    )
                    if sent_ok:
                        total_sent += 1
                        logs.append(f"  ✓ Đã gửi thông báo Telegram cho bài {post_id}")
                    else:
                        logs.append(f"  ✕ Gửi Telegram thất bại: {err_msg}")

                # Save to SeenPost
                new_seen = SeenPost(
                    post_id=post_id,
                    group_name=p["group_name"],
                    group_id_val=p["group_id"],
                    author_name=p["author_name"],
                    author_url=p.get("author_url", ""),
                    content=p["content"],
                    post_url=p["post_url"],
                    matched_keywords=p["matched_keyword"],
                    is_notified=sent_ok,
                )
                session.add(new_seen)

            # Update group last_scraped_at
            db_grp = session.get(GroupItem, grp.id)
            if db_grp:
                db_grp.last_scraped_at = utc_now()
                session.add(db_grp)

            session.commit()

    # Update account last_used_at
    if acc:
        with get_db_session() as session:
            db_acc = session.get(AccountItem, acc.id)
            if db_acc:
                db_acc.last_used_at = utc_now()
                session.add(db_acc)
                session.commit()

    logs.append(f"[{datetime.now().strftime('%H:%M:%S')}] Hoàn tất: Tìm thấy {total_found} bài, {total_new} bài mới, đã gửi {total_sent} cảnh báo.")

    # Record RunLog
    with get_db_session() as session:
        run_log = RunLog(
            run_type=run_type,
            account_used=account_label,
            started_at=utc_now(),
            finished_at=utc_now(),
            status="success" if total_sent > 0 or total_new == 0 else "warning",
            posts_found=total_found,
            posts_new=total_new,
            posts_sent=total_sent,
            message=f"Tìm thấy {total_found} bài, {total_new} bài mới, gửi {total_sent} cảnh báo.",
        )
        session.add(run_log)
        session.commit()

    return {
        "status": "success",
        "posts_found": total_found,
        "posts_new": total_new,
        "posts_sent": total_sent,
        "logs": logs,
    }


async def check_group_permission_service(group_id: int, account_id: Optional[int] = None) -> Dict[str, Any]:
    """Inspect and update post & comment approval permissions for a specific group."""
    with get_db_session() as session:
        grp = session.get(GroupItem, group_id)
        if not grp:
            return {"status": "error", "message": "Không tìm thấy nhóm"}
        fb_url = grp.fb_url

    acc, cookies = get_active_scraping_account(account_id)
    if not cookies:
        return {"status": "error", "message": "Chưa có tài khoản Facebook với cookie hợp lệ"}

    scraper = FbnScraper(raw_cookies=cookies)
    perm_res = await scraper.check_group_permissions(fb_url)

    # Save to DB
    with get_db_session() as session:
        db_grp = session.get(GroupItem, group_id)
        if db_grp:
            db_grp.post_permission = perm_res.get("post_permission", "unknown")
            db_grp.post_permission_text = perm_res.get("post_permission_text", "Chưa rõ")
            db_grp.comment_permission = perm_res.get("comment_permission", "open")
            db_grp.comment_permission_text = perm_res.get("comment_permission_text", "Bình luận tự do")
            session.add(db_grp)
            session.commit()
            session.refresh(db_grp)
            return {
                "status": "success",
                "post_permission": db_grp.post_permission,
                "post_permission_text": db_grp.post_permission_text,
                "comment_permission": db_grp.comment_permission,
                "comment_permission_text": db_grp.comment_permission_text,
                "group": db_grp.model_dump(),
                "perm": perm_res,
            }

    return {"status": "error", "message": "Lỗi lưu quyền nhóm"}


async def _background_monitor_loop():
    """Background worker that continuously polls groups according to configured schedules or default interval."""
    global _is_monitoring
    _is_monitoring = True
    logger.info("Background monitor started.")
    last_default_run = None

    while _is_monitoring:
        cfg = get_app_config()
        if not cfg.monitor_active:
            logger.info("Monitor flag is false in config. Stopping monitor loop.")
            break

        now_dt = datetime.now()
        now_time_str = now_dt.strftime("%H:%M")

        # 1. Fetch active schedules from DB
        with get_db_session() as session:
            schedules = session.exec(select(MonitorSchedule).where(MonitorSchedule.is_active == True)).all()

        if schedules:
            for sched in schedules:
                if not _is_monitoring:
                    break

                # Time window check (e.g. 08:00 -> 18:00)
                in_window = True
                if sched.start_time and sched.end_time:
                    if sched.start_time <= sched.end_time:
                        in_window = sched.start_time <= now_time_str <= sched.end_time
                    else:
                        in_window = now_time_str >= sched.start_time or now_time_str <= sched.end_time

                if not in_window:
                    continue

                # Interval check
                should_run = False
                if not sched.last_run_at:
                    should_run = True
                else:
                    elapsed_min = (utc_now() - sched.last_run_at).total_seconds() / 60.0
                    if elapsed_min >= sched.interval_minutes:
                        should_run = True

                if should_run:
                    logger.info(f"Triggering scheduled scan: '{sched.name}' (Account ID: {sched.account_id})")
                    try:
                        import json
                        grp_ids = json.loads(sched.group_ids_json) if sched.group_ids_json else None
                        kw_ids = json.loads(sched.keyword_ids_json) if sched.keyword_ids_json else None

                        await run_check_once(
                            dry_run=False,
                            run_type=f"schedule:{sched.name}",
                            group_ids=grp_ids if grp_ids else None,
                            keyword_ids=kw_ids if kw_ids else None,
                            account_id=sched.account_id,
                        )

                        with get_db_session() as s2:
                            db_sched = s2.get(MonitorSchedule, sched.id)
                            if db_sched:
                                db_sched.last_run_at = utc_now()
                                s2.add(db_sched)
                                s2.commit()
                    except Exception as sched_err:
                        logger.error(f"Error executing schedule {sched.name}: {sched_err}")
        else:
            # Fallback: run default monitor scan cycle adhering to scrape_interval_minutes
            now_utc = utc_now()
            should_run_default = False
            if last_default_run is None:
                should_run_default = True
            else:
                elapsed_min = (now_utc - last_default_run).total_seconds() / 60.0
                if elapsed_min >= max(1, cfg.scrape_interval_minutes):
                    should_run_default = True

            if should_run_default:
                try:
                    logger.info("Monitor default cycle triggered.")
                    last_default_run = now_utc
                    await run_check_once(dry_run=False, run_type="monitor")
                except Exception as e:
                    logger.error(f"Error in monitor cycle: {e}")

        # Sleep in small slices for responsiveness
        for _ in range(30):
            if not _is_monitoring:
                break
            await asyncio.sleep(1)

    _is_monitoring = False
    logger.info("Background monitor stopped.")


def start_monitor():
    """Start the background monitor task."""
    global _monitor_task, _is_monitoring
    if _monitor_task and not _monitor_task.done():
        return
    _is_monitoring = True
    _monitor_task = asyncio.create_task(_background_monitor_loop())


def stop_monitor():
    """Stop the background monitor task."""
    global _is_monitoring
    _is_monitoring = False


def is_monitoring() -> bool:
    """Check if background monitor is actively running."""
    return _is_monitoring
