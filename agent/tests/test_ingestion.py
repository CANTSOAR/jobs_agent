from ingestion.normalize import build_dedupe_key, canonicalize_url
from ingestion.simplify import parse_listings


def _listing(**overrides):
    row = {
        "id": "source-1",
        "company_name": "Example Corp",
        "title": "Software Engineering Intern",
        "url": "https://boards.greenhouse.io/example/jobs/123?utm_source=email",
        "locations": ["New York, NY"],
        "terms": ["Summer 2027"],
        "category": "Software Engineering",
        "active": True,
        "is_visible": True,
        "date_posted": 1788912000,
    }
    row.update(overrides)
    return row


def test_parse_listings_keeps_only_active_visible_jobs():
    records = parse_listings(
        [
            _listing(),
            _listing(id="inactive", active=False),
            _listing(id="hidden", is_visible=False),
        ]
    )

    assert len(records) == 1
    assert records[0].external_id == "source-1"
    assert records[0].source_active is True
    assert records[0].dedupe_key == "greenhouse:123"


def test_canonical_url_removes_tracking_but_preserves_identity_parameters():
    url = "https://Example.com/jobs/apply?utm_source=email&job=42&ref=mail#section"
    assert canonicalize_url(url) == "https://example.com/jobs/apply?job=42"


def test_ats_dedupe_key_is_stable_across_tracking_links():
    first = build_dedupe_key(
        "https://job-boards.greenhouse.io/acme/jobs/987?gh_src=abc",
        company_name="Acme",
        title="Intern",
    )
    second = build_dedupe_key(
        "https://job-boards.greenhouse.io/acme/jobs/987?utm_campaign=digest",
        company_name="Acme",
        title="Intern",
    )
    assert first[1] == second[1] == "greenhouse:987"
