"""URL normalisation and same-site checks."""

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import tldextract

# Offline: use the bundled public-suffix snapshot so results do not depend on
# network access. Private suffixes (github.io, vercel.app, ...) are included so
# that two different user sites on github.io are not treated as one site.
_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)

_TRACKING_PARAMS = {"ref", "ref_src", "fbclid", "gclid", "mc_cid", "mc_eid"}

SKIP_EXTENSIONS = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".avif", ".bmp",
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".rar", ".7z", ".dmg", ".exe", ".msi", ".apk",
    ".mp4", ".webm", ".mov", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".css", ".js", ".mjs", ".map", ".json", ".xml", ".rss", ".atom", ".txt", ".csv",
)

# Sites that host many unrelated products. A lead whose website is one of
# these is not a product website.
NON_PRODUCT_DOMAINS = {
    "github.com", "gitlab.com", "bitbucket.org", "sourceforge.net",
    "npmjs.com", "pypi.org", "crates.io", "rubygems.org", "nuget.org", "pkg.go.dev",
    "producthunt.com", "twitter.com", "x.com", "linkedin.com", "facebook.com",
    "instagram.com", "youtube.com", "youtu.be", "medium.com", "reddit.com",
    "apple.com", "google.com", "microsoft.com", "discord.gg", "discord.com", "t.me",
    "huggingface.co", "notion.so", "linktr.ee",
}


def normalize_url(url: str | None, base: str | None = None) -> str | None:
    """Return an absolute http(s) URL without fragment or tracking params, or None.

    Without `base`, a bare host such as "example.com" is accepted and given https.
    """
    if not url:
        return None
    url = url.strip()
    if base:
        url = urljoin(base, url)
    elif url.startswith("//"):
        url = "https:" + url
    elif not re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I):
        url = "https://" + url

    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not (k.lower().startswith("utm_") or k.lower() in _TRACKING_PARAMS)
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", urlencode(query), ""))


def hostname(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def registrable_domain(url: str) -> str:
    host = hostname(url)
    return _EXTRACT(host).top_domain_under_public_suffix or host


def same_site(url: str, site_domain: str) -> bool:
    return registrable_domain(url) == site_domain


def site_root(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/"


def is_crawlable(url: str) -> bool:
    return not urlsplit(url).path.lower().endswith(SKIP_EXTENSIONS)


def is_product_website(url: str) -> bool:
    return registrable_domain(url) not in NON_PRODUCT_DOMAINS
