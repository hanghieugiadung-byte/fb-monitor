"""
Telegram Notifier (with Apprise compatibility) for FB Monitor.
Uses httpx AsyncClient for reliable asynchronous delivery.
"""

import html
import re
from datetime import datetime
from typing import Optional, Tuple
import httpx
from loguru import logger


def parse_apprise_url(apprise_url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse Apprise format: tgram://BOT_TOKEN/CHAT_ID
    Returns (bot_token, chat_id)
    """
    if not apprise_url:
        return None, None
    m = re.match(r"^tgram://([^/]+)/(.+)$", apprise_url.strip())
    if m:
        return m.group(1), m.group(2)
    return None, None


def clean_html_content(raw_text: str) -> str:
    """Escape special characters for Telegram HTML parse_mode."""
    if not raw_text:
        return ""
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", "", raw_text)
    return html.escape(cleaned.strip())


async def test_telegram_connection(bot_token: str, chat_id: str) -> Tuple[bool, str]:
    """Send a test ping to Telegram to verify credentials."""
    if not bot_token or not chat_id:
        return False, "Chưa cấu hình Telegram Bot Token hoặc Chat ID."

    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    payload = {
        "chat_id": chat_id.strip(),
        "text": (
            "✅ <b>FB Monitor kết nối thành công!</b>\n\n"
            "🔔 Bot sẵn sàng gửi cảnh báo bài viết mới từ các Facebook Group của bạn."
        ),
        "parse_mode": "HTML",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True, "Kết nối Telegram thành công! Hãy kiểm tra tin nhắn bot vừa gửi."
            err = data.get("description", resp.text)
            return False, f"Telegram API từ chối: {err}"
    except Exception as e:
        return False, f"Lỗi kết nối tới Telegram: {str(e)}"


async def send_post_notification(
    bot_token: str,
    chat_id: str,
    group_name: str,
    author_name: str,
    content: str,
    post_url: str,
    matched_keyword: str = "",
    author_url: str = "",
) -> Tuple[bool, Optional[str]]:
    """
    Format and send a newly discovered post notification to Telegram.
    Includes canonical link directly to the post, and link to all posts by the author in the group.
    """
    if not bot_token or not chat_id:
        return False, "Thiếu Bot Token hoặc Chat ID."

    safe_content = clean_html_content(content)
    if len(safe_content) > 350:
        safe_content = safe_content[:350] + "..."

    kw_tag = f"🔑 <b>Từ khóa:</b> #{clean_html_content(matched_keyword)}\n" if matched_keyword else ""
    time_str = datetime.now().strftime("%d/%m/%Y %H:%M")

    author_clean = clean_html_content(author_name or "Ẩn danh")
    if author_url and author_name != "Ẩn danh":
        author_line = f'👤 <b>Người đăng:</b> <a href="{author_url}">{author_clean}</a> <i>(Xem bài trong nhóm ↗)</i>\n'
    else:
        author_line = f"👤 <b>Người đăng:</b> {author_clean}\n"

    text = (
        "🔔 <b>PHÁT HIỆN BÀI VIẾT MỚI!</b>\n\n"
        f"👥 <b>Nhóm:</b> {clean_html_content(group_name)}\n"
        f"{kw_tag}"
        f"{author_line}\n"
        f"📝 <b>Nội dung:</b>\n{safe_content or '<i>(Không có nội dung văn bản)</i>'}\n\n"
        f'🔗 <a href="{post_url}">Xem bài viết trên Facebook →</a>\n'
        f"⏰ <i>{time_str}</i>"
    )

    url = f"https://api.telegram.org/bot{bot_token.strip()}/sendMessage"
    
    inline_keyboard = [
        [
            {
                "text": "🔗 Mở bài viết gốc",
                "url": post_url if post_url.startswith("http") else f"https://www.facebook.com{post_url}",
            }
        ]
    ]
    if author_url and author_name != "Ẩn danh":
        short_name = author_name[:25]
        inline_keyboard.append([
            {
                "text": f"👤 Bài viết của {short_name} trong nhóm",
                "url": author_url if author_url.startswith("http") else f"https://www.facebook.com{author_url}",
            }
        ])

    payload = {
        "chat_id": chat_id.strip(),
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
        "reply_markup": {
            "inline_keyboard": inline_keyboard
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True, None
            return False, data.get("description", resp.text)
    except Exception as e:
        return False, str(e)
