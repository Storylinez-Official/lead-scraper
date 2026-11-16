"""Deterministic extraction from HTML: links, text, emails, phones, doc signals.

Nothing in here calls an LLM. The graph uses these results to decide which
edges to take, and passes them to the LLM nodes as evidence.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from .urls import hostname, normalize_url, registrable_domain

# --- links -------------------------------------------------------------------


@dataclass(frozen=True)
class Link:
    url: str
    text: str


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _link_text(a: Tag) -> str:
    text = a.get_text(" ", strip=True) or a.get("aria-label", "") or a.get("title", "")
    return re.sub(r"\s+", " ", str(text)).strip()[:120]


def all_links(soup: BeautifulSoup, base_url: str) -> list[Link]:
    seen: set[str] = set()
    out: list[Link] = []
    for a in soup.find_all("a", href=True):
        url = normalize_url(a["href"], base_url)
        if url and url not in seen:
            seen.add(url)
            out.append(Link(url, _link_text(a)))
    return out


def header_links(soup: BeautifulSoup, base_url: str) -> list[Link]:
    """Links in the site header / primary navigation.

    Falls back to the first 40 links in document order when the page has no
    <header> or <nav>, which is common on hand-rolled landing pages.
    """
    containers = soup.select("header, nav, [role=navigation], [class*=navbar], [class*=header]")
    seen: set[str] = set()
    out: list[Link] = []
    for c in containers:
        for a in c.find_all("a", href=True):
            url = normalize_url(a["href"], base_url)
            if url and url not in seen:
                seen.add(url)
                out.append(Link(url, _link_text(a)))
    return out or all_links(soup, base_url)[:40]


# --- visible text ------------------------------------------------------------

_NON_CONTENT = ["script", "style", "noscript", "svg", "template", "iframe"]


def visible_text(soup: BeautifulSoup, max_chars: int | None = None) -> str:
    soup = BeautifulSoup(str(soup), "lxml")
    for tag in soup(_NON_CONTENT):
        tag.decompose()
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n", strip=True))
    return text[:max_chars] if max_chars else text


def main_content_text(soup: BeautifulSoup, max_chars: int) -> str:
    """Text of the main content area, with code blocks fenced so the LLM can see them."""
    soup = BeautifulSoup(str(soup), "lxml")
    for tag in soup(_NON_CONTENT + ["header", "footer"]):
        tag.decompose()
    root = soup.select_one("main, article, [role=main], .markdown, .content") or soup.body or soup
    for pre in root.find_all("pre"):
        pre.replace_with(f"\n```\n{pre.get_text()}\n```\n")
    text = re.sub(r"\n\s*\n+", "\n", root.get_text("\n", strip=True))
    return text[:max_chars]


def page_title(soup: BeautifulSoup) -> str:
    return soup.title.get_text(strip=True)[:200] if soup.title else ""


def meta_description(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    return str(tag.get("content", "")).strip()[:500] if tag else ""


def looks_like_spa(html: str) -> bool:
    """True when the server HTML is an empty shell that needs JS to render."""
    if len(html) > 400_000:
        return False
    soup = soup_of(html)
    text_len = len(visible_text(soup))
    if text_len > 400:
        return False
    has_root = bool(soup.select_one("#root, #__next, #app, #__nuxt, [data-reactroot], app-root"))
    asks_js = bool(re.search(r"enable javascript|requires javascript", html, re.I))
    return has_root or asks_js or text_len < 80


def looks_blocked(status: int, html: str) -> bool:
    return status in (403, 429, 503) and bool(
        re.search(r"cf-chl|just a moment|attention required|captcha|verify you are human", html, re.I)
    )


# --- documentation keywords ---------------------------------------------------

# Step 2.1: words in navigation that mean "this site has documentation".
DOC_NAV_RE = re.compile(
    r"\b(docs?|documentation|api(?:\s+reference)?|developers?|dev\s*portal|reference|manual|"
    r"guides?|handbook|sdks?|getting\s+started|quick\s*start|tutorials?|knowledge\s*base|"
    r"help\s*center|learn)\b",
    re.I,
)
DOC_URL_RE = re.compile(
    r"(^https?://(docs?|developers?|dev|api|help|support|learn|manual|wiki|reference)\.)|"
    r"(/(docs?|documentation|api-?docs?|api-?reference|reference|developers?|guides?|manual|"
    r"handbook|learn|help|kb|knowledge-?base|sdk)(/|$))",
    re.I,
)


def doc_nav_links(links: list[Link]) -> list[Link]:
    return [link for link in links if DOC_NAV_RE.search(link.text) or DOC_URL_RE.search(link.url)]


# Step 2.2: patterns that indicate a page *is* documentation. Each pattern has
# a weight; the page score is the sum of matched weights.
@dataclass
class DocScore:
    score: int = 0
    signals: list[str] = field(default_factory=list)  # human-readable, for reports
    kinds: list[str] = field(default_factory=list)  # stable keys, for aggregation

    def add(self, weight: int, kind: str, detail: str = "") -> None:
        self.score += weight
        self.kinds.append(kind)
        self.signals.append(f"+{weight} {kind}" + (f" ({detail})" if detail else ""))


_HTTP_ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+/[\w/{}:.\-]+")
_CURL_RE = re.compile(r"\bcurl\s+(-[A-Za-z]+\s+\S+\s+)*['\"]?https?://", re.I)
_INSTALL_RE = re.compile(
    r"\b(npm\s+(i|install)|yarn\s+add|pnpm\s+add|pip3?\s+install|poetry\s+add|uv\s+add|go\s+get|"
    r"cargo\s+(add|install)|gem\s+install|composer\s+require|brew\s+install|dotnet\s+add|docker\s+(run|pull))\b"
)
_DOC_HEADINGS_RE = re.compile(
    r"^(api reference|getting started|quick ?start|installation|authentication|endpoints?|"
    r"parameters|request body|response|error codes?|sdks?|configuration|usage|examples?|"
    r"overview|introduction|tutorials?|rate limits?|webhooks|changelog)\b",
    re.I,
)
_DOC_PLATFORM_RE = re.compile(
    r"docusaurus|mintlify|gitbook|readme\.io|readme\.com|mkdocs|sphinx|vitepress|vuepress|nextra|"
    r"redoc|swagger-ui|stoplight|docsify|starlight|fern|scalar|hugo-book|docsearch|algolia",
    re.I,
)


def score_doc_page(url: str, soup: BeautifulSoup, html: str) -> DocScore:
    s = DocScore()
    text = visible_text(soup, max_chars=60_000)

    code_blocks = len(soup.find_all("pre"))
    inline_code = len(soup.find_all("code"))
    if code_blocks >= 1:
        s.add(2, "code_blocks", str(code_blocks))
    if code_blocks >= 3:
        s.add(1, "many_code_blocks")
    elif inline_code >= 5:
        s.add(1, "inline_code", str(inline_code))

    if _HTTP_ENDPOINT_RE.search(text):
        s.add(3, "http_endpoints")
    if _CURL_RE.search(text):
        s.add(2, "curl_example")
    if _INSTALL_RE.search(text):
        s.add(2, "install_command")

    headings = [h.get_text(" ", strip=True) for h in soup.find_all(["h1", "h2", "h3"])]
    matched = sorted({m.group(1).lower() for h in headings if (m := _DOC_HEADINGS_RE.match(h))})
    if matched:
        s.add(min(len(matched), 4), "doc_headings", ", ".join(matched[:6]))

    if DOC_URL_RE.search(url):
        s.add(2, "doc_url")

    generator = soup.find("meta", attrs={"name": "generator"})
    platform = _DOC_PLATFORM_RE.search((str(generator.get("content", "")) if generator else "") + html[:200_000])
    if platform:
        s.add(3, "doc_platform", platform.group(0).lower())

    if soup.select_one("aside, nav[class*=side], [class*=sidebar], [class*=toc], [class*=table-of-contents]"):
        s.add(1, "sidebar_toc")
    return s


_LOCALE_SEGMENT_RE = re.compile(r"^[a-z]{2}(-[a-z]{2,4})?$")
_NON_DOC_SEGMENTS = {
    "blog", "news", "newsletter", "pricing", "login", "signin", "sign-in", "signup", "sign-up",
    "register", "careers", "jobs", "about", "contact", "company", "legal", "privacy", "terms", "customers",
}


def doc_section_links(soup: BeautifulSoup, doc_url: str, limit: int) -> list[str]:
    """Other pages of the same documentation site, preferring sidebar links.

    A link belongs to the docs if it is on the same host and shares the first
    path segment of the doc URL (or the doc URL is the host root).
    """
    host = hostname(doc_url)
    first_segment = urlsplit(doc_url).path.strip("/").split("/")[0]
    prefix = f"/{first_segment}" if first_segment else ""

    # Sidebars first, then any nav, then the whole page. soup.select returns
    # document order, which would put the top navbar (blog, pricing,
    # language switcher) ahead of the docs sidebar.
    containers: list = []
    for selector in ("[class*=sidebar], aside", "[class*=toc], nav"):
        containers += [c for c in soup.select(selector) if c not in containers]
    containers.append(soup)
    out: list[str] = []
    for c in containers:
        for a in c.find_all("a", href=True):
            url = normalize_url(a["href"], doc_url)
            if not url or url == doc_url or url in out or hostname(url) != host:
                continue
            path = urlsplit(url).path
            if prefix and not path.startswith(prefix):
                continue
            first = path.strip("/").split("/")[0].lower()
            if first != first_segment.lower() and (_LOCALE_SEGMENT_RE.match(first) or first in _NON_DOC_SEGMENTS):
                continue
            out.append(url)
            if len(out) >= limit:
                return out
    return out


def code_languages(soup: BeautifulSoup) -> list[str]:
    langs: set[str] = set()
    for tag in soup.find_all(["code", "pre", "div"], class_=True):
        for cls in tag.get("class", []):
            m = re.match(r"(?:language|lang|highlight)-([a-z0-9+#]+)", cls, re.I)
            if m:
                langs.add(m.group(1).lower())
    return sorted(langs)


def has_search(soup: BeautifulSoup, html: str) -> bool:
    return bool(
        soup.select_one("input[type=search], [class*=search], [id*=search], [aria-label*=Search i]")
        or re.search(r"docsearch|algolia|pagefind|lunr", html, re.I)
    )


# --- contacts ----------------------------------------------------------------

EMAIL_RE = re.compile(r"(?<![\w.+-])[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}\b")
# Only bracketed forms: a bare " at " turns prose ("Acme is at acme.com")
# into fake addresses ("is@acme.com").
_OBFUSCATED_AT = re.compile(r"\s*(\[at\]|\(at\)|\{at\})\s*", re.I)
_OBFUSCATED_DOT = re.compile(r"\s*(\[dot\]|\(dot\)|\{dot\})\s*", re.I)
_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "avif", "css", "js", "ico", "woff", "woff2", "ttf"}
_JUNK_EMAIL_DOMAINS = re.compile(
    r"(^|\.)(example\.(com|org|net)|domain\.com|email\.com|yourdomain\.com|yourcompany\.com|"
    r"sentry\.io|sentry-next\.wixpress\.com|wixpress\.com|ingest\.sentry\.io|"
    r"users\.noreply\.github\.com|noreply\.github\.com)$",
    re.I,
)

# Phone numbers: international-ish groups separated by space, dot, dash or
# parens. Matches are filtered by digit count afterwards.
PHONE_RE = re.compile(
    r"(?<![\w/.=-])"
    r"(?:\+\d{1,3}[\s.-]?)?"
    r"(?:\(\d{1,5}\)[\s.-]?)?"
    r"\d{2,5}(?:[\s.-]\d{2,5}){1,4}"
    r"(?![\w/-])"
)
_DATE_LIKE = re.compile(r"^(19|20)\d{2}[\s.-]\d{1,2}[\s.-]\d{1,2}$|^\d{1,2}[\s.-]\d{1,2}[\s.-](19|20)\d{2}$")


def clean_email(raw: str) -> str | None:
    email = raw.strip().strip(".").lower()
    if email.startswith("mailto:"):
        email = email[7:]
    email = email.split("?", 1)[0]
    m = EMAIL_RE.fullmatch(email)
    if not m:
        return None
    domain = email.rsplit("@", 1)[1]
    if domain.rsplit(".", 1)[-1] in _ASSET_TLDS or _JUNK_EMAIL_DOMAINS.search(domain):
        return None
    local = email.split("@", 1)[0]
    if re.fullmatch(r"[0-9a-f]{16,}", local):  # hashed tracking ids
        return None
    return email


def phone_digits(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def clean_phone(raw: str) -> str | None:
    phone = raw.strip()
    if phone.lower().startswith("tel:"):
        phone = phone[4:]
    phone = re.sub(r"\s+", " ", phone.replace("%20", " ")).strip()
    digits = phone_digits(phone)
    if not 7 <= len(digits) <= 15:
        return None
    if _DATE_LIKE.match(phone) or len(set(digits)) == 1:
        return None
    return phone


def find_emails(soup: BeautifulSoup, html: str) -> set[str]:
    found: set[str] = set()
    for a in soup.select("a[href^='mailto:' i]"):
        if e := clean_email(a["href"]):
            found.add(e)
    text = visible_text(soup)
    deobfuscated = _OBFUSCATED_DOT.sub(".", _OBFUSCATED_AT.sub("@", text))
    for candidate in EMAIL_RE.findall(text) + EMAIL_RE.findall(deobfuscated):
        if e := clean_email(candidate):
            found.add(e)
    # Emails embedded in attributes or inline JSON (e.g. JSON-LD "email" field).
    for candidate in re.findall(r'"email"\s*:\s*"([^"]+)"', html):
        if e := clean_email(candidate):
            found.add(e)
    # mailto: links built by inline scripts, e.g. the fallback a site shows when its contact
    # form is blocked (fusionauth.io). visible_text drops <script>, so look at the raw HTML.
    for candidate in re.findall(r"mailto:([^\"'\s<>?]+)", html, re.I):
        if e := clean_email(candidate):
            found.add(e)
    return found


def find_phones(soup: BeautifulSoup, scan_text: bool) -> set[str]:
    """tel: links always; free-text regex only where phones are expected.

    Running the phone regex over every page produces mostly noise (prices,
    version numbers, ids), so free text is scanned only on contact-like pages
    and in the footer of every page.
    """
    found: set[str] = set()
    for a in soup.select("a[href^='tel:' i]"):
        if p := clean_phone(a["href"]):
            found.add(p)
    regions = [soup] if scan_text else soup.select("footer, [class*=footer], address, [itemprop=telephone]")
    for region in regions:
        for m in PHONE_RE.finditer(visible_text(region)):
            raw = m.group(0)
            # Free text is noisy: without a "+" or "(area)" marker, require a
            # full-length national number rather than e.g. "19 24 20 25".
            if not raw.lstrip().startswith(("+", "(")) and len(phone_digits(raw)) < 9:
                continue
            if p := clean_phone(raw):
                found.add(p)
    return found


def email_belongs_to(email: str, site_domain: str) -> bool:
    return registrable_domain("https://" + email.rsplit("@", 1)[1]) == site_domain
