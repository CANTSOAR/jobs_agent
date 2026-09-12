from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "gh_src",
    "lever-source",
    "ref",
    "referrer",
    "source",
    "trk",
}


def normalize_space(value: str) -> str:
    return " ".join(value.split())


def normalize_company_name(value: str) -> str:
    """Match the generated normalized_name expression in the database."""
    return normalize_space(value).lower()


def canonicalize_url(value: str) -> str:
    """Remove presentation-only URL differences without deleting job identity.

    Query parameters are retained unless they are a small, explicit set of tracking
    keys.  Some ATSs encode requisition identity in query parameters, so a generic
    "drop the query string" strategy is unsafe.
    """
    value = value.strip()
    if not value:
        return ""

    parts = urlsplit(value)
    scheme = parts.scheme.lower() or "https"
    hostname = (parts.hostname or "").lower()
    if not hostname:
        return value

    port = parts.port
    netloc = hostname
    if port and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        netloc = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    # /apply is merely the form variant for Lever and Ashby job URLs.
    if ("lever.co" in hostname or "ashbyhq.com" in hostname) and path.endswith("/apply"):
        path = path[:-6]

    query = []
    for key, item in parse_qsl(parts.query, keep_blank_values=True):
        lowered = key.lower()
        if lowered.startswith("utm_") or lowered in _TRACKING_KEYS:
            continue
        query.append((key, item))
    query.sort()

    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def _ats_identity(canonical_url: str) -> str | None:
    parts = urlsplit(canonical_url)
    host = (parts.hostname or "").lower()
    segments = [segment for segment in parts.path.split("/") if segment]

    if "greenhouse.io" in host:
        match = re.search(r"/(?:jobs?|job_app)/(\d+)(?:/|$)", parts.path)
        query = dict(parse_qsl(parts.query))
        job_id = match.group(1) if match else query.get("gh_jid")
        if job_id:
            return f"greenhouse:{job_id}"

    if host.endswith("lever.co") and len(segments) >= 2:
        return f"lever:{segments[0].lower()}:{segments[1].lower()}"

    if host.endswith("ashbyhq.com") and len(segments) >= 2:
        return f"ashby:{segments[0].lower()}:{segments[1].lower()}"

    if "myworkdayjobs.com" in host and segments:
        # Workday URLs end in a stable requisition id, commonly R123456 or JR-123.
        tail = segments[-1]
        match = re.search(r"(?:_|-)((?:R|JR)[A-Z0-9_-]*\d[A-Z0-9_-]*)$", tail, re.IGNORECASE)
        requisition = match.group(1) if match else tail
        tenant = host.split(".myworkdayjobs.com", 1)[0]
        return f"workday:{tenant}:{requisition.lower()}"

    return None


def build_dedupe_key(
    url: str,
    *,
    company_name: str,
    title: str,
    locations: tuple[str, ...] | list[str] = (),
) -> tuple[str, str]:
    canonical = canonicalize_url(url)
    if canonical:
        ats_identity = _ats_identity(canonical)
        if ats_identity:
            return canonical, ats_identity
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return canonical, f"url:{digest}"

    # Feeds used by this project normally include a URL. This fallback is purposely
    # conservative and should not be used to merge two records within one source.
    fingerprint = "\x1f".join(
        [
            normalize_company_name(company_name),
            normalize_space(title).lower(),
            *sorted(normalize_space(location).lower() for location in locations),
        ]
    )
    return "", f"fallback:{hashlib.sha256(fingerprint.encode('utf-8')).hexdigest()}"
