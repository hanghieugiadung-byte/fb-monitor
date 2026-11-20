"""
Playwright-based Facebook Group Scraper adhering to the `viseshrp/fbn` architecture.
Uses mobile layout emulation (m.facebook.com), chronological sorting,
cookie session injection, post card parsing, and group discovery.
"""

import asyncio
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple, Any
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from core.cookie_manager import parse_facebook_cookies


CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-blink-features=AutomationControlled",
]

STEALTH_INIT_SCRIPT = """
try {
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
    });
} catch (_) {}
"""


def extract_group_identifier(raw_url_or_id: str) -> str:
    """Extract clean group ID or alias from URL or raw ID."""
    raw = raw_url_or_id.strip()
    if raw.isdigit():
        return raw

    # Match /groups/<id>
    m = re.search(r"facebook\.com/groups/([^/?#]+)", raw)
    if m:
        return m.group(1).strip()

    # Clean stripped url
    cleaned = raw.rstrip("/").split("/")[-1]
    return cleaned


def parse_member_count(text: str) -> int:
    """Parses member count string like '12K thành viên', '1.5M members', '500 thành viên' into integer."""
    if not text:
        return 0
    m = re.search(r"([\d\.,]+)\s*([KkMmTr])?", text)
    if not m:
        return 0
    num_str = m.group(1).replace(",", "") if "," in m.group(1) and "." not in m.group(1) else m.group(1).replace(",", ".")
    unit = (m.group(2) or "").upper()
    multiplier = 1
    if unit in ("K",):
        multiplier = 1_000
    elif unit in ("M", "TR"):
        multiplier = 1_000_000
    try:
        return int(float(num_str) * multiplier)
    except ValueError:
        return 0


def extract_post_id_from_url(url: str) -> Optional[str]:
    """
    Extract authoritative Facebook post ID from various Facebook link formats.
    Supported patterns:
      - /posts/<id>
      - /permalink/<id>
      - story_fbid=<id>
      - view=permalink&id=<id>
      - multi_permalinks=<id>
      - set=gm.<id> or set=pcb.<id>
      - /story/<id>
      - fbid=<id> (excluding profile/user links)
    """
    if not url:
        return None

    patterns = [
        r"/posts/(\d+)",
        r"/permalink/(\d+)",
        r"[?&]story_fbid=(\d+)",
        r"[?&]view=permalink&id=(\d+)",
        r"(?:[?&/]|)multi_permalinks=(\d+)",
        r"[?&]set=(?:gm|pcb)\.(\d+)",
        r"/story/(\d+)",
    ]
    for pat in patterns:
        m = re.search(pat, url)
        if m:
            return m.group(1)

    # Fallback to fbid if long enough and not user profile or photo download
    if "/profile.php" not in url and "user.php" not in url and "/photos/" not in url:
        m_fbid = re.search(r"[?&]fbid=(\d{8,})", url)
        if m_fbid:
            return m_fbid.group(1)

    return None


def extract_post_id_from_ft(ft_str: str) -> Optional[str]:
    """
    Extract Facebook post ID from data-ft attribute (JSON or regex fallback).
    Checks top_level_post_id, mf_story_key, tl_objid, story_fbid, story_fbids.
    """
    if not ft_str:
        return None
    import json
    try:
        data = json.loads(ft_str)
        candidates = [
            data.get("top_level_post_id"),
            data.get("mf_story_key"),
            data.get("tl_objid"),
            data.get("story_fbid"),
            data.get("story_fbids"),
        ]
        for c in candidates:
            if isinstance(c, list) and c:
                c = c[0]
            if c is not None and str(c).strip().isdigit():
                return str(c).strip()
    except Exception:
        pass

    # Regex fallback on raw JSON string
    m = re.search(r'"(?:top_level_post_id|mf_story_key|tl_objid|story_fbid)":\s*"?(\d+)"?', ft_str)
    if m:
        return m.group(1)
    return None


def build_canonical_post_url(clean_group_id: str, post_id: Optional[str], permalink: Optional[str] = None) -> str:
    """
    Build authoritative, canonical post URL pointing directly to the exact post on Facebook.
    Format: https://www.facebook.com/groups/<group_id>/posts/<post_id>/
    """
    if post_id and str(post_id).isdigit():
        return f"https://www.facebook.com/groups/{clean_group_id}/posts/{post_id}/"

    if permalink:
        extracted = extract_post_id_from_url(permalink)
        if extracted:
            return f"https://www.facebook.com/groups/{clean_group_id}/posts/{extracted}/"

        if permalink.startswith("http://") or permalink.startswith("https://"):
            # Normalize to www.facebook.com for desktop/mobile compatibility
            return permalink.replace("://m.facebook.com", "://www.facebook.com").replace("://mbasic.facebook.com", "://www.facebook.com")
        elif permalink.startswith("/"):
            return f"https://www.facebook.com{permalink}"

    return f"https://www.facebook.com/groups/{clean_group_id}/"


def build_author_group_url(
    clean_group_id: str,
    author_id: Optional[str] = None,
    author_name: str = "",
    author_href: Optional[str] = None,
) -> str:
    """
    Construct authoritative link pointing to all posts by this author inside the specific group.
    Format: https://www.facebook.com/groups/<group_id>/user/<author_id>/
    Or search within group: https://www.facebook.com/groups/<group_id>/search/?q=<author_name>
    """
    if author_id and str(author_id).isdigit():
        return f"https://www.facebook.com/groups/{clean_group_id}/user/{author_id}/"

    if author_href:
        # Check /groups/<id>/user/<uid>
        m_user = re.search(r"/user/([^/?#]+)", author_href)
        if m_user:
            return f"https://www.facebook.com/groups/{clean_group_id}/user/{m_user.group(1)}/"
        # Check profile.php?id=<uid>
        m_prof = re.search(r"profile\.php\?id=(\d+)", author_href)
        if m_prof:
            return f"https://www.facebook.com/groups/{clean_group_id}/user/{m_prof.group(1)}/"
        # If relative user handle like /nguyenvana
        if author_href.startswith("/"):
            slug = author_href.strip("/").split("?")[0].split("/")[0]
            if slug and slug not in ("groups", "story.php", "photo.php", "hashtag", "watch", "home.php"):
                return f"https://www.facebook.com/groups/{clean_group_id}/user/{slug}/"

    clean_name = (author_name or "").strip()
    if clean_name and clean_name.lower() not in (
        "ẩn danh",
        "thành viên ẩn danh",
        "người tham gia ẩn danh",
        "anonymous participant",
        "facebook user",
    ):
        return f"https://www.facebook.com/groups/{clean_group_id}/search/?q={urllib.parse.quote(clean_name)}"

    return f"https://www.facebook.com/groups/{clean_group_id}/"


class FbnScraper:
    """
    High-performance, resilient Facebook scraper inspired by viseshrp/fbn.
    """

    def __init__(self, raw_cookies: str, headless: bool = True):
        self.raw_cookies = raw_cookies
        self.headless = headless
        self.cookies_list, self.c_user, self.cookie_error = parse_facebook_cookies(raw_cookies)

    async def run_doctor(self) -> Dict[str, Any]:
        """
        Doctor diagnostics command (fbn doctor):
        1. Checks Chromium launch.
        2. Injects cookies and tests Facebook session status.
        3. Detects if logged in, redirected to login, or blocked by checkpoint.
        """
        report: Dict[str, Any] = {
            "browser_ok": False,
            "browser_version": "",
            "cookie_format_ok": bool(self.cookies_list and not self.cookie_error),
            "c_user": self.c_user,
            "session_valid": False,
            "page_title": "",
            "final_url": "",
            "message": "",
        }

        if not self.cookies_list:
            report["message"] = self.cookie_error or "Chưa cấu hình Cookie Facebook."
            return report

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS,
                )
                report["browser_ok"] = True
                report["browser_version"] = browser.version

                # Emulate mobile layout
                device = p.devices.get("Pixel 7") or p.devices["Pixel 5"]
                context = await browser.new_context(
                    **device,
                    locale="vi-VN",
                )
                await context.add_init_script(STEALTH_INIT_SCRIPT)

                # Inject cookies
                await context.add_cookies(self.cookies_list)
                page = await context.new_page()

                # Test navigation to Facebook
                try:
                    await page.goto("https://m.facebook.com/", wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2)
                except Exception as net_err:
                    report["message"] = f"Không thể tải trang Facebook: {str(net_err)}"
                    await browser.close()
                    return report

                current_url = page.url
                title = await page.title()
                report["final_url"] = current_url
                report["page_title"] = title

                # Check if redirected to login / checkpoint
                if "login" in current_url.lower() or "checkpoint" in current_url.lower():
                    report["session_valid"] = False
                    report["message"] = "Cookie đã hết hạn hoặc bị Facebook yêu cầu xác minh danh tính (Checkpoint)."
                else:
                    report["session_valid"] = True
                    report["message"] = f"Cookie hoạt động tốt! Đăng nhập thành công với tài khoản ID: {self.c_user or 'OK'}."

                await browser.close()
        except Exception as e:
            report["message"] = f"Lỗi khởi chạy trình duyệt: {str(e)}"

        return report

    async def scrape_group(
        self,
        group_url_or_id: str,
        group_name: str,
        keywords: List[str],
        max_posts: int = 20,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Scrape a target Facebook group feed using mobile emulation & chronological sort.
        Returns:
            (posts, logs)
        """
        logs: List[str] = []
        clean_id = extract_group_identifier(group_url_or_id)
        target_url = f"https://m.facebook.com/groups/{clean_id}/?sorting_setting=CHRONOLOGICAL"
        logs.append(f"Mở nhóm: {group_name} ({clean_id})")
        logs.append(f"URL cào: {target_url}")

        if not self.cookies_list:
            logs.append("LỖI: Chưa có Cookie hợp lệ.")
            return [], logs

        # Flatten keywords (handle comma-separated strings)
        flat_keywords: List[str] = []
        for kw in keywords:
            for sub in kw.split(","):
                sub_clean = sub.strip().lower()
                if sub_clean:
                    flat_keywords.append(sub_clean)

        parsed_posts: List[Dict[str, Any]] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS,
                )
                device = p.devices.get("Pixel 7") or p.devices["Pixel 5"]
                context = await browser.new_context(
                    **device,
                    locale="vi-VN",
                )
                await context.add_init_script(STEALTH_INIT_SCRIPT)
                await context.add_cookies(self.cookies_list)
                page = await context.new_page()

                # Navigate to group
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2.5)
                except Exception as e:
                    logs.append(f"Không thể tải trang nhóm: {e}")
                    await browser.close()
                    return [], logs

                # Check if session redirected to login
                current_url = page.url.lower()
                if "login" in current_url:
                    logs.append("CẢNH BÁO: Facebook chuyển hướng đến trang đăng nhập. Cookie đã hết hạn hoặc cần cập nhật.")
                    await browser.close()
                    return [], logs

                # Close any overlay dialogs / app install modals safely
                try:
                    await page.evaluate("""() => {
                        const btns = document.querySelectorAll('div[role="dialog"] button, [aria-label*="Đóng"], [aria-label*="Close"]');
                        btns.forEach(b => { try { b.click(); } catch (_) {} });
                    }""")
                except Exception:
                    pass

                # Check if group is private and account not joined
                try:
                    page_text = await page.evaluate("() => document.body ? document.body.innerText.toLowerCase() : ''")
                    if "bạn phải tham gia nhóm này để xem" in page_text or "nội dung này hiện không khả dụng" in page_text:
                        logs.append("⚠️ CẢNH BÁO: Nhóm Riêng Tư (Private) và tài khoản Facebook của bạn chưa tham gia nhóm. Hãy mở Facebook và bấm Tham gia nhóm trước.")
                except Exception:
                    pass

                # Scroll down 2-3 times to load dynamic feed content
                for scroll_i in range(2):
                    await page.evaluate("window.scrollBy(0, document.body.scrollHeight / 2)")
                    await asyncio.sleep(1.5)

                # Try expanding "Xem thêm" / "See more" text
                try:
                    expand_buttons = await page.query_selector_all("text='Xem thêm', text='See more'")
                    for btn in expand_buttons[:5]:
                        try:
                            if await btn.is_visible():
                                await btn.click(timeout=1000)
                                await asyncio.sleep(0.3)
                        except Exception:
                            pass
                except Exception:
                    pass

                # High-performance JS extraction adhering to viseshrp/fbn
                extract_script = """
                (groupCleanId) => {
                    const containers = Array.from(document.querySelectorAll('article, div[role="article"], div[data-pagelet^="FeedUnit"], div[data-ft*="top_level_post_id"], div[data-ft*="mf_story_key"], div[id^="mall_post_"]'));
                    const items = [];
                    const seenPids = new Set();

                    // Strategy 1: Container-level extraction
                    for (const card of containers) {
                        try {
                            const text = (card.innerText || '').trim();
                            if (!text || text.length < 5) continue;

                            const allLinks = Array.from(card.querySelectorAll('a[href]'));

                            // 1. Extract Post ID & Permalink
                            let pid = null;
                            let permalink = null;

                            const ft = card.getAttribute('data-ft') || '';
                            if (ft) {
                                try {
                                    const pFt = JSON.parse(ft);
                                    const cand = pFt.top_level_post_id || pFt.mf_story_key || pFt.tl_objid || (Array.isArray(pFt.story_fbid) ? pFt.story_fbid[0] : pFt.story_fbid);
                                    if (cand && String(cand).match(/^\\d+$/) && String(cand).length >= 6 && String(cand) !== groupCleanId) {
                                        pid = String(cand);
                                    }
                                } catch (_) {
                                    const mFt = ft.match(/"(?:top_level_post_id|mf_story_key|tl_objid|story_fbid)":\\s*"?(\\d+)"?/);
                                    if (mFt && mFt[1].length >= 6 && mFt[1] !== groupCleanId) pid = mFt[1];
                                }
                            }

                            for (const lk of allLinks) {
                                const h = lk.getAttribute('href') || '';
                                const m = h.match(/\\/posts\\/(\\d+)/) ||
                                          h.match(/\\/permalink\\/(\\d+)/) ||
                                          h.match(/[?&]story_fbid=(\\d+)/) ||
                                          h.match(/[?&]view=permalink&id=(\\d+)/) ||
                                          h.match(/(?:[?&/]|)multi_permalinks=(\\d+)/) ||
                                          h.match(/[?&]set=(?:gm|pcb)\\.(\\d+)/) ||
                                          h.match(/\\/story\\/(\\d+)/);
                                if (m && m[1].length >= 6 && m[1] !== groupCleanId) {
                                    if (!pid) pid = m[1];
                                    permalink = h;
                                    break;
                                }
                            }

                            if (!pid && !permalink) continue;
                            if (pid && seenPids.has(pid)) continue;
                            if (pid) seenPids.add(pid);

                            // 2. Extract Author (Must NOT be group link or action button)
                            let author = "Ẩn danh";
                            let authorHref = null;
                            let authorId = null;

                            if (ft) {
                                try {
                                    const pFt = JSON.parse(ft);
                                    const own = pFt.content_owner_id_new || pFt.actrs;
                                    if (own && String(own).match(/^\\d+$/)) authorId = String(own);
                                } catch (_) {}
                            }

                            for (const lk of allLinks) {
                                const h = lk.getAttribute('href') || '';
                                const txt = (lk.innerText || '').trim().split('\\n')[0].trim();
                                if (!txt || txt.length > 60) continue;

                                // Exclude group link
                                if (h.includes('/groups/' + groupCleanId) && !h.includes('/user/') && !h.includes('/posts/')) continue;
                                if (h.match(/\\/groups\\/[^/?#]+\\/?(?:$|\\?)/)) continue;

                                // Exclude utility buttons
                                const lower = txt.toLowerCase();
                                if (['thích', 'like', 'bình luận', 'comment', 'chia sẻ', 'share', 'xem thêm', 'see more', 'trả lời', 'reply'].includes(lower)) continue;

                                const mUid = h.match(/\\/user\\/(\\d+)/) || h.match(/profile\\.php\\?id=(\\d+)/);
                                if (mUid) {
                                    author = txt;
                                    authorHref = h;
                                    authorId = mUid[1];
                                    break;
                                }

                                if (lk.closest('header, h2, h3, h4, strong') || lk.getAttribute('role') === 'link') {
                                    author = txt;
                                    authorHref = h;
                                    break;
                                }
                            }

                            items.push({
                                post_id: pid,
                                permalink: permalink,
                                text: text,
                                author: author,
                                author_href: authorHref,
                                author_id: authorId
                            });
                        } catch (_) {}
                    }

                    // Strategy 2: If containers returned nothing, scan via anchor links
                    if (items.length === 0) {
                        const allPageLinks = Array.from(document.querySelectorAll('a[href]'));
                        for (const a of allPageLinks) {
                            const h = a.getAttribute('href') || '';
                            const m = h.match(/\\/posts\\/(\\d+)/) || h.match(/\\/permalink\\/(\\d+)/) || h.match(/story_fbid=(\\d+)/);
                            if (m && m[1].length >= 6 && m[1] !== groupCleanId && !seenPids.has(m[1])) {
                                seenPids.add(m[1]);
                                let card = a.closest('div[role="article"], article') || a.parentElement.parentElement;
                                const t = card ? (card.innerText || '').trim() : '';
                                if (t.length >= 5) {
                                    items.push({
                                        post_id: m[1],
                                        permalink: h,
                                        text: t,
                                        author: "Ẩn danh",
                                        author_href: null,
                                        author_id: null
                                    });
                                }
                            }
                        }
                    }

                    return items;
                }
                """

                raw_items = await page.evaluate(extract_script, clean_id)
                logs.append(f"Tìm thấy {len(raw_items)} bài viết trên giao diện.")

                for idx, item in enumerate(raw_items[:max_posts]):
                    try:
                        content_text = item.get("text", "").strip()
                        if not content_text:
                            continue

                        post_id = item.get("post_id")
                        best_permalink = item.get("permalink")
                        author = item.get("author", "Ẩn danh")
                        author_href = item.get("author_href")
                        author_id = item.get("author_id")

                        # Build authoritative post URL directly to the post
                        if post_id and str(post_id).isdigit():
                            canonical_url = f"https://www.facebook.com/groups/{clean_id}/posts/{post_id}/"
                        else:
                            canonical_url = build_canonical_post_url(clean_id, post_id, best_permalink)

                        # Build author's posts URL within the group
                        author_url = build_author_group_url(clean_id, author_id, author, author_href)

                        if not post_id:
                            import hashlib
                            post_id = f"fbn_{clean_id}_{hashlib.md5(content_text[:100].encode()).hexdigest()[:12]}"
                            logger.warning(f"Không thể xác định numeric post ID cho bài viết của '{author}', link: {canonical_url}")
                        else:
                            logger.info(f"Đã trỏ bài viết ID {post_id} -> {canonical_url} (Tác giả: {author_url})")

                        # Filter by keywords (if keywords are defined)
                        matched_kw = ""
                        if flat_keywords:
                            matched = False
                            for kw in flat_keywords:
                                if kw in content_text.lower():
                                    matched = True
                                    matched_kw = kw
                                    break
                            if not matched:
                                continue  # Skip post if doesn't match any keyword

                        parsed_posts.append({
                            "post_id": post_id,
                            "group_name": group_name,
                            "group_id": clean_id,
                            "author_name": author,
                            "author_url": author_url,
                            "content": content_text,
                            "post_url": canonical_url,
                            "matched_keyword": matched_kw,
                        })

                    except Exception as parse_err:
                        logger.debug(f"Error parsing item {idx}: {parse_err}")

                await browser.close()
                logs.append(f"Hoàn tất: Lọc được {len(parsed_posts)} bài viết hợp lệ.")

        except Exception as e:
            logs.append(f"Lỗi tiến trình cào: {str(e)}")

        return parsed_posts, logs

    async def search_facebook_groups(
        self,
        keyword: str,
        min_members: int = 0,
        privacy_filter: str = "all",
        max_results: int = 15,
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """
        Automatically search and discover Facebook groups based on keyword and filtering conditions.
        privacy_filter: 'all', 'public', or 'private'
        Returns:
            (groups_found, logs)
        """
        logs: List[str] = []
        kw_clean = keyword.strip()
        encoded_kw = urllib.parse.quote(kw_clean)
        logs.append(f"Bắt đầu tìm kiếm nhóm với từ khóa: '{kw_clean}'")
        logs.append(f"Điều kiện: Thành viên tối thiểu >= {min_members:,}, Loại nhóm: {privacy_filter}")

        if not self.cookies_list:
            logs.append("LỖI: Chưa có Cookie hợp lệ để tìm kiếm nhóm.")
            return [], logs

        discovered_groups: List[Dict[str, Any]] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS,
                )
                # Desktop browser context for rich group search results
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    locale="vi-VN",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                await context.add_init_script(STEALTH_INIT_SCRIPT)
                await context.add_cookies(self.cookies_list)
                page = await context.new_page()

                search_url = f"https://www.facebook.com/search/groups/?q={encoded_kw}"
                logs.append(f"Truy cập: {search_url}")

                try:
                    await page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(3.5)
                except Exception as e:
                    logs.append(f"Không thể mở trang tìm kiếm: {e}")
                    await browser.close()
                    return [], logs

                # Check if redirected to login
                if "login" in page.url.lower():
                    logs.append("CẢNH BÁO: Cookie đã hết hạn khi tìm kiếm nhóm.")
                    await browser.close()
                    return [], logs

                # Scroll down 2-3 times to load group results
                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000)")
                    await asyncio.sleep(1.5)

                # Look for group links in search results
                group_anchors = await page.query_selector_all("a[href*='/groups/']")
                logs.append(f"Tìm thấy {len(group_anchors)} đường dẫn liên quan đến nhóm.")

                seen_clean_ids = set()

                for a in group_anchors:
                    if len(discovered_groups) >= max_results:
                        break
                    try:
                        href = await a.get_attribute("href") or ""
                        # Filter out non-group search noise (e.g. /groups/feed, /groups/discover, etc.)
                        clean_id = extract_group_identifier(href)
                        if not clean_id or clean_id in ("feed", "discover", "joins", "search", "create") or clean_id in seen_clean_ids:
                            continue

                        # Extract card container
                        card_text = ""
                        try:
                            # Ascend to the parent container
                            container = await a.evaluate_handle("el => el.closest('div[role=\"article\"]') || el.closest('div[role=\"feed\"] > div') || el.parentElement.parentElement.parentElement")
                            if container:
                                card_text = (await container.as_element().inner_text() or "").strip()
                        except Exception:
                            card_text = (await a.inner_text() or "").strip()

                        if not card_text:
                            card_text = (await a.inner_text() or "").strip()

                        lines = [line.strip() for line in card_text.splitlines() if line.strip()]
                        group_name = lines[0] if lines else clean_id
                        if len(group_name) > 100 or "facebook.com" in group_name.lower():
                            continue

                        # Determine privacy
                        is_public = False
                        is_private = False
                        card_lower = card_text.lower()
                        if "công khai" in card_lower or "public" in card_lower:
                            is_public = True
                        if "riêng tư" in card_lower or "private" in card_lower:
                            is_private = True

                        privacy_val = "public" if is_public else ("private" if is_private else "unknown")

                        # Privacy filter check
                        if privacy_filter == "public" and not is_public:
                            continue
                        if privacy_filter == "private" and not is_private:
                            continue

                        # Parse member count
                        members_count = parse_member_count(card_text)
                        if min_members > 0 and members_count > 0 and members_count < min_members:
                            continue  # Doesn't meet minimum members threshold

                        seen_clean_ids.add(clean_id)
                        canonical_url = f"https://www.facebook.com/groups/{clean_id}"

                        # Detect post approval from card snippet
                        card_snippet = " • ".join(lines[1:3]) if len(lines) > 1 else ""
                        post_perm = "approval" if ("phê duyệt" in card_lower or "duyệt bài" in card_lower) else ("free" if is_public else "unknown")
                        post_perm_text = "Cần Admin phê duyệt" if post_perm == "approval" else ("Đăng tự do (Công khai)" if is_public else "Chưa rõ")

                        discovered_groups.append({
                            "name": group_name,
                            "fb_url": canonical_url,
                            "clean_group_id": clean_id,
                            "member_count": members_count,
                            "member_text": f"{members_count:,} thành viên" if members_count else "Không rõ",
                            "privacy": privacy_val,
                            "post_permission": post_perm,
                            "post_permission_text": post_perm_text,
                            "comment_permission": "open",
                            "comment_permission_text": "Bình luận mở",
                            "snippet": card_snippet,
                        })

                    except Exception as parse_e:
                        logger.debug(f"Error parsing group card: {parse_e}")

                await browser.close()
                logs.append(f"Hoàn tất: Tìm thấy {len(discovered_groups)} nhóm phù hợp với điều kiện!")

        except Exception as e:
            logs.append(f"Lỗi khi tìm kiếm nhóm: {str(e)}")

        return discovered_groups, logs

    async def check_group_permissions(self, group_url_or_id: str) -> Dict[str, Any]:
        """
        Check whether group allows public/free posting or requires admin approval,
        and whether comments are open or restricted.
        """
        clean_id = extract_group_identifier(group_url_or_id)
        about_url = f"https://m.facebook.com/groups/{clean_id}/about/"
        res = {
            "clean_group_id": clean_id,
            "post_permission": "unknown",
            "post_permission_text": "Chưa rõ",
            "comment_permission": "open",
            "comment_permission_text": "Bình luận tự do",
            "details": "",
        }
        if not self.cookies_list:
            res["details"] = "Chưa có Cookie để kiểm tra"
            return res

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=self.headless,
                    args=CHROMIUM_ARGS,
                )
                device = p.devices.get("Pixel 7") or p.devices["Pixel 5"]
                context = await browser.new_context(**device, locale="vi-VN")
                await context.add_init_script(STEALTH_INIT_SCRIPT)
                await context.add_cookies(self.cookies_list)
                page = await context.new_page()

                try:
                    await page.goto(about_url, wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2.5)
                except Exception:
                    await page.goto(f"https://m.facebook.com/groups/{clean_id}/", wait_until="domcontentloaded", timeout=25000)
                    await asyncio.sleep(2.5)

                perm_data = await page.evaluate("""
                () => {
                    const text = (document.body.innerText || "").toLowerCase();
                    let postPerm = "unknown";
                    let postText = "Chưa rõ";

                    if (text.includes("cần được quản trị viên") || 
                        text.includes("cần phê duyệt") || 
                        text.includes("phê duyệt bài viết: bật") || 
                        text.includes("admin approval") || 
                        text.includes("bài viết phải được duyệt") ||
                        text.includes("bài viết cần phê duyệt")) {
                        postPerm = "approval";
                        postText = "Cần Admin phê duyệt";
                    } else if (text.includes("chỉ quản trị viên mới có thể đăng") || 
                               text.includes("only admins can post") ||
                               text.includes("chỉ admin đăng")) {
                        postPerm = "admin_only";
                        postText = "Chỉ Admin được đăng";
                    } else if (text.includes("mọi người có thể đăng") || 
                               text.includes("không cần phê duyệt") || 
                               text.includes("bài viết không cần phê duyệt") || 
                               text.includes("anyone can post") ||
                               text.includes("bất kỳ ai cũng có thể đăng") ||
                               text.includes("đăng bài tự do")) {
                        postPerm = "free";
                        postText = "Đăng tự do (Không duyệt)";
                    } else {
                        const writeBox = document.querySelector("textarea, input[placeholder*='bạn đang nghĩ gì'], input[placeholder*='write something'], [aria-label*='tạo bài viết']");
                        if (writeBox) {
                            postPerm = "free";
                            postText = "Đăng tự do (Mở ô đăng bài)";
                        }
                    }

                    let commPerm = "open";
                    let commText = "Bình luận mở";
                    if (text.includes("tắt tính năng bình luận") || 
                        text.includes("giới hạn bình luận") || 
                        text.includes("commenting turned off") ||
                        text.includes("comments restricted")) {
                        commPerm = "restricted";
                        commText = "Bình luận giới hạn";
                    }

                    return {
                        post_permission: postPerm,
                        post_permission_text: postText,
                        comment_permission: commPerm,
                        comment_permission_text: commText
                    };
                }
                """)
                res.update(perm_data)
                await browser.close()
        except Exception as e:
            res["details"] = f"Lỗi: {str(e)}"

        return res
