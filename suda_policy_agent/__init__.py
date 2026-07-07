"""Local knowledge-base assistant for university policy documents."""

from __future__ import annotations

import sys
from pathlib import Path

_VENDOR = Path(__file__).resolve().parents[1] / "vendor"
if _VENDOR.exists():
    sys.path.insert(0, str(_VENDOR))
