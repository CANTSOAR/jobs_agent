import hashlib
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

# Several career sites 403 a self-identifying bot string outright. A realistic
# browser UA + Accept headers gets past basic WAF checks (though not Cloudflare-style
# JS challenges, which no header change can bypass without a real browser).
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str) -> str:
    response = httpx.get(url, headers=REQUEST_HEADERS, timeout=20, follow_redirects=True)
    response.raise_for_status()
    return response.text


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
