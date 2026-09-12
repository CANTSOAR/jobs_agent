from __future__ import annotations

from urllib.parse import urlsplit

from playwright.sync_api import Page

from .generic import GenericAdapter


class MockAdapter(GenericAdapter):
    """Adapter used only by the loopback end-to-end test server."""

    name = "mock"

    def supports(self, url: str, page: Page) -> int:
        host = (urlsplit(url).hostname or "").casefold()
        loopback = host == "localhost" or host.startswith("127.") or host == "::1"
        return 100 if loopback and page.locator("[data-mock-ats]").count() == 1 else 0
