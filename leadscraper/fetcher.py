"""HTTP fetching with a per-lead cache and optional JS rendering.

One Fetcher serves one lead on one thread. It owns an httpx client and,
lazily, a headless BrowserSession used only for pages that need JS.
"""

import logging
from dataclasses import dataclass
from functools import cached_property

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError

from .browser import BlockedError, BrowserSession
from .extract import looks_blocked, looks_like_spa, soup_of
from .settings import Settings
from .urls import normalize_url

log = logging.getLogger(__name__)

_MAX_BYTES = 3_000_000


@dataclass
class Page:
    url: str
    status: int
    html: str
    rendered: bool = False

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 400

    @cached_property
    def soup(self) -> BeautifulSoup:
        return soup_of(self.html)


class Fetcher:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            follow_redirects=True,
            timeout=settings.request_timeout,
            headers={
                "User-Agent": settings.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        self._cache: dict[str, Page | None] = {}
        self._browser: BrowserSession | None = None
        self.requests = 0
        self.renders = 0

    def close(self) -> None:
        self.client.close()
        if self._browser:
            self._browser.close()
            self._browser = None

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def get(self, url: str, render: bool = True) -> Page | None:
        """Fetch an HTML page. Returns None on network errors or non-HTML responses.

        Error statuses (404, 500) are returned as a Page so callers can tell
        "exists but broken" from "unreachable"; check `page.ok`.
        """
        if url in self._cache:
            return self._cache[url]
        page = self._fetch_http(url)
        if (
            page is not None
            and render
            and self.settings.render_js
            and self.renders < self.settings.max_renders_per_lead
            and (looks_like_spa(page.html) or looks_blocked(page.status, page.html))
        ):
            page = self._fetch_rendered(url) or page
        self._cache[url] = page
        if page is not None:
            self._cache.setdefault(page.url, page)
        return page

    def _fetch_http(self, url: str) -> Page | None:
        self.requests += 1
        try:
            with self.client.stream("GET", url) as resp:
                ctype = resp.headers.get("content-type", "")
                if "html" not in ctype and "xml" not in ctype:
                    return None
                body = bytearray()
                for chunk in resp.iter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_BYTES:
                        break
                encoding = resp.encoding or "utf-8"
                final = normalize_url(str(resp.url)) or url
                return Page(final, resp.status_code, bytes(body).decode(encoding, errors="replace"))
        except (httpx.HTTPError, ValueError) as exc:
            log.debug("fetch failed %s: %s", url, exc)
            return None

    def _fetch_rendered(self, url: str) -> Page | None:
        if self._browser is None:
            # Crawling stays headless: a headed window per lead would be unusable.
            self._browser = BrowserSession(
                headless="true", channel=self.settings.browser_channel, user_agent=self.settings.user_agent,
                challenge_wait_s=10.0,
            )
        self.renders += 1
        try:
            final, status, html = self._browser.render(url)
        except (BlockedError, PlaywrightError) as exc:
            log.debug("render failed %s: %s", url, exc)
            return None
        log.debug("rendered %s", url)
        return Page(normalize_url(final) or url, status or 200, html, rendered=True)
