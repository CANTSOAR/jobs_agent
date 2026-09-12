from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizedJob:
    source_key: str
    external_id: str
    company_name: str
    title: str
    url: str
    canonical_url: str
    dedupe_key: str
    locations: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()
    category: str | None = None
    sponsorship: str | None = None
    degrees: tuple[str, ...] = ()
    posted_at: str | None = None
    source_updated_at: str | None = None
    source_active: bool = True
    company_url: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def location(self) -> str | None:
        return " | ".join(self.locations) if self.locations else None

    def as_rpc_record(self) -> dict[str, Any]:
        return {
            "external_id": self.external_id,
            "company_name": self.company_name,
            "title": self.title,
            "url": self.url,
            "canonical_url": self.canonical_url,
            "dedupe_key": self.dedupe_key,
            "location": self.location,
            "locations": list(self.locations),
            "terms": list(self.terms),
            "category": self.category,
            "sponsorship": self.sponsorship,
            "degrees": list(self.degrees),
            "posted_at": self.posted_at,
            "source_updated_at": self.source_updated_at,
            "source_active": self.source_active,
            "company_url": self.company_url,
            "raw_payload": self.raw_payload,
        }


@dataclass(frozen=True, slots=True)
class FeedSnapshot:
    records: tuple[NormalizedJob, ...] = ()
    etag: str | None = None
    last_modified: str | None = None
    not_modified: bool = False
