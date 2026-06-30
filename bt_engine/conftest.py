"""Add research-baseline source tree to sys.path read-only for oracle imports."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_SRC = REPO_ROOT / "research-baseline" / "code" / "src"

if BASELINE_SRC.is_dir():
    sys.path.insert(0, str(BASELINE_SRC))
