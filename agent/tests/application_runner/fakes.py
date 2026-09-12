from __future__ import annotations

from collections.abc import Mapping

from application_runner.models import (
    ApplicationRecord,
    ApplicationStatus,
    CandidateApplicationData,
    SubmissionReceipt,
)


class InMemoryRepository:
    def __init__(self, data: CandidateApplicationData) -> None:
        self.data = data
        self.status: ApplicationStatus | None = None
        self.inspection: dict = {}
        self.updates: dict = {}
        self.events: list[tuple[str, str | None]] = []
        self.submit_attempts = 0
        self.receipt: SubmissionReceipt | None = None

    def claim_next(self, worker_id: str, lease_minutes: int = 30):
        raise AssertionError("not used by these tests")

    def load_candidate_data(self, application: ApplicationRecord) -> CandidateApplicationData:
        return self.data

    def save_inspection(
        self,
        application: ApplicationRecord,
        *,
        adapter: str,
        target_url: str,
        fingerprint: str,
        inspection_data: Mapping,
        form_snapshot: Mapping,
        unknown_fields: list[str],
    ) -> None:
        self.status = ApplicationStatus.INSPECTED
        self.inspection = {
            "adapter": adapter,
            "target_url": target_url,
            "fingerprint": fingerprint,
            "inspection_data": dict(inspection_data),
            "form_snapshot": dict(form_snapshot),
            "unknown_fields": list(unknown_fields),
        }

    def transition(
        self,
        application: ApplicationRecord,
        status: ApplicationStatus,
        *,
        message: str | None = None,
        metadata: Mapping | None = None,
        updates: Mapping | None = None,
    ) -> None:
        self.status = status
        self.updates.update(dict(updates or {}))
        self.events.append((status.value, message))

    def has_submission_attempt(self, application: ApplicationRecord) -> bool:
        return self.submit_attempts > 0

    def count_submissions_today(self, user_id: str) -> int:
        return 0

    def mark_submitting(self, application: ApplicationRecord, fingerprint: str) -> None:
        if self.submit_attempts:
            raise RuntimeError("duplicate submit attempt")
        self.submit_attempts += 1
        self.status = ApplicationStatus.SUBMITTING
        self.events.append(("submit_click_committed", fingerprint))

    def mark_submitted(self, application: ApplicationRecord, receipt: SubmissionReceipt) -> None:
        self.status = ApplicationStatus.SUBMITTED
        self.receipt = receipt
        self.events.append((ApplicationStatus.SUBMITTED.value, receipt.confirmation_id))
