"""Browser tool: Playwright-backed web automation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from nova.config import SCREENSHOTS_DIR

_SEARCH_ENGINE = "https://www.google.com/search?q="


class BrowserTool:
    """Async Playwright browser. One shared browser instance per process."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    async def _ensure_browser(self) -> None:
        if self._page is not None:
            return
        from playwright.async_api import async_playwright  # type: ignore[import]

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=False)
        self._page = await self._browser.new_page()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._browser = None
        self._playwright = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def navigate(self, url: str) -> str:
        """Navigate to *url* and return the page title."""
        await self._ensure_browser()
        assert self._page is not None
        await self._page.goto(url, wait_until="domcontentloaded")
        return await self._page.title()

    async def click(self, selector: str) -> str:
        """Click the first element matching *selector*."""
        await self._ensure_browser()
        assert self._page is not None
        await self._page.click(selector)
        return f"Clicked: {selector}"

    async def type_text(self, selector: str, text: str) -> str:
        """Fill an input field."""
        await self._ensure_browser()
        assert self._page is not None
        await self._page.fill(selector, text)
        return f"Typed into {selector}"

    async def extract_text(self) -> str:
        """Return all visible text from the current page (up to 8 000 chars)."""
        await self._ensure_browser()
        assert self._page is not None
        text = await self._page.inner_text("body")
        return text[:8_000]

    async def screenshot(self, name: str = "snap") -> Path:
        """Save a screenshot and return its path."""
        await self._ensure_browser()
        assert self._page is not None
        path = SCREENSHOTS_DIR / f"{name}.png"
        await self._page.screenshot(path=str(path), full_page=False)
        return path

    async def search_web(self, query: str) -> str:
        """Search Google and return the page text of the results."""
        encoded = query.replace(" ", "+")
        await self.navigate(_SEARCH_ENGINE + encoded)
        return await self.extract_text()

    async def get_links(self) -> list[dict[str, str]]:
        """Return all anchor tags on the current page as {text, href} dicts."""
        await self._ensure_browser()
        assert self._page is not None
        links = await self._page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => ({text: e.innerText.trim(), href: e.href}))",
        )
        return links[:50]  # cap at 50
