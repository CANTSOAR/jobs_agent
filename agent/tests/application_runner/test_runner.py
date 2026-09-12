from __future__ import annotations

from datetime import datetime, timezone

from application_runner.models import (
    ApplicationMode,
    ApplicationRecord,
    ApplicationStatus,
    ApprovedAnswer,
    CandidateApplicationData,
    SubmissionPermit,
)
from application_runner.runner import ApplicationRunner
from application_runner.policy import canonical_key
from application_runner.safety import SafetyError, SubmitGuard, TargetValidator

from fakes import InMemoryRepository
from mock_ats import serve_mock_ats


def _application(
    url: str,
    mode: ApplicationMode,
    *,
    fingerprint: str | None = None,
    authorized_at: datetime | None = None,
) -> ApplicationRecord:
    return ApplicationRecord(
        id="app-1",
        user_id="user-1",
        job_id="job-1",
        status=ApplicationStatus.CLAIMED,
        mode=mode,
        application_url=url,
        form_fingerprint=fingerprint,
        submission_authorized_at=authorized_at,
        claimed_by="test-worker",
    )


def _candidate(tmp_path, *, policy=None, answers=()) -> CandidateApplicationData:
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n% test resume\n")
    base_answers = (
        ApprovedAnswer(
            key="work_setting",
            value="Remote",
            approved_for_autofill=True,
            approved_for_submission=True,
        ),
    )
    return CandidateApplicationData(
        profile={
            "first_name": "Ada",
            "last_name": "Applicant",
            "email": "ada@example.test",
            "country": "United States",
            "major": "Computer Science",
        },
        answers=base_answers + tuple(answers),
        resume_path=resume,
        policy=policy or {},
        company_name="Mock Company",
    )


def test_autofill_blocks_all_posts_and_never_submits(tmp_path):
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)

        result = runner.run_claimed(
            _application(f"{base_url}/apply", ApplicationMode.AUTOFILL),
            repository.data,
        )

    assert result.status is ApplicationStatus.READY_TO_SUBMIT
    assert state.post_paths == []
    assert repository.submit_attempts == 0
    assert repository.updates["answers_snapshot"]["blocked_mutation_requests"] > 0


def test_inspection_blocks_page_load_posts(tmp_path):
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)

        result = runner.run_claimed(
            _application(f"{base_url}/apply?loadpost=1", ApplicationMode.INSPECT),
            repository.data,
        )

    assert result.status is ApplicationStatus.INSPECTED
    assert state.post_paths == []
    assert repository.inspection["inspection_data"]["blocked_mutation_requests"] > 0


def test_checkbox_group_is_one_multi_select_field(tmp_path):
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?multi=1", ApplicationMode.AUTOFILL),
            repository.data,
        )

    fields = repository.inspection["form_snapshot"]["fields"]
    discipline_fields = [field for field in fields if field["key"] == "major"]
    assert result.status is ApplicationStatus.READY_TO_SUBMIT
    assert len(discipline_fields) == 1
    assert discipline_fields[0]["kind"] == "multi_select"
    assert discipline_fields[0]["options"] == ["Mathematics", "Computer Science"]
    assert state.post_paths == []


def test_combobox_option_is_selected_without_posting(tmp_path):
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?combo=1", ApplicationMode.AUTOFILL),
            repository.data,
        )

    country = next(
        field
        for field in repository.inspection["form_snapshot"]["fields"]
        if field["key"] == "country"
    )
    assert result.status is ApplicationStatus.READY_TO_SUBMIT
    assert country["kind"] == "combobox"
    assert "country" in repository.updates["answers_snapshot"]["filled_keys"]
    assert state.post_paths == []


def test_unknown_required_question_requires_review_without_posting(tmp_path):
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?unknown=1", ApplicationMode.AUTO_SUBMIT_IF_SAFE),
            repository.data,
        )

    assert result.status is ApplicationStatus.NEEDS_REVIEW
    assert "favorite_protocol" in repository.inspection["unknown_fields"]
    assert state.post_paths == []


def test_sensitive_profile_value_is_not_implicitly_authorized(tmp_path):
    with serve_mock_ats() as (base_url, state):
        candidate = _candidate(tmp_path)
        candidate = CandidateApplicationData(
            profile={**candidate.profile, "requires_sponsorship": False},
            answers=candidate.answers,
            resume_path=candidate.resume_path,
            policy=candidate.policy,
            company_name=candidate.company_name,
        )
        repository = InMemoryRepository(candidate)
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?sensitive=1", ApplicationMode.AUTOFILL),
            candidate,
        )

    assert result.status is ApplicationStatus.NEEDS_REVIEW
    assert "requires_sponsorship" in repository.inspection["unknown_fields"]
    assert state.post_paths == []


def test_sensitive_saved_answer_requires_exact_question_pattern(tmp_path):
    mismatched = ApprovedAnswer(
        key="requires_sponsorship",
        value="No",
        approved_for_autofill=True,
        approved_for_submission=True,
        sensitive=True,
        question_pattern="Do you require sponsorship to work in Canada?",
    )
    with serve_mock_ats() as (base_url, state):
        candidate = _candidate(tmp_path, answers=(mismatched,))
        repository = InMemoryRepository(candidate)
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?sensitive=1", ApplicationMode.AUTOFILL),
            candidate,
        )

    assert result.status is ApplicationStatus.NEEDS_REVIEW
    assert "requires_sponsorship" in repository.inspection["unknown_fields"]
    assert state.post_paths == []


def test_conditional_question_after_fill_forces_fresh_review(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBS_AGENT_TEST_MODE", "1")
    policy = {
        "auto_submit_authorized": True,
        "ats_allowlist": ["mock"],
        "company_allowlist": ["Mock Company"],
        "max_daily_submissions": 1,
    }
    with serve_mock_ats() as (base_url, state):
        candidate = _candidate(tmp_path, policy=policy)
        repository = InMemoryRepository(candidate)
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(f"{base_url}/apply?dynamic=1", ApplicationMode.AUTO_SUBMIT_IF_SAFE),
            candidate,
        )

    assert result.status is ApplicationStatus.NEEDS_REVIEW
    assert "work_authorization" in repository.inspection["unknown_fields"]
    assert any("form changed after autofill" in blocker for blocker in result.blockers)
    assert state.post_paths == []


def test_demographic_alias_does_not_collide_with_city():
    assert canonical_key("Race / Ethnicity") == "race_ethnicity"


def test_mock_auto_submit_posts_exactly_once(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBS_AGENT_TEST_MODE", "1")
    policy = {
        "auto_submit_authorized": True,
        "ats_allowlist": ["mock"],
        "company_allowlist": ["Mock Company"],
        "max_daily_submissions": 1,
    }
    with serve_mock_ats() as (base_url, state):
        repository = InMemoryRepository(_candidate(tmp_path, policy=policy))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        application = _application(
            f"{base_url}/apply", ApplicationMode.AUTO_SUBMIT_IF_SAFE
        )

        result = runner.run_claimed(application, repository.data)
        duplicate_result = runner.run_claimed(application, repository.data)

    assert result.status is ApplicationStatus.SUBMITTED
    assert result.receipt is not None
    assert result.receipt.confirmation_id == "MOCK-1234"
    assert duplicate_result.status is ApplicationStatus.SUBMISSION_UNKNOWN
    assert state.count("/submit") == 1
    assert state.count("/autosave") == 0
    assert repository.submit_attempts == 1


def test_changed_form_cannot_reuse_application_authorization(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBS_AGENT_TEST_MODE", "1")
    with serve_mock_ats() as (base_url, state):
        inspection_repository = InMemoryRepository(_candidate(tmp_path))
        inspection_runner = ApplicationRunner(
            inspection_repository, test_mode=True, headless=True
        )
        inspection_runner.run_claimed(
            _application(f"{base_url}/apply", ApplicationMode.INSPECT),
            inspection_repository.data,
        )
        old_fingerprint = inspection_repository.inspection["fingerprint"]

        policy = {
            "ats_allowlist": ["mock"],
            "company_allowlist": ["Mock Company"],
            "max_daily_submissions": 1,
        }
        repository = InMemoryRepository(_candidate(tmp_path, policy=policy))
        runner = ApplicationRunner(repository, test_mode=True, headless=True)
        result = runner.run_claimed(
            _application(
                f"{base_url}/apply?changed=1",
                ApplicationMode.AUTO_SUBMIT_IF_SAFE,
                fingerprint=old_fingerprint,
                authorized_at=datetime.now(timezone.utc),
            ),
            repository.data,
        )

    assert result.status is ApplicationStatus.READY_TO_SUBMIT
    assert any("form changed" in blocker for blocker in result.blockers)
    assert state.post_paths == []


def test_live_guard_is_disabled_and_private_targets_are_rejected():
    validator = TargetValidator(
        resolver=lambda *args, **kwargs: [
            (None, None, None, None, ("93.184.216.34", 443))
        ]
    )
    guard = SubmitGuard(validator=validator, live_enabled="")
    permit = SubmissionPermit(
        application_id="app-1",
        mode=ApplicationMode.AUTO_SUBMIT_IF_SAFE,
        target_url="https://boards.greenhouse.io/example/jobs/123",
        adapter="greenhouse",
        current_fingerprint="current",
        authorized_fingerprint="current",
        submission_authorized_at=datetime.now(timezone.utc),
        policy_auto_submit_authorized=False,
        adapter_allowlist=("greenhouse",),
        company_name="Example",
        company_allowlist=("Example",),
        max_daily_submissions=1,
    )
    try:
        guard.validate(permit)
    except SafetyError as exc:
        assert "live submission is disabled" in str(exc)
    else:
        raise AssertionError("live submission must be disabled without the exact environment gate")

    untrusted_guard = SubmitGuard(
        validator=validator,
        live_enabled=SubmitGuard.LIVE_ENABLE_VALUE,
    )
    untrusted_permit = SubmissionPermit(
        **{
            **permit.__dict__,
            "target_url": "https://example.com/apply",
        }
    )
    try:
        untrusted_guard.validate(untrusted_permit)
    except SafetyError as exc:
        assert "trusted host" in str(exc)
    else:
        raise AssertionError("live adapters must be bound to their trusted target hosts")

    private_validator = TargetValidator(
        resolver=lambda *args, **kwargs: [
            (None, None, None, None, ("127.0.0.1", 443))
        ]
    )
    try:
        private_validator.validate("https://internal.example/apply")
    except SafetyError as exc:
        assert "private" in str(exc)
    else:
        raise AssertionError("private network targets must be rejected")


def test_submit_guard_rejects_daily_limits_above_hard_ceiling():
    validator = TargetValidator(
        resolver=lambda *args, **kwargs: [
            (None, None, None, None, ("93.184.216.34", 443))
        ]
    )
    guard = SubmitGuard(
        validator=validator,
        live_enabled=SubmitGuard.LIVE_ENABLE_VALUE,
    )
    permit = SubmissionPermit(
        application_id="app-1",
        mode=ApplicationMode.AUTO_SUBMIT_IF_SAFE,
        target_url="https://boards.greenhouse.io/example/jobs/123",
        adapter="greenhouse",
        current_fingerprint="current",
        authorized_fingerprint="current",
        submission_authorized_at=datetime.now(timezone.utc),
        policy_auto_submit_authorized=True,
        adapter_allowlist=("greenhouse",),
        company_name="Example",
        company_allowlist=("Example",),
        max_daily_submissions=21,
    )

    try:
        guard.validate(permit)
    except SafetyError as exc:
        assert "cannot exceed 20" in str(exc)
    else:
        raise AssertionError("the worker must enforce the daily submission ceiling")
