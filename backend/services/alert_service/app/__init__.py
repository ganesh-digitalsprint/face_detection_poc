"""Independent shared Alert Service."""
import os
import sys
from pathlib import Path

_shared = Path(os.environ.get('FEDBANK_SHARED_PATH') or Path(__file__).resolve().parents[3] / 'shared')
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
