from __future__ import annotations

from urllib.parse import urlsplit

from playwright.sync_api import Page

from .generic import GenericAdapter


class GreenhouseAdapter(GenericAdapter):
    """Greenhouse detector with conservative generic HTML-form filling.

    Keeping Greenhouse behind its own adapter name lets policies allowlist it today
    and lets us replace individual field handlers as its markup evolves.
    """

    name = "greenhouse"

    def supports(self, url: str, page: Page) -> int:
        host = (urlsplit(url).hostname or "").casefold()
        if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
            return 90
        if host.endswith(".greenhouse.io"):
            return 80
        if page.locator('form[action*="greenhouse"], #grnhse_app').count():
            return 70
        return 0
