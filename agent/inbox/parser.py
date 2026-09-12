from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from email.utils import parseaddr

from bs4 import BeautifulSoup


PARSER_VERSION = "swelist-v1"
SWELIST_SENDER = "noreply@swelist.com"

_JOB_LINE = re.compile(r"^(?P<company>[^:\n]{1,160}):\s+(?P<title>[^\n]{2,300})$")
_START_MARKERS = ("tech internships from swelist", "daily update")
_END_MARKERS = ("see more details by visiting the repo", "click here to unsubscribe")


@dataclass(frozen=True)
class DigestListing:
    company: str
    title: str
    url: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return asdict(self)


def _clean(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def _parse_job_label(label: str, url: str | None = None) -> DigestListing | None:
    match = _JOB_LINE.match(_clean(label))
    if not match:
        return None

    company = _clean(match.group("company"))
    title = _clean(match.group("title"))
    if company.lower() in {"link to simplify", "subject", "from", "to"}:
        return None
    return DigestListing(company=company, title=title, url=url)


def parse_swelist_text(text: str) -> list[DigestListing]:
    """Parse the text fallback from a SWEList digest.

    Plain-text copies do not contain application URLs, but are still useful for
    triggering and reconciling the structured Simplify feed.
    """
    lines = [_clean(line) for line in text.splitlines()]
    start = 0
    for index, line in enumerate(lines):
        if any(marker in line.lower() for marker in _START_MARKERS):
            start = index + 1
            break

    listings: list[DigestListing] = []
    seen: set[tuple[str, str, str | None]] = set()
    for line in lines[start:]:
        if any(marker in line.lower() for marker in _END_MARKERS):
            break
        listing = _parse_job_label(line)
        if not listing:
            continue
        key = (listing.company.casefold(), listing.title.casefold(), listing.url)
        if key not in seen:
            listings.append(listing)
            seen.add(key)
    return listings


def parse_swelist_html(html: str) -> list[DigestListing]:
    """Parse linked `Company: Role` labels from the original HTML message."""
    soup = BeautifulSoup(html, "html.parser")
    listings: list[DigestListing] = []
    seen: set[tuple[str, str, str | None]] = set()

    for anchor in soup.find_all("a", href=True):
        listing = _parse_job_label(anchor.get_text(" ", strip=True), anchor["href"].strip())
        if not listing:
            continue
        key = (listing.company.casefold(), listing.title.casefold(), listing.url)
        if key not in seen:
            listings.append(listing)
            seen.add(key)

    # Some newsletter templates put the URL on a wrapping element or strip it
    # from a plain-text alternative. Preserve those unlinked rows as a fallback.
    linked_pairs = {(item.company.casefold(), item.title.casefold()) for item in listings}
    for item in parse_swelist_text(soup.get_text("\n")):
        if (item.company.casefold(), item.title.casefold()) not in linked_pairs:
            listings.append(item)

    return listings


def classify_message(sender: str | None, subject: str | None, text: str) -> str:
    sender_address = parseaddr(sender or "")[1].casefold()
    haystack = f"{subject or ''}\n{text[:4000]}".casefold()
    # A message mentioning SWEList is not enough to treat it as a trusted digest.
    # The Gmail query is narrow too, but this exact sender check keeps a broader
    # operator-supplied query from turning spoofed content into a discovery signal.
    if sender_address == SWELIST_SENDER:
        return "swelist_digest"
    if any(value in haystack for value in ("application received", "application submitted", "thank you for applying")):
        return "application_confirmation"
    if any(value in haystack for value in ("online assessment", "coding assessment", "take-home assessment")):
        return "assessment"
    if any(value in haystack for value in ("schedule an interview", "interview invitation", "interview availability")):
        return "interview"
    if any(value in haystack for value in ("not moving forward", "other candidates", "unable to offer")):
        return "rejection"
    return "unknown"
