"""Step 3: crawl a site and collect emails and phone numbers with regex.

Breadth-first over the lead's own registrable domain (so docs.example.com and
www.example.com count as the same site), with contact-like pages crawled
first. The crawl is bounded by `max_pages`.
"""

import heapq
import logging
import re
from dataclasses import dataclass, field

from .extract import all_links, find_emails, find_phones
from .fetcher import Fetcher
from .urls import is_crawlable, registrable_domain, same_site, site_root

log = logging.getLogger(__name__)

_CONTACT_PATH_RE = re.compile(
    r"/(contact|contact-us|about|about-us|team|company|imprint|impressum|legal|support|help|"
    r"press|careers|privacy|terms)(/|$|\.html?$)",
    re.I,
)
_CONTACT_TEXT_RE = re.compile(
    r"\b(contact|about|team|company|imprint|impressum|legal|support|get in touch|talk to (us|sales)|press)\b",
    re.I,
)
_SEED_PATHS = ["contact", "contact-us", "about", "about-us", "company", "team", "imprint", "impressum", "legal", "support"]


@dataclass
class ContactCrawl:
    # value -> pages it was found on (first 3)
    emails: dict[str, list[str]] = field(default_factory=dict)
    phones: dict[str, list[str]] = field(default_factory=dict)
    pages_visited: list[str] = field(default_factory=list)

    def _add(self, bucket: dict[str, list[str]], values: set[str], url: str) -> None:
        for v in sorted(values):
            pages = bucket.setdefault(v, [])
            if url not in pages and len(pages) < 3:
                pages.append(url)

    @property
    def found_any(self) -> bool:
        return bool(self.emails or self.phones)


def crawl_contacts(fetcher: Fetcher, start_url: str, max_pages: int, extra_urls: list[str] = ()) -> ContactCrawl:
    domain = registrable_domain(start_url)
    root = site_root(start_url)
    result = ContactCrawl()

    # (priority, insertion order, url): lower priority first, FIFO within a priority.
    queue: list[tuple[int, int, str]] = []
    queued: set[str] = set()
    counter = 0

    def push(url: str, priority: int) -> None:
        nonlocal counter
        if url in queued or not same_site(url, domain) or not is_crawlable(url):
            return
        queued.add(url)
        heapq.heappush(queue, (priority, counter, url))
        counter += 1

    push(start_url, 0)
    for path in _SEED_PATHS:
        push(root + path, 1)
    for url in extra_urls:
        push(url, 2)

    while queue and len(result.pages_visited) < max_pages:
        priority, _, url = heapq.heappop(queue)
        page = fetcher.get(url)
        if page is None or not page.ok:
            continue
        result.pages_visited.append(page.url)
        contact_like = priority <= 1 or bool(_CONTACT_PATH_RE.search(page.url))
        result._add(result.emails, find_emails(page.soup, page.html), page.url)
        result._add(result.phones, find_phones(page.soup, scan_text=contact_like), page.url)

        for link in all_links(page.soup, page.url):
            is_contact = bool(_CONTACT_PATH_RE.search(link.url) or _CONTACT_TEXT_RE.search(link.text))
            push(link.url, 1 if is_contact else 3)

    log.debug(
        "contact crawl %s: %d pages, %d emails, %d phones",
        domain, len(result.pages_visited), len(result.emails), len(result.phones),
    )
    return result
