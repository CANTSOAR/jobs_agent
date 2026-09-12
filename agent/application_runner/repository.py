from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .models import (
    ApplicationMode,
    ApplicationRecord,
    ApplicationStatus,
    ApprovedAnswer,
    CandidateApplicationData,
    SubmissionReceipt,
)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _application_from_row(row: Mapping[str, Any], fallback_url: str | None = None) -> ApplicationRecord:
    url = row.get("target_url") or row.get("application_url") or fallback_url
    if not url:
        raise RuntimeError(f"application {row.get('id')} has no target URL")
    return ApplicationRecord(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        job_id=str(row["job_id"]),
        status=ApplicationStatus(str(row["status"])),
        mode=ApplicationMode(str(row["mode"])),
        application_url=str(url),
        adapter=row.get("adapter"),
        form_fingerprint=row.get("form_fingerprint"),
        claimed_by=row.get("claimed_by"),
        inspection_data=row.get("inspection_data") or {},
        form_snapshot=row.get("form_snapshot") or {},
        resume_snapshot=row.get("resume_snapshot") or {},
        answers_snapshot=row.get("answers_snapshot") or {},
        submission_authorized_at=_parse_datetime(row.get("submission_authorized_at")),
        attempt_count=int(row.get("attempt_count") or 0),
    )


class ApplicationRepository(Protocol):
    def claim_next(self, worker_id: str, lease_minutes: int = 30) -> ApplicationRecord | None: ...

    def load_candidate_data(self, application: ApplicationRecord) -> CandidateApplicationData: ...

    def save_inspection(
        self,
        application: ApplicationRecord,
        *,
        adapter: str,
        target_url: str,
        fingerprint: str,
        inspection_data: Mapping[str, Any],
        form_snapshot: Mapping[str, Any],
        unknown_fields: list[str],
    ) -> None: ...

    def transition(
        self,
        application: ApplicationRecord,
        status: ApplicationStatus,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        updates: Mapping[str, Any] | None = None,
    ) -> None: ...

    def has_submission_attempt(self, application: ApplicationRecord) -> bool: ...

    def count_submissions_today(self, user_id: str) -> int: ...

    def mark_submitting(self, application: ApplicationRecord, fingerprint: str) -> None: ...

    def mark_submitted(self, application: ApplicationRecord, receipt: SubmissionReceipt) -> None: ...


class SupabaseApplicationRepository:
    """Small Supabase boundary used by the local/private application worker."""

    def __init__(self, client, *, resume_path: Path | None = None) -> None:
        self.client = client
        self.resume_path = resume_path

    @staticmethod
    def _first(data: Any) -> Mapping[str, Any] | None:
        if isinstance(data, list):
            return data[0] if data else None
        return data or None

    def claim_next(self, worker_id: str, lease_minutes: int = 30) -> ApplicationRecord | None:
        response = self.client.rpc(
            "claim_next_application",
            {"p_worker_id": worker_id, "p_lease_minutes": lease_minutes},
        ).execute()
        row = self._first(response.data)
        return _application_from_row(row) if row else None

    def get_by_id(self, application_id: str) -> ApplicationRecord:
        response = (
            self.client.table("applications")
            .select("*")
            .eq("id", application_id)
            .limit(1)
            .execute()
        )
        row = self._first(response.data)
        if not row:
            raise RuntimeError(f"application not found: {application_id}")
        if not (row.get("target_url") or row.get("application_url")):
            job = (
                self.client.table("jobs")
                .select("url")
                .eq("id", row["job_id"])
                .limit(1)
                .execute()
            )
            fallback = (self._first(job.data) or {}).get("url")
        else:
            fallback = None
        return _application_from_row(row, fallback)

    def load_candidate_data(self, application: ApplicationRecord) -> CandidateApplicationData:
        profile_response = (
            self.client.table("profiles")
            .select("application_profile")
            .eq("id", application.user_id)
            .limit(1)
            .execute()
        )
        profile_row = self._first(profile_response.data) or {}

        answers_response = (
            self.client.table("application_answers")
            .select(
                "key,question_pattern,answer_value,approved_for_autofill,"
                "approved_for_submission,is_sensitive"
            )
            .eq("user_id", application.user_id)
            .execute()
        )
        answers = tuple(
            ApprovedAnswer(
                key=row["key"],
                value=row.get("answer_value"),
                approved_for_autofill=bool(row.get("approved_for_autofill")),
                approved_for_submission=bool(row.get("approved_for_submission")),
                sensitive=bool(row.get("is_sensitive")),
                question_pattern=row.get("question_pattern"),
            )
            for row in (answers_response.data or [])
        )

        policy_response = (
            self.client.table("application_policies")
            .select("*")
            .eq("user_id", application.user_id)
            .limit(1)
            .execute()
        )
        policy = self._first(policy_response.data) or {}

        job_response = (
            self.client.table("jobs")
            .select("companies(name)")
            .eq("id", application.job_id)
            .limit(1)
            .execute()
        )
        job = self._first(job_response.data) or {}
        company = job.get("companies") or {}
        if isinstance(company, list):
            company = company[0] if company else {}

        return CandidateApplicationData(
            profile=profile_row.get("application_profile") or {},
            answers=answers,
            resume_path=self.resume_path,
            policy=policy,
            company_name=company.get("name"),
        )

    def save_inspection(
        self,
        application: ApplicationRecord,
        *,
        adapter: str,
        target_url: str,
        fingerprint: str,
        inspection_data: Mapping[str, Any],
        form_snapshot: Mapping[str, Any],
        unknown_fields: list[str],
    ) -> None:
        (
            self.client.table("applications")
            .update(
                {
                    "adapter": adapter,
                    "target_url": target_url,
                    "form_fingerprint": fingerprint,
                    "inspection_data": dict(inspection_data),
                    "form_snapshot": dict(form_snapshot),
                    "unknown_fields": unknown_fields,
                    "status": ApplicationStatus.INSPECTED.value,
                    "last_error": None,
                }
            )
            .eq("id", application.id)
            .execute()
        )

    def _event(
        self,
        application: ApplicationRecord,
        event_type: str,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        to_status: ApplicationStatus | None = None,
    ) -> None:
        self.client.table("application_events").insert(
            {
                "application_id": application.id,
                "event_type": event_type,
                "actor": application.claimed_by or "application_runner",
                "message": message,
                "to_status": to_status.value if to_status else None,
                "metadata": dict(metadata or {}),
            }
        ).execute()

    def transition(
        self,
        application: ApplicationRecord,
        status: ApplicationStatus,
        *,
        message: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        updates: Mapping[str, Any] | None = None,
    ) -> None:
        payload = {"status": status.value, **dict(updates or {})}
        if status is ApplicationStatus.FAILED and message:
            payload["last_error"] = message[:2000]
        self.client.table("applications").update(payload).eq("id", application.id).execute()
        if message or metadata:
            self._event(
                application,
                "runner_result",
                message=message,
                metadata=metadata,
                to_status=status,
            )

    def has_submission_attempt(self, application: ApplicationRecord) -> bool:
        if application.status in {
            ApplicationStatus.SUBMITTING,
            ApplicationStatus.SUBMITTED,
            ApplicationStatus.SUBMISSION_UNKNOWN,
        }:
            return True
        response = (
            self.client.table("application_events")
            .select("id")
            .eq("application_id", application.id)
            .eq("event_type", "submit_click_committed")
            .limit(1)
            .execute()
        )
        return bool(response.data)

    def count_submissions_today(self, user_id: str) -> int:
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        # Count committed final-click attempts, including ambiguous outcomes. An
        # unknown confirmation still consumes the user's daily safety budget.
        response = (
            self.client.table("application_events")
            .select("id, applications!inner(user_id)")
            .eq("event_type", "submit_click_committed")
            .eq("applications.user_id", user_id)
            .gte("created_at", start.isoformat())
            .execute()
        )
        return len(response.data or [])

    def mark_submitting(self, application: ApplicationRecord, fingerprint: str) -> None:
        # Move out of a claimable state before emitting the commit marker.  A crash at
        # either point stops retries, which is safer than risking a duplicate submit.
        response = (
            self.client.table("applications")
            .update({"status": ApplicationStatus.SUBMITTING.value})
            .eq("id", application.id)
            .eq("status", ApplicationStatus.INSPECTED.value)
            .select("id")
            .execute()
        )
        if not response.data:
            raise RuntimeError("application was not in the expected pre-submit state")
        self._event(
            application,
            "submit_click_committed",
            message="Final submit control is about to be clicked exactly once",
            metadata={"form_fingerprint": fingerprint},
            to_status=ApplicationStatus.SUBMITTING,
        )

    def mark_submitted(self, application: ApplicationRecord, receipt: SubmissionReceipt) -> None:
        self.transition(
            application,
            ApplicationStatus.SUBMITTED,
            message="Application submission confirmed",
            metadata={"confirmation_id": receipt.confirmation_id},
            updates={
                "confirmation_id": receipt.confirmation_id,
                "confirmation_url": receipt.confirmation_url,
                "submitted_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
            },
        )
