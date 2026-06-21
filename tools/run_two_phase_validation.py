"""转发层：实际实现已迁移至 `tools.reports.run_two_phase_validation`。"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path

if __package__ in {None, ""}:
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))

from tools.reports.run_two_phase_validation import *  # noqa: F401,F403
from tools.reports import run_two_phase_validation as _impl

_sys.modules[__name__] = _impl

if __name__ == "__main__":
    raise SystemExit(_impl.main())
