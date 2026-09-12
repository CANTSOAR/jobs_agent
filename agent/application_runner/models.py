from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class ApplicationStatus(str, Enum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    INSPECTED = "inspected"
    NEEDS_REVIEW = "needs_review"
    READY_TO_SUBMIT = "ready_to_submit"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUBMISSION_UNKNOWN = "submission_unknown"
    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    SKIPPED = "skipped"
    FAILED = "failed"


class ApplicationMode(str, Enum):
    TRACK_ONLY = "track_only"
    INSPECT = "inspect"
    AUTOFILL = "autofill"
    AUTO_SUBMIT_IF_SAFE = "auto_submit_if_safe"


class FieldKind(str, Enum):
    TEXT = "text"
    TEXTAREA = "textarea"
    EMAIL = "email"
    TEL = "tel"
    URL = "url"
    DATE = "date"
    NUMBER = "number"
    SELECT = "select"
    COMBOBOX = "combobox"
    MULTI_SELECT = "multi_select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class FormField:
    key: str
    label: str
    name: str
    kind: FieldKind
    selector: str
    required: bool = False
    options: tuple[str, ...] = ()
    sensitive: bool = False

    def fingerprint_payload(self) -> dict[str, Any]:
        # Selectors are deliberately omitted: generated selectors may change between
        # page loads while the question itself remains identical.
        return {
            "key": self.key,
            "label": self.label.strip(),
            "name": self.name,
            "kind": self.kind.value,
            "required": self.required,
            "options": list(self.options),
            "sensitive": self.sensitive,
        }


@dataclass(frozen=True)
class ApplicationForm:
    adapter: str
    source_url: str
    action_url: str
    fields: tuple[FormField, ...]
    submit_selector: str | None
    submit_label: str | None
    fingerprint: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "source_url": self.source_url,
            "action_url": self.action_url,
            "fields": [item.fingerprint_payload() for item in self.fields],
            "submit_label": self.submit_label,
            "form_fingerprint": self.fingerprint,
        }


@dataclass(frozen=True)
class ApprovedAnswer:
    key: str
    value: Any
    approved_for_autofill: bool = False
    approved_for_submission: bool = False
    sensitive: bool = False
    question_pattern: str | None = None


@dataclass(frozen=True)
class ResolvedAnswers:
    values: Mapping[str, Any]
    blockers: tuple[str, ...] = ()
    unknown_required: tuple[str, ...] = ()
    review_keys: tuple[str, ...] = ()

    @property
    def safe_to_submit(self) -> bool:
        return not self.blockers and not self.unknown_required and not self.review_keys


@dataclass(frozen=True)
class FillReport:
    form_fingerprint: str
    filled: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    validation_errors: tuple[str, ...] = ()
    blocked_mutation_requests: int = 0

    @property
    def complete(self) -> bool:
        return not self.skipped and not self.validation_errors


@dataclass(frozen=True)
class SubmissionReceipt:
    confirmation_id: str | None
    confirmation_url: str
    message: str | None = None


@dataclass(frozen=True)
class SubmissionPermit:
    application_id: str
    mode: ApplicationMode
    target_url: str
    adapter: str
    current_fingerprint: str
    authorized_fingerprint: str | None
    submission_authorized_at: datetime | None
    policy_auto_submit_authorized: bool
    adapter_allowlist: tuple[str, ...]
    company_name: str | None
    company_allowlist: tuple[str, ...]
    blockers: tuple[str, ...] = ()
    prior_submission_attempted: bool = False
    daily_submission_count: int = 0
    max_daily_submissions: int = 0
    test_mode: bool = False


@dataclass(frozen=True)
class ApplicationRecord:
    id: str
    user_id: str
    job_id: str
    status: ApplicationStatus
    mode: ApplicationMode
    application_url: str
    adapter: str | None = None
    form_fingerprint: str | None = None
    claimed_by: str | None = None
    inspection_data: Mapping[str, Any] = field(default_factory=dict)
    form_snapshot: Mapping[str, Any] = field(default_factory=dict)
    resume_snapshot: Mapping[str, Any] = field(default_factory=dict)
    answers_snapshot: Mapping[str, Any] = field(default_factory=dict)
    submission_authorized_at: datetime | None = None
    attempt_count: int = 0


@dataclass(frozen=True)
class CandidateApplicationData:
    profile: Mapping[str, Any]
    answers: tuple[ApprovedAnswer, ...]
    resume_path: Path | None
    policy: Mapping[str, Any]
    company_name: str | None = None


@dataclass(frozen=True)
class RunResult:
    application_id: str
    status: ApplicationStatus
    adapter: str | None = None
    form_fingerprint: str | None = None
    blockers: tuple[str, ...] = ()
    receipt: SubmissionReceipt | None = None
