"""Compatibility command; use ``python app/core/zones/define_zone.py``."""
from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[2]
script_dir = Path(__file__).resolve().parent
sys.path[:] = [entry for entry in sys.path if Path(entry or ".").resolve() != script_dir]
sys.path.insert(0, str(project_root))

from app.core.zones.define_zone import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
