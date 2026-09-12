from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import Page


class PrivateArtifactStore:
    """Optional local evidence storage; files are private and never placed in Git."""

    def __init__(self, root: Path | None) -> None:
        self.root = root

    def screenshot(self, page: Page, application_id: str, stage: str) -> str | None:
        if self.root is None:
            return None
        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", application_id)
        safe_stage = re.sub(r"[^a-zA-Z0-9_-]", "_", stage)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        path = self.root / f"{safe_id}-{safe_stage}.png"
        page.screenshot(path=str(path), full_page=True)
        os.chmod(path, 0o600)
        # Supabase receives only an opaque local reference, never the operator's
        # username or absolute filesystem layout.
        return f"local:{path.name}"
