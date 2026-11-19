"""
GroupScraper: Searches a Facebook group by keyword and extracts matching posts.

Strategy
--------
For each keyword, we navigate to the group's search URL with chronological
ordering applied via Facebook's filter parameter.  We scroll a configurable
number of times, expanding "See more" snippets, and collect post data.

The scraper returns a list of :class:`~scraper.post_data.PostData` objects
ready for downstream deduplication and alerting.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import urllib.parse
from typing import TYPE_CHECKING

from loguru import logger
from playwright.async_api import Page, Error as PlaywrightError, TimeoutError as PWTimeoutError

from scraper.post_data import PostData

if TYPE_CHECKING:
    # Avoid a hard dependency on storage models at import time;
    # accept any object with .name and .fb_url attributes.
    from typing import Protocol

    class Group(Protocol):
        name: str
        fb_url: str  # e.g. "https://www.facebook.com/groups/123456789"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FB_BASE = "https://www.facebook.com"

# Facebook search filter that restricts results to group posts in
# chronological order.  The value is URL-encoded JSON understood by FB's
# internal search API.
_SEARCH_FILTERS = json.dumps(
    {
        "rtype:group_post:{}": json.dumps({"name": "rtype", "args": "group_post"}),
        "chronological:1:{}": json.dumps({"name": "chronological", "args": "1"}),
    }
)


def _build_search_url(group_id: str, keyword: str) -> str:
    """Return the Facebook group-search URL for a given keyword."""
    params = urllib.parse.urlencode(
        {"q": keyword, "filters": _SEARCH_FILTERS},
        quote_via=urllib.parse.quote,
    )
    return f"{_FB_BASE}/groups/{group_id}/search/?{params}"


def _extract_group_id(fb_url: str) -> str:
    """Extract the numeric or string group ID from a Facebook group URL."""
    # Handles both /groups/123456 and /groups/my-group-name
    match = re.search(r"/groups/([^/?#]+)", fb_url)
    if match:
        return match.group(1)
    raise ValueError(f"Cannot extract group ID from URL: {fb_url!r}")


def _extract_post_id(url: str) -> str:
    """Extract the post ID from various Facebook post URL patterns."""
    # Pattern: /posts/123, /permalink/123, ?story_fbid=123, fbid=123
    for pattern in (
        r"/posts/(\d+)",
        r"/permalink/(\d+)",
        r"story_fbid=(\d+)",
        r"fbid=(\d+)",
        r"[?&]id=(\d+)",
    ):
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    # Fallback: last path segment if numeric
    segments = [s for s in url.split("/") if s.isdigit()]
    if segments:
        return segments[-1]
    return url  # Return full URL as ID if nothing else matches


async def _jitter(low: float = 1.0, high: float = 3.0) -> None:
    """Sleep for a random duration to mimic human browsing pace."""
    await asyncio.sleep(random.uniform(low, high))


# ---------------------------------------------------------------------------
# GroupScraper
# ---------------------------------------------------------------------------


class GroupScraper:
    """Scrapes posts from a Facebook group that match one or more keywords.

    Parameters
    ----------
    page:
        A Playwright :class:`Page` instance (already authenticated).
    max_posts_per_group:
        Maximum number of posts to collect across all keywords for one group.
    scroll_count:
        How many times to scroll down the results page before stopping.
    """

    def __init__(
        self,
        page: Page,
        max_posts_per_group: int = 20,
        scroll_count: int = 3,
    ) -> None:
        self._page = page
        self._max_posts = max_posts_per_group
        self._scroll_count = scroll_count

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def scrape_group(self, group: "Group", keywords: list[str]) -> list[PostData]:
        """Search *group* for each keyword and return all matching posts.

        Parameters
        ----------
        group:
            ORM / dataclass object with `.name` and `.fb_url` attributes.
        keywords:
            List of search keywords to query within the group.

        Returns
        -------
        list[PostData]
            Deduplicated post objects (by post_id).
        """
        try:
            group_id = _extract_group_id(group.fb_url)
        except ValueError as exc:
            logger.error("GroupScraper: {}", exc)
            return []

        seen_ids: set[str] = set()
        results: list[PostData] = []

        for keyword in keywords:
            if len(results) >= self._max_posts:
                logger.info(
                    "[{}] Reached max posts limit ({}).", group.name, self._max_posts
                )
                break

            logger.info("[{}] Searching for keyword: {!r}", group.name, keyword)
            keyword_results = await self._search_keyword(
                group_id=group_id,
                group_name=group.name,
                keyword=keyword,
                seen_ids=seen_ids,
                remaining=self._max_posts - len(results),
            )
            results.extend(keyword_results)
            await _jitter()

        logger.info(
            "[{}] Scrape complete — {} post(s) collected.", group.name, len(results)
        )
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _search_keyword(
        self,
        group_id: str,
        group_name: str,
        keyword: str,
        seen_ids: set[str],
        remaining: int,
    ) -> list[PostData]:
        """Navigate to the search URL for one keyword and extract posts."""
        url = _build_search_url(group_id, keyword)
        posts: list[PostData] = []

        try:
            logger.debug("Navigating to: {}", url)
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await _jitter()
        except PWTimeoutError:
            logger.warning("Timeout loading search page for {!r} in {}", keyword, group_name)
            return posts
        except PlaywrightError as exc:
            logger.error("Navigation error for {!r}: {}", keyword, exc)
            return posts

        for scroll_idx in range(self._scroll_count):
            await self._expand_see_more()
            new_posts = await self._extract_posts(
                group_name=group_name,
                keyword=keyword,
                seen_ids=seen_ids,
            )
            posts.extend(new_posts)

            if len(posts) >= remaining:
                break

            if scroll_idx < self._scroll_count - 1:
                logger.debug("Scrolling down ({}/{})…", scroll_idx + 1, self._scroll_count)
                await self._scroll_down()
                await _jitter()

        return posts[:remaining]

    async def _expand_see_more(self) -> None:
        """Click all visible "See more" / "Xem thêm" links to reveal full post text."""
        selectors = [
            "div[data-ad-preview='message'] [role='button']:has-text('See more')",
            "div[data-ad-preview='message'] [role='button']:has-text('Xem thêm')",
            "[role='button']:has-text('See more')",
        ]
        for selector in selectors:
            try:
                buttons = await self._page.query_selector_all(selector)
                for btn in buttons:
                    try:
                        await btn.click(timeout=3_000)
                        await asyncio.sleep(0.3)
                    except PlaywrightError:
                        pass
            except PlaywrightError:
                pass

    async def _scroll_down(self) -> None:
        """Scroll the page down by one viewport height."""
        try:
            await self._page.evaluate("window.scrollBy(0, window.innerHeight)")
        except PlaywrightError as exc:
            logger.debug("Scroll failed: {}", exc)

    async def _extract_posts(
        self,
        group_name: str,
        keyword: str,
        seen_ids: set[str],
    ) -> list[PostData]:
        """Parse post elements on the current page and return new PostData items."""
        posts: list[PostData] = []

        # Facebook renders feed items inside role="article" elements
        try:
            article_elements = await self._page.query_selector_all("div[role='article']")
        except PlaywrightError as exc:
            logger.error("Failed to query post elements: {}", exc)
            return posts

        for article in article_elements:
            try:
                post = await self._parse_article(
                    article, group_name=group_name, keyword=keyword
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("Could not parse article: {}", exc)
                continue

            if post is None:
                continue
            if post.post_id in seen_ids:
                continue

            seen_ids.add(post.post_id)
            posts.append(post)

        return posts

    async def _parse_article(self, article, group_name: str, keyword: str):
        """Extract fields from a single article element.

        Returns None if no usable post URL can be found.
        """
        # --- Post URL & ID ---
        post_url = ""
        post_id = ""

        # Look for a permalink anchor (timestamp link pattern)
        link_handles = await article.query_selector_all("a[href*='/posts/'], a[href*='/permalink/']")
        if not link_handles:
            # Broader fallback: any anchor that contains a numeric post-like path
            link_handles = await article.query_selector_all("a[href*='story_fbid']")

        for lh in link_handles:
            href = await lh.get_attribute("href")
            if href:
                post_url = href if href.startswith("http") else _FB_BASE + href
                post_id = _extract_post_id(post_url)
                if post_id:
                    break

        if not post_id:
            return None

        # --- Author name ---
        author_name = ""
        author_selectors = [
            "a[role='link'] strong",
            "h2 a",
            "strong a",
            "a[href*='/profile.php'] strong",
        ]
        for sel in author_selectors:
            el = await article.query_selector(sel)
            if el:
                author_name = (await el.inner_text()).strip()
                if author_name:
                    break

        # --- Content ---
        content = ""
        content_selectors = [
            "div[data-ad-preview='message']",
            "div[dir='auto']",
        ]
        for sel in content_selectors:
            el = await article.query_selector(sel)
            if el:
                content = (await el.inner_text()).strip()
                if content:
                    break

        return PostData(
            post_id=post_id,
            author_name=author_name,
            content=content,
            post_url=post_url,
            group_name=group_name,
            matched_keyword=keyword,
        )
