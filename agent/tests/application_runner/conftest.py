from __future__ import annotations

import sys
from pathlib import Path


# Tests are normally run from agent/, but this also makes `pytest agent/tests/...`
# work from the repository root without installing the package.
AGENT_ROOT = Path(__file__).resolve().parents[2]
if str(AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENT_ROOT))
