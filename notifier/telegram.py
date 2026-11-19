"""
Telegram notification module for fb-monitor.
Sends alerts via raw Bot API using httpx AsyncClient.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Optional, Any

import httpx
from loguru import logger

from config import get_settings
from scraper.post_data import PostData
from notifier.formatter import clean_html, format_timestamp, truncate_content

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"
_MAX_RETRIES = 3
_RETRY_DELAY = 2  # seconds base delay, exponential backoff


class TelegramNotifier:
    """Sends Telegram messages via raw Bot API."""

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.bot_token: str = bot_token or settings.TELEGRAM_BOT_TOKEN
        self.chat_id: str = chat_id or settings.TELEGRAM_CHAT_ID

    def _api_url(self, method: str) -> str:
        return _TELEGRAM_API_BASE.format(token=self.bot_token, method=method)

    async def _send_request(
        self,
        method: str,
        payload: dict,
    ) -> Optional[dict]:
        """
        POST to Telegram Bot API with retry on transient failures.
        Returns the response JSON on success, None on failure after retries.
        """
        url = self._api_url(method)
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(url, json=payload)

                if response.status_code == 429:
                    # Rate limited — honour Retry-After header
                    retry_after = int(response.headers.get("Retry-After", _RETRY_DELAY * attempt))
                    logger.warning(
                        f"[Telegram] Rate limited. Retrying in {retry_after}s "
                        f"(attempt {attempt}/{_MAX_RETRIES})"
                    )
                    await asyncio.sleep(retry_after)
                    continue

                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    logger.error(f"[Telegram] API error: {data.get('description')}")
                    return None

                return data

            except httpx.TimeoutException as exc:
                logger.warning(
                    f"[Telegram] Timeout on attempt {attempt}/{_MAX_RETRIES}: {exc}"
                )
            except httpx.HTTPStatusError as exc:
                logger.error(
                    f"[Telegram] HTTP {exc.response.status_code} on attempt "
                    f"{attempt}/{_MAX_RETRIES}: {exc}"
                )
            except httpx.RequestError as exc:
                logger.warning(
                    f"[Telegram] Network error on attempt {attempt}/{_MAX_RETRIES}: {exc}"
                )

            if attempt < _MAX_RETRIES:
                await asyncio.sleep(_RETRY_DELAY * attempt)

        logger.error(f"[Telegram] Failed after {_MAX_RETRIES} attempts for method '{method}'")
        return None

    async def send_post_alert(self, post: Any, group_name: str = "") -> bool:
        """
        Send a formatted alert for a newly detected Facebook post.
        Accepts PostData dataclass, Post SQLModel, or duck-typed object.
        Returns True on success, False on failure.
        """
        grp_name = getattr(post, "group_name", None) or group_name or "Nhóm Facebook"
        kw = getattr(post, "matched_keyword", None) or getattr(post, "matched_keywords", "")
        author = getattr(post, "author_name", None) or "Ẩn danh"
        content_val = getattr(post, "content", "") or ""
        post_url_val = getattr(post, "post_url", "") or ""

        content_safe = clean_html(content_val)
        content_preview = truncate_content(content_safe, max_chars=300)
        timestamp_str = format_timestamp(datetime.now())

        text = (
            "🔔 <b>Bài viết mới phát hiện!</b>\n"
            "\n"
            f"👥 <b>Group:</b> {grp_name}\n"
            f"🔑 <b>Từ khóa:</b> #{kw}\n"
            f"👤 <b>Người đăng:</b> {author}\n"
            "\n"
            "📝 <b>Nội dung:</b>\n"
            f"{content_preview}\n"
            "\n"
            f'🔗 <a href="{post_url_val}">Xem bài viết gốc →</a>\n'
            f"⏰ {timestamp_str}"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "reply_markup": {
                "inline_keyboard": [
                    [
                        {
                            "text": "🔗 Mở bài viết",
                            "url": post_url_val,
                        }
                    ]
                ]
            },
        }

        result = await self._send_request("sendMessage", payload)
        if result:
            logger.info(
                f"[Telegram] Alert sent for post {post.post_id} "
                f"(group={post.group_name}, keyword={post.matched_keyword})"
            )
            return True
        else:
            logger.error(
                f"[Telegram] Failed to send alert for post {post.post_id}"
            )
            return False

    async def send_summary(self, stats: dict) -> bool:
        """
        Send a daily summary report.

        Expected keys in stats:
            date (str), total_posts (int), sent_count (int),
            active_groups (int), active_keywords (int)
        """
        date_str = stats.get("date", datetime.now().strftime("%d/%m/%Y"))
        total_posts = stats.get("total_posts", 0)
        sent_count = stats.get("sent_count", 0)
        active_groups = stats.get("active_groups", 0)
        active_keywords = stats.get("active_keywords", 0)

        text = (
            "📊 <b>Báo cáo tổng hợp</b>\n"
            f"📅 {date_str}\n"
            "\n"
            f"✅ Tổng bài mới: {total_posts}\n"
            f"📤 Đã gửi thông báo: {sent_count}\n"
            f"👥 Groups theo dõi: {active_groups}\n"
            f"🔑 Từ khóa đang dùng: {active_keywords}"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        result = await self._send_request("sendMessage", payload)
        if result:
            logger.info("[Telegram] Daily summary sent.")
            return True
        else:
            logger.error("[Telegram] Failed to send daily summary.")
            return False

    async def send_error_alert(self, error_msg: str) -> None:
        """Send a brief error notification to Telegram."""
        text = (
            "⚠️ <b>Lỗi hệ thống</b>\n"
            "\n"
            f"<code>{error_msg[:1000]}</code>"
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        result = await self._send_request("sendMessage", payload)
        if result:
            logger.info("[Telegram] Error alert sent.")
        else:
            logger.error(f"[Telegram] Failed to send error alert: {error_msg[:200]}")

    async def test_connection(self) -> bool:
        """
        Send a test message to verify the bot token and chat ID are valid.
        Returns True if successful, False otherwise.
        """
        text = (
            "✅ <b>fb-monitor kết nối thành công!</b>\n"
            "Bot đang hoạt động và sẵn sàng gửi thông báo."
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }

        result = await self._send_request("sendMessage", payload)
        if result:
            logger.info("[Telegram] Connection test passed.")
            return True
        else:
            logger.error("[Telegram] Connection test failed.")
            return False
