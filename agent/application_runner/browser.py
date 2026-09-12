from __future__ import annotations

from pathlib import Path
from types import TracebackType

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from .safety import MutationFirewall, TargetValidator


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ApplicationBrowser:
    """A dedicated browser lifecycle that is never shared with scraping."""

    def __init__(
        self,
        *,
        validator: TargetValidator,
        headless: bool = False,
        user_data_dir: Path | None = None,
        timeout_ms: int = 20_000,
    ) -> None:
        self.validator = validator
        self.headless = headless
        self.user_data_dir = user_data_dir
        self.timeout_ms = timeout_ms
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> ApplicationBrowser:
        self._playwright = sync_playwright().start()
        chromium = self._playwright.chromium
        context_options = {
            "accept_downloads": False,
            "locale": "en-US",
            "service_workers": "block",
            "user_agent": DEFAULT_USER_AGENT,
        }
        if self.user_data_dir is not None:
            self.user_data_dir.mkdir(parents=True, exist_ok=True)
            self._context = chromium.launch_persistent_context(
                str(self.user_data_dir),
                headless=self.headless,
                **context_options,
            )
        else:
            self._browser = chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(**context_options)
        self._context.set_default_timeout(self.timeout_ms)
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def open(
        self,
        url: str,
        *,
        mutation_firewall: MutationFirewall | None = None,
    ) -> Page:
        if self._context is None:
            raise RuntimeError("ApplicationBrowser must be used as a context manager")
        self.validator.validate(url)
        page = self._context.new_page()
        self.validator.install_navigation_guard(page)
        if mutation_firewall is not None:
            mutation_firewall.install(page)
        page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        self.validator.validate(page.url)
        return page
