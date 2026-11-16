"""Step 4.5: find the pages that name the team and the pages that show recent change.

Deterministic discovery only. The graph node hands what is found here to the
LLM, then guards the LLM output against it (a person must be named on a
fetched page; a signal must link to a URL found on the changelog page).

People pages:  about / team / leadership / company pages linked from the
               homepage, plus the common paths.
Changelog:     changelog / release notes / what's new pages linked from the
               homepage or the docs, plus the common paths on the site and
               on the docs host.
"""

import re
from dataclasses import dataclass, field

from .extract import Link, all_links, header_links, page_title, visible_text
from .fetcher import Fetcher
from .urls import hostname, registrable_domain, same_site, site_root

_PEOPLE_PATH_RE = re.compile(
    r"/(about|about-us|team|our-team|the-team|company|leadership|people|founders|who-we-are|our-story)(/|$|\.html?$)",
    re.I,
)
_PEOPLE_TEXT_RE = re.compile(r"\b(about( us)?|team|leadership|company|our story|who we are|founders)\b", re.I)
_PEOPLE_SEED = ["about", "about-us", "team", "company", "leadership"]

_CHANGELOG_PATH_RE = re.compile(
    r"/(change-?log|changes|release-?notes|releases|whats-?new|what-is-new|product-updates|updates)(/|$|\.html?$)",
    re.I,
)
_CHANGELOG_TEXT_RE = re.compile(r"\b(change ?log|release notes|what'?s new|product updates)\b", re.I)
_CHANGELOG_SEED = ["changelog", "change-log", "release-notes", "releases", "whats-new"]


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str


@dataclass
class ResearchSources:
    people_pages: list[FetchedPage] = field(default_factory=list)
    changelog: FetchedPage | None = None
    changelog_links: list[Link] = field(default_factory=list)  # entry links on the changelog page
    tried: list[str] = field(default_factory=list)


def _candidates(links: list[Link], path_re: re.Pattern, text_re: re.Pattern, domain: str) -> list[str]:
    out: list[str] = []
    for link in links:
        url = link.url.split("#", 1)[0]
        if url not in out and same_site(url, domain) and (path_re.search(url) or text_re.search(link.text)):
            out.append(url)
    return out


def gather(fetcher: Fetcher, homepage_url: str, doc_url: str | None, max_people_pages: int = 3) -> ResearchSources:
    domain = registrable_domain(homepage_url)
    root = site_root(homepage_url)
    src = ResearchSources()
    home = fetcher.get(homepage_url)
    home_links = (header_links(home.soup, home.url) + all_links(home.soup, home.url)) if home and home.ok else []

    # People: linked pages first (their real paths), then common paths.
    people = _candidates(home_links, _PEOPLE_PATH_RE, _PEOPLE_TEXT_RE, domain)
    people += [root + p for p in _PEOPLE_SEED if root + p not in people]
    for url in people:
        if len(src.people_pages) >= max_people_pages:
            break
        src.tried.append(url)
        page = fetcher.get(url)
        if page is None or not page.ok or any(p.url == page.url for p in src.people_pages):
            continue
        src.people_pages.append(FetchedPage(page.url, page_title(page.soup), visible_text(page.soup, max_chars=7000)))

    # Changelog: links from the homepage and the docs, then common paths on both hosts.
    links = list(home_links)
    if doc_url:
        doc = fetcher.get(doc_url)
        if doc and doc.ok:
            links += header_links(doc.soup, doc.url) + all_links(doc.soup, doc.url)
    changelog = _candidates(links, _CHANGELOG_PATH_RE, _CHANGELOG_TEXT_RE, domain)
    roots = [root] + ([site_root(doc_url)] if doc_url and hostname(doc_url) != hostname(homepage_url) else [])
    changelog += [r + p for r in roots for p in _CHANGELOG_SEED if r + p not in changelog]
    for url in changelog[:8]:
        src.tried.append(url)
        page = fetcher.get(url)
        if page is None or not page.ok:
            continue
        src.changelog = FetchedPage(page.url, page_title(page.soup), visible_text(page.soup, max_chars=9000))
        src.changelog_links = [
            link for link in all_links(page.soup, page.url) if same_site(link.url, domain) and link.text
        ][:120]
        break
    return src
