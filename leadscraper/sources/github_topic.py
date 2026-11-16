"""GitHub topic pages (https://github.com/topics/<topic>).

Repositories on a topic page are not products; the product is the repo's
"homepage" (the website link in the About box). The search API returns that
field directly, so this adapter uses it instead of scraping each repo page.
Repos without a homepage, or whose homepage is another hosting site, are
skipped.
"""

import logging
import re
import time
from collections.abc import Iterator
from urllib.parse import urlsplit

import httpx

from ..schemas import Lead
from ..urls import is_product_website, normalize_url
from .base import Source, register

log = logging.getLogger(__name__)

_API = "https://api.github.com/search/repositories"


@register("github_topic")
class GitHubTopicSource(Source):
    """Options:
    topic: override the topic parsed from the URL.
    sort: "stars" (default, same as the topic page) or "updated".
    """

    def _topic(self) -> str:
        if topic := self.options.get("topic"):
            return topic
        m = re.match(r"^/topics/([^/?#]+)", urlsplit(self.url).path)
        if not m:
            raise ValueError(f"{self.name}: cannot parse topic from {self.url}; set options.topic")
        return m.group(1)

    def iter_leads(self, limit: int) -> Iterator[Lead]:
        topic = self._topic()
        sort = self.options.get("sort", "stars")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.settings.github_token:
            headers["Authorization"] = f"Bearer {self.settings.github_token}"

        yielded = 0
        page = 1
        with httpx.Client(headers=headers, timeout=self.settings.request_timeout) as client:
            while yielded < limit and page <= 10:  # search API caps at 1000 results
                resp = client.get(
                    _API,
                    params={"q": f"topic:{topic}", "sort": sort, "order": "desc", "per_page": 50, "page": page},
                )
                if resp.status_code in (403, 429):
                    reset = int(resp.headers.get("x-ratelimit-reset", "0"))
                    wait = max(0, reset - int(time.time())) + 1
                    if wait > 70:
                        log.warning("%s: GitHub rate limit, reset in %ss; stopping source", self.name, wait)
                        return
                    log.info("%s: GitHub rate limit, sleeping %ss", self.name, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                items = resp.json().get("items", [])
                if not items:
                    return
                for item in items:
                    website = normalize_url(item.get("homepage") or "")
                    if not website or not is_product_website(website):
                        log.debug("%s: skip %s (homepage=%r)", self.name, item["full_name"], item.get("homepage"))
                        continue
                    yield Lead(
                        name=item["full_name"],
                        website=website,
                        source=self.name,
                        source_url=item["html_url"],
                        description=item.get("description") or "",
                        extra={
                            "stars": item.get("stargazers_count"),
                            "language": item.get("language"),
                            "repo": item["html_url"],
                            "topics": item.get("topics", []),
                        },
                    )
                    yielded += 1
                    if yielded >= limit:
                        return
                page += 1
