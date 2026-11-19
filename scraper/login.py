"""
One-time Facebook login helper.

Run as:
    python -m scraper.login

The script opens a visible (non-headless) Chromium window, navigates to
facebook.com, and waits for you to log in manually.  Once you press Enter it
saves the session state (cookies + localStorage) to session/state.json so the
scraper can reuse it without logging in again.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from loguru import logger
from playwright.async_api import async_playwright


SESSION_DIR = Path("session")
SESSION_FILE = SESSION_DIR / "state.json"
PROFILE_DIR = SESSION_DIR / "profile"


async def _run_login() -> None:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Opening browser for manual login…")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=["--no-sandbox"],
            locale="en-US",
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        page = context.pages[0] if context.pages else await context.new_page()

        logger.info("Navigating to facebook.com…")
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded")

        print("\n" + "=" * 60)
        print("  A browser window has opened.")
        print("  Please log in to Facebook in that window.")
        print("  When you are fully logged in, return here and")
        print("  press Enter to save your session.")
        print("=" * 60 + "\n")

        try:
            input("Press Enter after you've logged in… ")
        except EOFError:
            # Non-interactive environment fallback
            logger.info("Non-interactive mode — waiting 60 s for login…")
            await asyncio.sleep(60)

        logger.info("Saving session state to {}…", SESSION_FILE)
        await context.storage_state(path=str(SESSION_FILE))

        await context.close()

    logger.success("Session saved to {}. You can now run the scraper.", SESSION_FILE)


def main() -> None:
    try:
        asyncio.run(_run_login())
    except KeyboardInterrupt:
        logger.warning("Login cancelled by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
