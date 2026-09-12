from __future__ import annotations

from abc import ABC, abstractmethod

from playwright.sync_api import Page

from ..models import ApplicationForm, FillReport, ResolvedAnswers, SubmissionReceipt


class ApplicationAdapter(ABC):
    name: str

    @abstractmethod
    def supports(self, url: str, page: Page) -> int:
        """Return a confidence score; zero means unsupported."""

    @abstractmethod
    def inspect(self, page: Page) -> ApplicationForm:
        """Inspect without entering data or issuing network mutations."""

    @abstractmethod
    def fill(self, page: Page, form: ApplicationForm, answers: ResolvedAnswers) -> FillReport:
        """Fill fields, but never click a submit/next button."""

    @abstractmethod
    def read_receipt(self, page: Page) -> SubmissionReceipt | None:
        """Return a receipt only when the page clearly confirms submission."""
