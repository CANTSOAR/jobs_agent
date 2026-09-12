from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .adapters import AdapterRegistry
from .artifacts import PrivateArtifactStore
from .browser import ApplicationBrowser
from .models import (
    ApplicationMode,
    ApplicationRecord,
    ApplicationStatus,
    CandidateApplicationData,
    RunResult,
    SubmissionPermit,
)
from .policy import AnswerPolicy
from .repository import ApplicationRepository
from .safety import MutationFirewall, SafetyError, SubmitGuard, TargetValidator


class ApplicationRunner:
    def __init__(
        self,
        repository: ApplicationRepository,
        *,
        test_mode: bool = False,
        headless: bool = False,
        user_data_dir: Path | None = None,
        artifact_dir: Path | None = None,
        registry: AdapterRegistry | None = None,
        browser_factory: Callable[[], ApplicationBrowser] | None = None,
        submit_guard: SubmitGuard | None = None,
    ) -> None:
        self.repository = repository
        self.validator = TargetValidator(test_mode=test_mode)
        self.test_mode = test_mode
        self.registry = registry or AdapterRegistry()
        self.artifacts = PrivateArtifactStore(artifact_dir)
        self.browser_factory = browser_factory or (
            lambda: ApplicationBrowser(
                validator=self.validator,
                headless=headless,
                user_data_dir=user_data_dir,
            )
        )
        self.submit_guard = submit_guard or SubmitGuard(validator=self.validator)

    def _transition_failure(self, application: ApplicationRecord, exc: Exception) -> RunResult:
        message = f"{type(exc).__name__}: {exc}"
        self.repository.transition(application, ApplicationStatus.FAILED, message=message)
        return RunResult(application.id, ApplicationStatus.FAILED, blockers=(message,))

    def run_claimed(
        self,
        application: ApplicationRecord,
        data: CandidateApplicationData,
    ) -> RunResult:
        # This check happens before opening a page or overwriting any state.  It is the
        # final backstop if a stale queue item is ever delivered twice.
        if self.repository.has_submission_attempt(application):
            return RunResult(
                application.id,
                ApplicationStatus.SUBMISSION_UNKNOWN,
                application.adapter,
                application.form_fingerprint,
                ("a final submission was already attempted; refusing to open the form",),
            )

        if application.mode is ApplicationMode.TRACK_ONLY:
            self.repository.transition(
                application,
                ApplicationStatus.SKIPPED,
                message="track_only applications are not opened by the browser runner",
            )
            return RunResult(application.id, ApplicationStatus.SKIPPED)

        if data.resume_path is not None and not data.resume_path.is_file():
            return self._transition_failure(
                application, FileNotFoundError(f"resume file not found: {data.resume_path}")
            )

        click_committed = False
        adapter_name: str | None = None
        fingerprint: str | None = None
        firewall = MutationFirewall()

        try:
            with self.browser_factory() as browser:
                page = browser.open(
                    application.application_url,
                    mutation_firewall=firewall,
                )
                page.wait_for_timeout(100)
                adapter = self.registry.select(page.url, page)
                adapter_name = adapter.name
                form = adapter.inspect(page)
                fingerprint = form.fingerprint
                self.validator.validate(form.action_url)

                policy = AnswerPolicy(
                    require_review_on_unknown_question=bool(
                        data.policy.get("require_review_on_unknown_question", True)
                    )
                )
                resolved = policy.resolve(
                    form,
                    data.profile,
                    data.answers,
                    resume_path=str(data.resume_path) if data.resume_path else None,
                )

                captcha_detected = bool(
                    page.locator(
                        'iframe[src*="recaptcha" i], iframe[src*="hcaptcha" i], '
                        '[class*="captcha" i], [id*="captcha" i], '
                        '[data-sitekey]'
                    ).count()
                )

                self.repository.save_inspection(
                    application,
                    adapter=adapter.name,
                    target_url=page.url,
                    fingerprint=form.fingerprint,
                    inspection_data={
                        "field_count": len(form.fields),
                        "required_field_count": sum(field.required for field in form.fields),
                        "submit_label": form.submit_label,
                        "captcha_detected": captcha_detected,
                        "blocked_mutation_requests": len(firewall.blocked_urls),
                    },
                    form_snapshot=form.snapshot(),
                    unknown_fields=list(resolved.unknown_required),
                )

                if application.mode is ApplicationMode.INSPECT:
                    return RunResult(
                        application.id,
                        ApplicationStatus.INSPECTED,
                        adapter.name,
                        form.fingerprint,
                        resolved.blockers,
                    )

                fill_report = adapter.fill(page, form, resolved)
                # Give any input/change-triggered autosave request a chance to reach
                # the route firewall, and conditional questions a chance to render.
                page.wait_for_timeout(250)
                rechecked_form = adapter.inspect(page)
                self.validator.validate(rechecked_form.action_url)
                form_changed_after_fill = rechecked_form.fingerprint != form.fingerprint
                form = rechecked_form
                fingerprint = form.fingerprint
                if form_changed_after_fill:
                    # Do not fill a newly revealed field in the same pass. Persist
                    # the new shape and require a fresh, explicit review instead.
                    resolved = policy.resolve(
                        form,
                        data.profile,
                        data.answers,
                        resume_path=str(data.resume_path) if data.resume_path else None,
                    )
                    self.repository.save_inspection(
                        application,
                        adapter=adapter.name,
                        target_url=page.url,
                        fingerprint=form.fingerprint,
                        inspection_data={
                            "field_count": len(form.fields),
                            "required_field_count": sum(field.required for field in form.fields),
                            "submit_label": form.submit_label,
                            "captcha_detected": captcha_detected,
                            "changed_after_fill": True,
                        },
                        form_snapshot=form.snapshot(),
                        unknown_fields=list(resolved.unknown_required),
                    )
                fill_report = replace(
                    fill_report,
                    blocked_mutation_requests=len(firewall.blocked_urls),
                )
                evidence_path = self.artifacts.screenshot(page, application.id, "filled")

                blockers = list(resolved.blockers)
                if form_changed_after_fill:
                    blockers.append("form changed after autofill; fresh review required")
                if captcha_detected:
                    blockers.append("CAPTCHA or bot challenge requires manual review")
                blockers.extend(
                    f"{key}: required answer is missing" for key in resolved.unknown_required
                )
                blockers.extend(fill_report.validation_errors)
                blockers.extend(f"{key}: field was not filled" for key in fill_report.skipped)
                blockers = list(dict.fromkeys(blockers))

                snapshot_updates = {
                    "answers_snapshot": {
                        "filled_keys": list(fill_report.filled),
                        "review_keys": list(resolved.review_keys),
                        "blocked_mutation_requests": fill_report.blocked_mutation_requests,
                    },
                    "resume_snapshot": {
                        "filename": data.resume_path.name if data.resume_path else None,
                    },
                    "evidence_path": evidence_path,
                    "unknown_fields": list(resolved.unknown_required),
                }

                if application.mode is ApplicationMode.AUTOFILL:
                    status = (
                        ApplicationStatus.NEEDS_REVIEW
                        if blockers
                        else ApplicationStatus.READY_TO_SUBMIT
                    )
                    self.repository.transition(
                        application,
                        status,
                        message="Autofill completed without submitting",
                        metadata={"blockers": blockers},
                        updates=snapshot_updates,
                    )
                    return RunResult(
                        application.id,
                        status,
                        adapter.name,
                        form.fingerprint,
                        tuple(blockers),
                    )

                if blockers:
                    self.repository.transition(
                        application,
                        ApplicationStatus.NEEDS_REVIEW,
                        message="Automatic submission blocked by form or answer policy",
                        metadata={"blockers": blockers},
                        updates=snapshot_updates,
                    )
                    return RunResult(
                        application.id,
                        ApplicationStatus.NEEDS_REVIEW,
                        adapter.name,
                        form.fingerprint,
                        tuple(blockers),
                    )

                previous_fingerprint = application.form_fingerprint or application.form_snapshot.get(
                    "form_fingerprint"
                )
                permit = SubmissionPermit(
                    application_id=application.id,
                    mode=application.mode,
                    target_url=form.action_url,
                    adapter=adapter.name,
                    current_fingerprint=form.fingerprint,
                    authorized_fingerprint=previous_fingerprint,
                    submission_authorized_at=application.submission_authorized_at,
                    policy_auto_submit_authorized=bool(
                        data.policy.get("auto_submit_authorized", False)
                    ),
                    adapter_allowlist=tuple(data.policy.get("ats_allowlist") or ()),
                    company_name=data.company_name,
                    company_allowlist=tuple(data.policy.get("company_allowlist") or ()),
                    blockers=(),
                    prior_submission_attempted=self.repository.has_submission_attempt(application),
                    daily_submission_count=self.repository.count_submissions_today(application.user_id),
                    max_daily_submissions=int(data.policy.get("max_daily_submissions") or 0),
                    test_mode=self.test_mode,
                )

                try:
                    self.submit_guard.validate(permit)
                except SafetyError as exc:
                    self.repository.transition(
                        application,
                        ApplicationStatus.READY_TO_SUBMIT,
                        message=str(exc),
                        updates=snapshot_updates,
                    )
                    return RunResult(
                        application.id,
                        ApplicationStatus.READY_TO_SUBMIT,
                        adapter.name,
                        form.fingerprint,
                        (str(exc),),
                    )

                firewall.remove(page)

                def before_click() -> None:
                    nonlocal click_committed
                    self.repository.mark_submitting(application, form.fingerprint)
                    click_committed = True

                self.submit_guard.submit(page, form, permit, before_click=before_click)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=5_000)
                except PlaywrightTimeoutError:
                    pass
                receipt = adapter.read_receipt(page)
                self.artifacts.screenshot(page, application.id, "submitted")
                if receipt is None:
                    self.repository.transition(
                        application,
                        ApplicationStatus.SUBMISSION_UNKNOWN,
                        message="Final submit was clicked but no unambiguous confirmation was found",
                        updates=snapshot_updates,
                    )
                    return RunResult(
                        application.id,
                        ApplicationStatus.SUBMISSION_UNKNOWN,
                        adapter.name,
                        form.fingerprint,
                        ("submission confirmation was not detected",),
                    )

                self.repository.mark_submitted(application, receipt)
                return RunResult(
                    application.id,
                    ApplicationStatus.SUBMITTED,
                    adapter.name,
                    form.fingerprint,
                    receipt=receipt,
                )
        except Exception as exc:
            if click_committed:
                message = f"{type(exc).__name__}: {exc}"
                self.repository.transition(
                    application,
                    ApplicationStatus.SUBMISSION_UNKNOWN,
                    message=message,
                )
                return RunResult(
                    application.id,
                    ApplicationStatus.SUBMISSION_UNKNOWN,
                    adapter_name,
                    fingerprint,
                    (message,),
                )
            return self._transition_failure(application, exc)

    def run_next(self, worker_id: str, lease_minutes: int = 30) -> RunResult | None:
        application = self.repository.claim_next(worker_id, lease_minutes)
        if application is None:
            return None
        data = self.repository.load_candidate_data(application)
        return self.run_claimed(application, data)
