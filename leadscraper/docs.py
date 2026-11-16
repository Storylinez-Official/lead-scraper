"""Step 2.2 (find the documentation page) and step 5 input (sample doc pages).

Both are deterministic: candidates are ordered by fixed rules and every page
is scored with the regex signals in extract.score_doc_page.
"""

import logging
from dataclasses import asdict, dataclass, field

from .extract import (
    DOC_NAV_RE,
    Link,
    code_languages,
    doc_section_links,
    has_search,
    main_content_text,
    page_title,
    score_doc_page,
)
from .fetcher import Fetcher, Page
from .urls import hostname, registrable_domain, site_root

log = logging.getLogger(__name__)

_GUESSED_PATHS = ["docs", "documentation", "developers", "api", "reference", "guide", "help"]
_GUESSED_SUBDOMAINS = ["docs", "developer", "developers", "help"]


@dataclass
class Candidate:
    url: str
    reason: str
    score: int = 0
    signals: list[str] = field(default_factory=list)
    fetched: bool = False


@dataclass
class DocsDiscovery:
    doc_url: str | None
    score: int
    signals: list[str]
    candidates: list[dict]


def _candidate_urls(homepage: Page, nav_doc_links: list[Link], limit: int) -> list[Candidate]:
    """Header doc links first (strongest keyword first), then guessed URLs."""
    root = site_root(homepage.url)
    domain = registrable_domain(homepage.url)
    out: list[Candidate] = []
    seen: set[str] = set()

    def add(url: str, reason: str) -> None:
        if url not in seen and len(out) < limit:
            seen.add(url)
            out.append(Candidate(url, reason))

    # Explicit "Docs"/"Documentation" links outrank "API", "Learn", etc.
    def rank(link: Link) -> int:
        m = DOC_NAV_RE.search(link.text)
        word = m.group(1).lower() if m else ""
        return 0 if word.startswith("doc") else 1 if word else 2

    for link in sorted(nav_doc_links, key=rank):
        add(link.url, f"header link '{link.text}'")
    for path in _GUESSED_PATHS:
        add(f"{root}{path}", "common docs path")
    for sub in _GUESSED_SUBDOMAINS:
        add(f"https://{sub}.{domain}/", "common docs subdomain")
    return out


def find_documentation(
    fetcher: Fetcher, homepage: Page, nav_doc_links: list[Link], max_candidates: int, threshold: int
) -> DocsDiscovery:
    candidates = _candidate_urls(homepage, nav_doc_links, max_candidates)
    best: Candidate | None = None
    for cand in candidates:
        page = fetcher.get(cand.url)
        if page is None or not page.ok:
            continue
        cand.fetched = True
        cand.url = page.url  # follow redirects, e.g. /docs -> docs.example.com
        s = score_doc_page(page.url, page.soup, page.html)
        cand.score, cand.signals = s.score, s.signals
        if best is None or cand.score > best.score:
            best = cand
        if cand.score >= threshold * 2:
            break  # unambiguous; skip the remaining guesses

    # The homepage itself is the docs for many libraries and dev tools.
    home_score = score_doc_page(homepage.url, homepage.soup, homepage.html)
    home = Candidate(homepage.url, "homepage", home_score.score, home_score.signals, True)
    candidates.append(home)
    if best is None or home.score > best.score:
        best = home

    found = best is not None and best.score >= threshold
    log.debug("docs for %s: %s (score %s)", homepage.url, best.url if found else None, best.score if best else 0)
    return DocsDiscovery(
        doc_url=best.url if found else None,
        score=best.score if best else 0,
        signals=best.signals if best else [],
        candidates=[asdict(c) for c in candidates if c.fetched],
    )


@dataclass
class DocSample:
    pages: list[dict]  # {url, title, text}
    metrics: dict


def sample_documentation(fetcher: Fetcher, doc_url: str, max_pages: int, chars_per_page: int = 5000) -> DocSample:
    first = fetcher.get(doc_url)
    if first is None or not first.ok:
        return DocSample([], {"pages_sampled": 0})

    urls = [first.url] + doc_section_links(first.soup, first.url, limit=max_pages * 3)
    nav_link_count = len(urls) - 1
    pages: list[dict] = []
    code_blocks = 0
    words = 0
    langs: set[str] = set()
    signals: set[str] = set()
    for url in urls:
        if len(pages) >= max_pages:
            break
        page = fetcher.get(url)
        if page is None or not page.ok or hostname(page.url) != hostname(first.url):
            continue
        text = main_content_text(page.soup, chars_per_page)
        pages.append({"url": page.url, "title": page_title(page.soup), "text": text})
        code_blocks += len(page.soup.find_all("pre"))
        words += len(text.split())
        langs.update(code_languages(page.soup))
        signals.update(score_doc_page(page.url, page.soup, page.html).kinds)

    metrics = {
        "pages_sampled": len(pages),
        "doc_nav_links": nav_link_count,
        "code_blocks_total": code_blocks,
        "avg_words_per_page": round(words / len(pages)) if pages else 0,
        "code_languages": sorted(langs),
        "has_search": has_search(first.soup, first.html),
        "signals_seen": sorted(signals),
    }
    return DocSample(pages, metrics)
