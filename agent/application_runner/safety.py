from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from playwright.sync_api import Page, Request, Route

from .models import ApplicationForm, SubmissionPermit


class SafetyError(RuntimeError):
    """Raised when a browser action fails closed."""


def _host_matches(value: str, allowed: str) -> bool:
    value = value.casefold().strip().rstrip(".")
    allowed = allowed.casefold().strip().rstrip(".")
    if allowed.startswith("*."):
        suffix = allowed[2:]
        return value.endswith(f".{suffix}") and value != suffix
    return value == allowed


class TargetValidator:
    """Reject dangerous application URLs before and during navigation."""

    def __init__(
        self,
        *,
        test_mode: bool = False,
        resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
    ) -> None:
        self.test_mode = test_mode
        self._resolver = resolver

    @staticmethod
    def _is_loopback_name(hostname: str) -> bool:
        return hostname.casefold().rstrip(".") == "localhost"

    def validate(self, url: str) -> str:
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise SafetyError(f"invalid target URL: {exc}") from exc

        hostname = (parsed.hostname or "").casefold().rstrip(".")
        if not hostname or parsed.username or parsed.password:
            raise SafetyError("target URL must have a hostname and no embedded credentials")

        if self.test_mode:
            if parsed.scheme != "http":
                raise SafetyError("test targets must use http")
            if not self._is_loopback_name(hostname):
                try:
                    if not ipaddress.ip_address(hostname).is_loopback:
                        raise SafetyError("test targets must resolve to the loopback interface")
                except ValueError as exc:
                    raise SafetyError("test targets must use localhost or a loopback IP") from exc
            return url

        if parsed.scheme != "https":
            raise SafetyError("live application targets must use https")
        if port not in (None, 443):
            raise SafetyError("live application targets may only use the standard HTTPS port")
        if self._is_loopback_name(hostname):
            raise SafetyError("loopback targets are forbidden in live mode")

        try:
            literal = ipaddress.ip_address(hostname)
            addresses = [literal]
        except ValueError:
            try:
                info = self._resolver(hostname, 443, type=socket.SOCK_STREAM)
            except OSError as exc:
                raise SafetyError(f"could not resolve target hostname: {hostname}") from exc
            addresses = []
            for item in info:
                try:
                    addresses.append(ipaddress.ip_address(item[4][0]))
                except (ValueError, IndexError):
                    continue

        if not addresses or any(not address.is_global for address in addresses):
            raise SafetyError("private, loopback, link-local, and reserved targets are forbidden")
        return url

    def install_navigation_guard(self, page: Page) -> Callable[[Route, Request], None]:
        def guard(route: Route, request: Request) -> None:
            scheme = urlsplit(request.url).scheme.casefold()
            if scheme in {"http", "https"}:
                try:
                    self.validate(request.url)
                except SafetyError:
                    route.abort("blockedbyclient")
                    return
            elif request.is_navigation_request() and request.frame == page.main_frame:
                route.abort("blockedbyclient")
                return
            route.continue_()

        page.route("**/*", guard)
        return guard


class MutationFirewall:
    """Blocks all network mutations while a form is inspected or autofilled."""

    SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

    def __init__(self) -> None:
        self.blocked_urls: list[str] = []
        self._handler: Callable[[Route, Request], None] | None = None

    def install(self, page: Page) -> None:
        if self._handler is not None:
            raise SafetyError("mutation firewall is already installed")

        def block_mutations(route: Route, request: Request) -> None:
            if request.method.upper() not in self.SAFE_METHODS:
                self.blocked_urls.append(request.url)
                route.abort("blockedbyclient")
                return
            # Let the navigation guard (registered earlier) validate safe-method
            # requests and redirects as well.
            route.fallback()

        self._handler = block_mutations
        page.route("**/*", block_mutations)

    def remove(self, page: Page) -> None:
        if self._handler is not None:
            page.unroute("**/*", self._handler)
            self._handler = None


class SubmitGuard:
    """The only component permitted to click a final submit control."""

    LIVE_ENABLE_VALUE = "I_UNDERSTAND_THIS_SUBMITS_REAL_APPLICATIONS"
    MAX_DAILY_SUBMISSIONS = 20
    LIVE_ADAPTER_HOSTS = {
        "greenhouse": ("greenhouse.io", "*.greenhouse.io"),
    }

    def __init__(
        self,
        *,
        validator: TargetValidator,
        live_enabled: str | None = None,
        test_enabled: bool | None = None,
        now: Callable[[], datetime] | None = None,
        authorization_ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        self.validator = validator
        self.live_enabled = (
            live_enabled
            if live_enabled is not None
            else os.environ.get("APPLICATION_LIVE_SUBMIT_ENABLED", "")
        )
        self.test_enabled = (
            test_enabled
            if test_enabled is not None
            else os.environ.get("JOBS_AGENT_TEST_MODE") == "1"
        )
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.authorization_ttl = authorization_ttl

    @staticmethod
    def _in_allowlist(value: str, allowed: Iterable[str]) -> bool:
        return any(_host_matches(value, candidate) for candidate in allowed)

    def validate(self, permit: SubmissionPermit) -> None:
        if permit.mode.value != "auto_submit_if_safe":
            raise SafetyError("application mode does not permit automatic submission")
        if permit.blockers:
            raise SafetyError(f"submission has policy blockers: {', '.join(permit.blockers)}")
        if permit.prior_submission_attempted:
            raise SafetyError("a final submission was already attempted")
        if permit.max_daily_submissions <= 0:
            raise SafetyError("daily submission limit must be explicitly configured")
        if permit.max_daily_submissions > self.MAX_DAILY_SUBMISSIONS:
            raise SafetyError(
                f"daily submission limit cannot exceed {self.MAX_DAILY_SUBMISSIONS}"
            )
        if permit.daily_submission_count >= permit.max_daily_submissions:
            raise SafetyError("daily submission limit reached")

        self.validator.validate(permit.target_url)
        host = (urlsplit(permit.target_url).hostname or "").casefold()

        if permit.adapter.casefold() not in {item.casefold() for item in permit.adapter_allowlist}:
            raise SafetyError("adapter is not explicitly allowlisted")

        adapter_name = permit.adapter.casefold()
        if permit.test_mode:
            if adapter_name != "mock":
                raise SafetyError("test submission requires the mock adapter")
        else:
            trusted_hosts = self.LIVE_ADAPTER_HOSTS.get(adapter_name)
            if not trusted_hosts:
                raise SafetyError("adapter is not supported for guarded live submission")
            if not self._in_allowlist(host, trusted_hosts):
                raise SafetyError("submission target is not a trusted host for this adapter")

        if not permit.company_allowlist:
            raise SafetyError("company allowlist is empty")
        if not permit.company_name or permit.company_name.casefold() not in {
            item.casefold() for item in permit.company_allowlist
        }:
            raise SafetyError("company is not explicitly allowlisted")

        app_authorized = False
        if permit.submission_authorized_at is not None:
            authorized_at = permit.submission_authorized_at
            if authorized_at.tzinfo is None:
                authorized_at = authorized_at.replace(tzinfo=timezone.utc)
            age = self._now() - authorized_at
            app_authorized = timedelta(0) <= age <= self.authorization_ttl
            if not app_authorized:
                raise SafetyError("application-specific submission authorization expired")
            if not permit.authorized_fingerprint:
                raise SafetyError("authorized form fingerprint is missing")
            if permit.current_fingerprint != permit.authorized_fingerprint:
                raise SafetyError("the form changed after submission was authorized")

        if not app_authorized and not permit.policy_auto_submit_authorized:
            raise SafetyError("submission was not explicitly authorized")

        if permit.test_mode:
            if not self.test_enabled or not self.validator.test_mode:
                raise SafetyError("test submission requires both test safety gates")
        elif self.live_enabled != self.LIVE_ENABLE_VALUE:
            raise SafetyError("live submission is disabled in this worker environment")

    def submit(
        self,
        page: Page,
        form: ApplicationForm,
        permit: SubmissionPermit,
        *,
        before_click: Callable[[], None],
        timeout_ms: int = 10_000,
    ) -> None:
        self.validate(permit)
        if not form.submit_selector:
            raise SafetyError("adapter did not identify a submit control")
        locator = page.locator(form.submit_selector)
        if locator.count() != 1:
            raise SafetyError("submit control is missing or ambiguous")
        if not locator.is_visible() or not locator.is_enabled():
            raise SafetyError("submit control is not visible and enabled")

        # The durable event/status write must succeed before the one irreversible action.
        before_click()
        locator.click(timeout=timeout_ms)
