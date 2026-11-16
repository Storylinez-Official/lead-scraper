"""Generic, config-driven listing scraper using a real browser.

Works for any site shaped as "listing page -> item detail page -> external
website link". Everything site-specific lives in the source's `options`:

  item_link_pattern   regex matched against each <a href> on the listing
                      (relative or absolute). Required.
  website_selector    CSS selector on the detail page for the external
                      website link. If omitted, the item link itself is
                      treated as the website (listing links straight out).
  name_selector       CSS selector for the product name on the detail page.
                      Default: "h1", then the link text from the listing.
  description_selector  optional CSS selector on the detail page.
  load_more_selector  optional CSS selector clicked to load more items.
  scroll_rounds       how many times to scroll / load more (default 5).
  headless            "auto" (default), "true" or "false".
  delay_ms            pause between detail pages (default 1500).
"""

import logging
import re
from collections.abc import Iterator

from playwright.sync_api import Error as PlaywrightError

from ..browser import BlockedError, BrowserSession
from ..schemas import Lead
from ..urls import is_product_website, normalize_url
from .base import Source, register

log = logging.getLogger(__name__)

_COLLECT_JS = """(pattern) => {
  const re = new RegExp(pattern);
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href');
    if (!re.test(href)) continue;
    const abs = new URL(href, location.href).href.split('#')[0];
    if (seen.has(abs)) continue;
    seen.add(abs);
    out.push({url: abs, text: (a.innerText || '').trim().split('\\n')[0].slice(0, 120)});
  }
  return out;
}"""


@register("browser_listing")
class BrowserListingSource(Source):
    def iter_leads(self, limit: int) -> Iterator[Lead]:
        opts = self.options
        if "item_link_pattern" not in opts:
            raise ValueError(f"{self.name}: options.item_link_pattern is required")
        pattern = opts["item_link_pattern"]
        re.compile(pattern)  # fail fast on a bad pattern; JS regex syntax is close enough

        with BrowserSession(
            headless=str(opts.get("headless", "auto")).lower(),
            channel=self.settings.browser_channel,
            user_agent=self.settings.user_agent,
        ) as browser:
            items = self._collect_items(browser, pattern, want=limit * 3)
            log.info("%s: %d item links on listing", self.name, len(items))
            yielded = 0
            seen_sites: set[str] = set()
            for item in items:
                if yielded >= limit:
                    return
                lead = self._resolve(browser, item)
                if lead is None or lead.website in seen_sites:
                    continue
                seen_sites.add(lead.website)
                yielded += 1
                yield lead

    def _collect_items(self, browser: BrowserSession, pattern: str, want: int) -> list[dict]:
        page, _ = browser.open(self.url)
        try:
            items = page.evaluate(_COLLECT_JS, pattern)
            for _ in range(int(self.options.get("scroll_rounds", 5))):
                if len(items) >= want:
                    break
                if sel := self.options.get("load_more_selector"):
                    try:
                        page.click(sel, timeout=3_000)
                    except PlaywrightError:
                        pass
                page.mouse.wheel(0, 20_000)
                page.wait_for_timeout(1_500)
                items = page.evaluate(_COLLECT_JS, pattern)
            return items[:want]
        finally:
            page.close()

    def _resolve(self, browser: BrowserSession, item: dict) -> Lead | None:
        selector = self.options.get("website_selector")
        if not selector:
            website = normalize_url(item["url"])
            if not website or not is_product_website(website):
                return None
            return Lead(name=item["text"] or website, website=website, source=self.name, source_url=self.url)

        try:
            page, _ = browser.open(item["url"])
        except (BlockedError, PlaywrightError) as exc:
            log.warning("%s: cannot open %s: %s", self.name, item["url"], exc)
            return None
        try:
            href = page.get_attribute(selector, "href", timeout=5_000)
            website = normalize_url(href or "")
            if not website or not is_product_website(website):
                log.debug("%s: no product website on %s (href=%r)", self.name, item["url"], href)
                return None
            name = self._text(page, self.options.get("name_selector", "h1")) or item["text"] or website
            description = self._text(page, self.options.get("description_selector"))
            return Lead(name=name, website=website, source=self.name, source_url=item["url"], description=description)
        except PlaywrightError as exc:
            log.debug("%s: no website link on %s: %s", self.name, item["url"], exc)
            return None
        finally:
            page.wait_for_timeout(int(self.options.get("delay_ms", 1500)))
            page.close()

    @staticmethod
    def _text(page, selector: str | None) -> str:
        if not selector:
            return ""
        try:
            return (page.text_content(selector, timeout=2_000) or "").strip()[:300]
        except PlaywrightError:
            return ""
