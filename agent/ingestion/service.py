from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Iterable

from ingestion.normalize import build_dedupe_key
from ingestion.simplify import DEFAULT_SOURCE_KEY, DEFAULT_SOURCE_URL, fetch_snapshot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first(data: Any) -> dict[str, Any] | None:
    if isinstance(data, list):
        return data[0] if data else None
    return data if isinstance(data, dict) else None


def _configured_terms() -> tuple[str, ...] | None:
    raw = os.environ.get("SIMPLIFY_TERMS")
    if raw is None or not raw.strip():
        return None
    terms = tuple(term.strip() for term in raw.split(",") if term.strip())
    return terms or None


def _retry_metadata_write(operation, *, attempts: int = 3):
    """Retry idempotent run/source metadata writes after transient gateway errors."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(0.5 * (2**attempt))
    assert last_error is not None
    raise last_error


def _get_or_create_source(
    supabase,
    *,
    key: str,
    url: str,
    terms: Iterable[str] | None,
) -> dict[str, Any]:
    config = {"terms": list(terms) if terms else []}
    existing_result = (
        supabase.table("ingestion_sources")
        .select("*")
        .eq("key", key)
        .limit(1)
        .execute()
    )
    existing = _first(existing_result.data)
    if existing:
        return existing

    result = (
        supabase.table("ingestion_sources")
        .insert(
            {"key": key, "kind": "simplify_json", "url": url, "config": config},
        )
        .execute()
    )
    source = _first(result.data)
    if source:
        return source
    result = supabase.table("ingestion_sources").select("*").eq("key", key).limit(1).execute()
    source = _first(result.data)
    if not source:
        raise RuntimeError(f"could not create or load ingestion source {key!r}")
    return source


def sync_simplify_feed(
    supabase,
    *,
    url: str | None = None,
    source_key: str = DEFAULT_SOURCE_KEY,
    terms: Iterable[str] | None = None,
    batch_size: int | None = None,
) -> dict[str, int | str]:
    """Conditionally fetch and idempotently persist the official Simplify feed."""
    url = url or os.environ.get("SIMPLIFY_SOURCE_URL", DEFAULT_SOURCE_URL)
    terms = tuple(terms) if terms is not None else _configured_terms()
    batch_size = batch_size or int(os.environ.get("SIMPLIFY_BATCH_SIZE", "100"))
    batch_size = max(1, min(batch_size, 500))
    timeout = float(os.environ.get("SIMPLIFY_HTTP_TIMEOUT", "30"))

    source = _get_or_create_source(supabase, key=source_key, url=url, terms=terms)
    run_result = (
        supabase.table("ingestion_runs")
        .insert({"source_id": source["id"], "status": "running"})
        .execute()
    )
    run = _first(run_result.data)
    if not run:
        raise RuntimeError("could not create ingestion run")

    try:
        # An ETag belongs to both the URL and our local filtering configuration.
        # A configuration change must reparse the body even if upstream is unchanged.
        desired_config = {"terms": list(terms) if terms else []}
        same_request = source.get("url") == url and source.get("config") == desired_config
        snapshot = fetch_snapshot(
            url,
            source_key=source_key,
            terms=terms,
            etag=source.get("etag") if same_request else None,
            last_modified=source.get("last_modified") if same_request else None,
            timeout=timeout,
        )

        if snapshot.not_modified:
            finished_at = _now()
            _retry_metadata_write(
                lambda: supabase.table("ingestion_runs").update(
                    {
                        "status": "not_modified",
                        "upstream_version": source.get("etag") or source.get("last_modified"),
                        "finished_at": finished_at,
                    }
                ).eq("id", run["id"]).execute()
            )
            _retry_metadata_write(
                lambda: supabase.table("ingestion_sources").update(
                    {"last_checked_at": finished_at, "last_error": None}
                ).eq("id", source["id"]).execute()
            )
            return {"status": "not_modified", "records_seen": 0, "jobs_inserted": 0, "jobs_updated": 0}

        if not snapshot.records:
            raise RuntimeError("Simplify feed produced zero valid records; refusing to deactivate existing jobs")

        inserted = 0
        updated = 0
        for offset in range(0, len(snapshot.records), batch_size):
            batch = snapshot.records[offset : offset + batch_size]
            result = supabase.rpc(
                "ingest_job_batch",
                {
                    "p_source_id": source["id"],
                    "p_run_id": run["id"],
                    "p_records": [record.as_rpc_record() for record in batch],
                },
            ).execute()
            counts = _first(result.data) or {}
            inserted += int(counts.get("jobs_inserted", 0))
            updated += int(counts.get("jobs_updated", 0))

        supabase.rpc(
            "finalize_ingestion_run",
            {"p_source_id": source["id"], "p_run_id": run["id"]},
        ).execute()

        finished_at = _now()
        upstream_version = snapshot.etag or snapshot.last_modified
        _retry_metadata_write(
            lambda: supabase.table("ingestion_runs").update(
                {
                    "status": "completed",
                    "upstream_version": upstream_version,
                    "records_seen": len(snapshot.records),
                    "jobs_inserted": inserted,
                    "jobs_updated": updated,
                    "finished_at": finished_at,
                }
            ).eq("id", run["id"]).execute()
        )
        _retry_metadata_write(
            lambda: supabase.table("ingestion_sources").update(
                {
                    "url": url,
                    "config": desired_config,
                    "etag": snapshot.etag,
                    "last_modified": snapshot.last_modified,
                    "last_checked_at": finished_at,
                    "last_success_at": finished_at,
                    "last_error": None,
                }
            ).eq("id", source["id"]).execute()
        )
        return {
            "status": "completed",
            "records_seen": len(snapshot.records),
            "jobs_inserted": inserted,
            "jobs_updated": updated,
        }
    except Exception as exc:
        finished_at = _now()
        error = f"{type(exc).__name__}: {exc}"[:4000]
        try:
            _retry_metadata_write(
                lambda: supabase.table("ingestion_runs").update(
                    {"status": "failed", "error": error, "finished_at": finished_at}
                ).eq("id", run["id"]).execute()
            )
            _retry_metadata_write(
                lambda: supabase.table("ingestion_sources").update(
                    {"last_checked_at": finished_at, "last_error": error}
                ).eq("id", source["id"]).execute()
            )
        except Exception as reporting_error:
            print(f"Could not persist ingestion failure metadata: {reporting_error}")
        raise


def upsert_scraped_job(
    supabase,
    *,
    company_id: str,
    company_name: str,
    title: str,
    url: str | None,
    location: str | None,
) -> dict[str, Any] | None:
    """Insert a scraper result without duplicating an existing feed/ATS job."""
    canonical_url, dedupe_key = build_dedupe_key(
        url or "",
        company_name=company_name,
        title=title,
        locations=(location,) if location else (),
    )
    existing_result = (
        supabase.table("jobs")
        .select("id, discovery_method")
        .eq("dedupe_key", dedupe_key)
        .limit(1)
        .execute()
    )
    existing = _first(existing_result.data)
    if not existing and url:
        legacy_result = (
            supabase.table("jobs")
            .select("id, discovery_method")
            .is_("dedupe_key", "null")
            .eq("url", url)
            .limit(1)
            .execute()
        )
        existing = _first(legacy_result.data)
    payload = {
        "company_id": company_id,
        "title": title,
        "url": url,
        "canonical_url": canonical_url or None,
        "dedupe_key": dedupe_key,
        "location": location,
        "is_active": True,
        "last_seen_at": _now(),
    }
    if existing:
        payload["discovery_method"] = (
            "mixed" if existing.get("discovery_method") == "feed" else existing.get("discovery_method", "scrape")
        )
        result = supabase.table("jobs").update(payload).eq("id", existing["id"]).execute()
        return _first(result.data) or {"id": existing["id"], **payload}

    payload["discovery_method"] = "scrape"
    try:
        result = supabase.table("jobs").insert(payload).execute()
        return _first(result.data)
    except Exception:
        # A concurrent discovery worker may have won the unique-key race.
        result = (
            supabase.table("jobs")
            .select("*")
            .eq("dedupe_key", dedupe_key)
            .limit(1)
            .execute()
        )
        return _first(result.data)
