from __future__ import annotations

from collections.abc import Iterable

from playwright.sync_api import Page

from .base import ApplicationAdapter
from .generic import GenericAdapter
from .greenhouse import GreenhouseAdapter
from .mock import MockAdapter


class AdapterRegistry:
    def __init__(self, adapters: Iterable[ApplicationAdapter] | None = None) -> None:
        self.adapters = tuple(adapters or (MockAdapter(), GreenhouseAdapter(), GenericAdapter()))

    def select(self, url: str, page: Page) -> ApplicationAdapter:
        ranked = sorted(
            ((adapter.supports(url, page), adapter) for adapter in self.adapters),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] <= 0:
            raise RuntimeError("no application adapter supports this page")
        return ranked[0][1]
