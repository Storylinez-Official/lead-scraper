"""Playwright browser session with bot-challenge detection and headed fallback.

Playwright's sync API is not thread-safe: create one BrowserSession per thread
and close it on the thread that created it.
"""

import logging
import time
from typing import Literal

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, sync_playwright

log = logging.getLogger(__name__)

HeadlessMode = Literal["auto", "true", "false"]

_CHALLENGE_TITLES = ("just a moment", "attention required", "access denied", "verify you are human", "security check")


class BlockedError(RuntimeError):
    """The page stayed behind a bot challenge."""


class BrowserSession:
    def __init__(
        self,
        headless: HeadlessMode = "auto",
        channel: str | None = None,
        user_agent: str | None = None,
        challenge_wait_s: float = 25.0,
        nav_timeout_ms: int = 45_000,
    ):
        self.mode = headless
        self.channel = channel or None
        self.user_agent = user_agent
        self.challenge_wait_s = challenge_wait_s
        self.nav_timeout_ms = nav_timeout_ms
        self._pw = None
        self._browser = None
        self._context = None
        self._headed = False

    # -- lifecycle --

    def _launch(self, headed: bool) -> None:
        if self._browser and self._headed == headed:
            return
        self._close_browser()
        if self._pw is None:
            self._pw = sync_playwright().start()
        kwargs = {"headless": not headed, "args": ["--disable-blink-features=AutomationControlled"]}
        try:
            self._browser = self._pw.chromium.launch(channel=self.channel, **kwargs) if self.channel else None
        except PlaywrightError as exc:
            log.warning("browser channel %r unavailable (%s); using bundled Chromium", self.channel, exc)
        if self._browser is None:
            self._browser = self._pw.chromium.launch(**kwargs)
        ctx_kwargs = {"viewport": {"width": 1366, "height": 900}, "locale": "en-US"}
        # Headless Chromium advertises "HeadlessChrome" in its UA, which bot
        # filters reject on sight. Headed Chrome's own UA is left untouched.
        if not headed and self.user_agent:
            ctx_kwargs["user_agent"] = self.user_agent
        self._context = self._browser.new_context(**ctx_kwargs)
        self._headed = headed
        log.debug("launched browser headed=%s channel=%s", headed, self.channel)

    def _close_browser(self) -> None:
        if self._browser:
            try:
                self._browser.close()
            except PlaywrightError:
                pass
        self._browser = None
        self._context = None

    def close(self) -> None:
        self._close_browser()
        if self._pw:
            self._pw.stop()
            self._pw = None

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- navigation --

    @staticmethod
    def is_challenged(page: Page) -> bool:
        try:
            title = page.title().lower()
        except PlaywrightError:
            return False
        if any(t in title for t in _CHALLENGE_TITLES):
            return True
        return any("challenges.cloudflare.com" in f.url for f in page.frames)

    def _goto(self, url: str, challenge_wait_s: float) -> tuple[Page, int | None]:
        page = self._context.new_page()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=self.nav_timeout_ms)
        deadline = time.monotonic() + challenge_wait_s
        while self.is_challenged(page) and time.monotonic() < deadline:
            page.wait_for_timeout(1000)
        try:
            page.wait_for_load_state("networkidle", timeout=8_000)
        except PlaywrightError:
            pass  # long-polling pages never go idle; DOM is already loaded
        return page, (resp.status if resp else None)

    def open(self, url: str) -> tuple[Page, int | None]:
        """Open `url` in a new tab. The caller must close the returned page.

        In "auto" mode a headless browser that hits a bot challenge is replaced
        by a headed one, and the session stays headed afterwards.
        """
        if self._browser is None:
            self._launch(headed=self.mode == "false")
        wait = 8.0 if (self.mode == "auto" and not self._headed) else self.challenge_wait_s
        page, status = self._goto(url, wait)
        if self.is_challenged(page) and self.mode == "auto" and not self._headed:
            log.info("bot challenge in headless mode, retrying headed: %s", url)
            page.close()
            self._launch(headed=True)
            page, status = self._goto(url, self.challenge_wait_s)
        if self.is_challenged(page):
            page.close()
            raise BlockedError(url)
        return page, status

    def render(self, url: str) -> tuple[str, int | None, str]:
        """Return (final_url, status, html) after JS has run."""
        page, status = self.open(url)
        try:
            return page.url, status, page.content()
        finally:
            page.close()
