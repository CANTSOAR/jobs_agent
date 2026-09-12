from evaluator.relevance import passes_job_preferences


def _job(**overrides):
    job = {
        "title": "Software Engineering Intern",
        "location": "New York, NY",
        "category": "Software Engineering",
        "terms": ["Summer 2027"],
        "companies": {"name": "Example"},
    }
    job.update(overrides)
    return job


def test_dashboard_preference_keys_are_enforced():
    preferences = {
        "target_categories": ["Software Engineering"],
        "target_terms": ["Summer 2027"],
        "preferred_locations": ["New York"],
        "excluded_title_keywords": ["Senior"],
        "allow_remote": True,
        "willing_to_relocate": False,
    }
    assert passes_job_preferences(_job(), preferences)
    assert not passes_job_preferences(_job(title="Senior Software Engineer"), preferences)
    assert not passes_job_preferences(_job(category="Product Management"), preferences)
    assert not passes_job_preferences(_job(terms=["Fall 2027"], title="Developer"), preferences)
    assert not passes_job_preferences(_job(location="Austin, TX"), preferences)
    assert passes_job_preferences(_job(location="Remote - US"), preferences)


def test_relocation_and_missing_upstream_values_fail_open():
    preferences = {
        "preferred_locations": ["New York"],
        "willing_to_relocate": True,
        "target_categories": ["Software Engineering"],
    }
    assert passes_job_preferences(_job(location="Austin, TX"), preferences)
    assert passes_job_preferences(_job(location=None, category=None), preferences)


def test_remote_can_be_excluded_explicitly():
    assert not passes_job_preferences(_job(location="Remote"), {"allow_remote": False})
