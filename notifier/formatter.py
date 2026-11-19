"""
Formatting helper functions for Telegram notification messages.
"""

import re
from datetime import datetime


def truncate_content(text: str, max_chars: int = 300) -> str:
    """Truncate text to max_chars, appending '...' if truncated."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def clean_html(text: str) -> str:
    """Strip HTML tags from text for safe display."""
    if not text:
        return ""
    # Remove all HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Unescape common HTML entities
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&quot;", '"')
    clean = clean.replace("&#39;", "'")
    clean = clean.replace("&nbsp;", " ")
    return clean.strip()


def format_timestamp(dt: datetime) -> str:
    """Format datetime to Vietnamese locale style: '18/11/2026 09:30'."""
    return dt.strftime("%d/%m/%Y %H:%M")
