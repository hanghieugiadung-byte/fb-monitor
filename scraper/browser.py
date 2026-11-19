"""
BrowserManager: Manages a Playwright persistent browser context for Facebook scraping.
Session state is loaded from / saved to the path configured by FB_SESSION_FILE.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from loguru import logger
from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    Error as PlaywrightError,
)


class BrowserManager:
    """Manages a Playwright Chromium browser with a persistent storage context.

    Usage (async context manager)::

        async with BrowserManager(session_file="session/state.json") as bm:
            page = await bm.get_page()
            await page.goto("https://www.facebook.com")
    """

    def __init__(
        self,
        session_file: str = "session/state.json",
        headless: bool = True,
        user_data_dir: str = "session/profile",
    ) -> None:
        self._session_file = Path(session_file)
        self._headless = headless
        self._user_data_dir = user_data_dir

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start Playwright and open a persistent browser context."""
        if self._playwright is not None:
            logger.debug("BrowserManager already started.")
            return

        logger.info("Starting Playwright browser (headless={})…", self._headless)
        self._playwright = await async_playwright().start()

        await self._launch_context()

    async def _launch_context(self) -> None:
        """(Re-)launch the browser context, loading session state if available."""
        launch_kwargs: dict = {
            "headless": self._headless,
            "args": [
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        }

        storage_state = None
        if self._session_file.exists():
            logger.info("Loading session state from {}", self._session_file)
            storage_state = str(self._session_file)
        else:
            logger.warning(
                "Session file {} not found — starting fresh context. "
                "Run `python -m scraper.login` to create one.",
                self._session_file,
            )

        try:
            # Use a persistent context so cookies/localStorage survive restarts
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir,
                **launch_kwargs,
                storage_state=storage_state,
                locale="en-US",
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            )
        except PlaywrightError as exc:
            logger.exception("Failed to launch browser context: {}", exc)
            raise

        # Reuse the first existing page or open a new blank one
        pages = self._context.pages
        self._page = pages[0] if pages else await self._context.new_page()
        logger.success("Browser context ready.")

    async def stop(self) -> None:
        """Close the browser context and stop Playwright."""
        if self._context:
            try:
                await self._context.close()
            except PlaywrightError as exc:
                logger.warning("Error while closing context: {}", exc)
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser stopped.")

    # ------------------------------------------------------------------
    # Page access with auto-restart
    # ------------------------------------------------------------------

    async def get_page(self) -> Page:
        """Return the active page, restarting the browser if it has crashed."""
        if self._context is None:
            logger.warning("Context is None — restarting browser…")
            await self._launch_context()

        assert self._page is not None, "Page is unexpectedly None after context launch."

        # Verify the page is still alive
        try:
            await self._page.evaluate("1")
        except PlaywrightError as exc:
            logger.warning("Page check failed ({}); opening a new page…", exc)
            try:
                self._page = await self._context.new_page()  # type: ignore[union-attr]
            except PlaywrightError:
                logger.warning("Context also dead — performing full restart…")
                await self.stop()
                await self.start()

        return self._page  # type: ignore[return-value]

    async def save_state(self) -> None:
        """Persist the current cookies / localStorage to the session file."""
        if self._context is None:
            logger.warning("Cannot save state: no active context.")
            return
        self._session_file.parent.mkdir(parents=True, exist_ok=True)
        await self._context.storage_state(path=str(self._session_file))
        logger.info("Session state saved to {}", self._session_file)

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "BrowserManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
