import hashlib
from typing import Optional
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# A real browser (rather than a plain HTTP client) gets past basic WAF/UA checks and
# executes JS-rendered pages. Kept as one process-wide instance and reused across every
# fetch_html() call in a run -- launching a fresh browser per call is slow. Cloudflare
# Enterprise-style bot management can still detect plain headless Chromium; this isn't
# a guaranteed bypass for every site, just a real improvement over a raw HTTP client.
_playwright = None
_browser = None


def _get_browser():
    global _playwright, _browser
    if _browser is None:
        _playwright = sync_playwright().start()
        _browser = _playwright.chromium.launch(headless=True)
    return _browser


def close_browser():
    global _playwright, _browser
    if _browser is not None:
        _browser.close()
        _browser = None
    if _playwright is not None:
        _playwright.stop()
        _playwright = None


def fetch_html(url: str) -> str:
    browser = _get_browser()
    page = browser.new_page(user_agent=USER_AGENT, locale="en-US")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        return page.content()
    finally:
        page.close()


def extract_favicon_url(html: str, base_url: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    for rel in ("icon", "shortcut icon", "apple-touch-icon"):
        link = soup.find("link", rel=lambda value: value and rel in value.lower())
        if link and link.get("href"):
            return urljoin(base_url, link["href"])
    return urljoin(base_url, "/favicon.ico")


def extract_linkedin_company_url(html: str) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", href=lambda href: href and "linkedin.com/company" in href)
    if not link:
        return None
    parts = urlsplit(link["href"].strip())
    return f"{parts.scheme}://{parts.netloc}{parts.path}"


def extract_visible_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    lines = [line.strip() for line in soup.get_text(separator="\n").splitlines() if line.strip()]
    return "\n".join(lines)


def hash_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
