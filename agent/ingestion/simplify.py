from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ingestion.models import FeedSnapshot, NormalizedJob
from ingestion.normalize import build_dedupe_key, normalize_space

DEFAULT_SOURCE_KEY = "simplify_summer_2027"
DEFAULT_SOURCE_URL = (
    "https://raw.githubusercontent.com/SimplifyJobs/"
    "Summer2027-Internships/dev/.github/scripts/listings.json"
)
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class SimplifyFeedError(RuntimeError):
    pass


def _iso_from_epoch(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _clean_string_list(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(
        cleaned
        for item in value
        if isinstance(item, str) and (cleaned := normalize_space(item))
    )


def parse_listings(
    payload: Any,
    *,
    source_key: str = DEFAULT_SOURCE_KEY,
    terms: Iterable[str] | None = None,
) -> tuple[NormalizedJob, ...]:
    if not isinstance(payload, list):
        raise SimplifyFeedError("Simplify listings payload must be a JSON array")

    selected_terms = {normalize_space(term).lower() for term in terms or () if normalize_space(term)}
    records: list[NormalizedJob] = []

    for raw in payload:
        if not isinstance(raw, dict):
            continue

        external_id = normalize_space(str(raw.get("id") or ""))
        company_name = normalize_space(str(raw.get("company_name") or ""))
        title = normalize_space(str(raw.get("title") or ""))
        url = str(raw.get("url") or "").strip()
        record_terms = _clean_string_list(raw.get("terms"))
        source_active = bool(raw.get("active", False)) and bool(raw.get("is_visible", False))

        # Missing active records are reconciled by finalize_ingestion_run, so there
        # is no value in materializing the feed's large inactive history as jobs.
        if not source_active or not external_id or not company_name or not title or not url:
            continue
        if selected_terms and not selected_terms.intersection(term.lower() for term in record_terms):
            continue

        locations = _clean_string_list(raw.get("locations"))
        canonical_url, dedupe_key = build_dedupe_key(
            url,
            company_name=company_name,
            title=title,
            locations=locations,
        )
        records.append(
            NormalizedJob(
                source_key=source_key,
                external_id=external_id,
                company_name=company_name,
                title=title,
                url=url,
                canonical_url=canonical_url,
                dedupe_key=dedupe_key,
                locations=locations,
                terms=record_terms,
                category=normalize_space(str(raw.get("category") or "")) or None,
                sponsorship=normalize_space(str(raw.get("sponsorship") or "")) or None,
                degrees=_clean_string_list(raw.get("degrees")),
                posted_at=_iso_from_epoch(raw.get("date_posted")),
                source_updated_at=_iso_from_epoch(raw.get("date_updated")),
                source_active=True,
                company_url=str(raw.get("company_url") or "").strip() or None,
                raw_payload=raw,
            )
        )

    return tuple(records)


def fetch_snapshot(
    url: str = DEFAULT_SOURCE_URL,
    *,
    source_key: str = DEFAULT_SOURCE_KEY,
    terms: Iterable[str] | None = None,
    etag: str | None = None,
    last_modified: str | None = None,
    timeout: float = 30,
) -> FeedSnapshot:
    headers = {
        "Accept": "application/json",
        "User-Agent": "jobs-agent/1.0 (+https://github.com/CANTSOAR/jobs_agent)",
    }
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    request = Request(url, headers=headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as exc:
        if exc.code == 304:
            return FeedSnapshot(etag=etag, last_modified=last_modified, not_modified=True)
        raise SimplifyFeedError(f"Simplify feed returned HTTP {exc.code}") from exc

    with response:
        declared_length = response.headers.get("Content-Length")
        if declared_length and int(declared_length) > MAX_RESPONSE_BYTES:
            raise SimplifyFeedError("Simplify feed exceeds the configured response limit")
        body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SimplifyFeedError("Simplify feed exceeds the configured response limit")
        response_etag = response.headers.get("ETag")
        response_last_modified = response.headers.get("Last-Modified")

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SimplifyFeedError("Simplify feed did not contain valid JSON") from exc

    # Validate an RFC timestamp if supplied so malformed proxy headers are not stored.
    if response_last_modified:
        try:
            parsedate_to_datetime(response_last_modified)
        except (TypeError, ValueError):
            response_last_modified = None

    return FeedSnapshot(
        records=parse_listings(payload, source_key=source_key, terms=terms),
        etag=response_etag,
        last_modified=response_last_modified,
    )
