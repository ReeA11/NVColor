"""One-shot: wipe stacked gamma ramps back to neutral 0.5/0.5/1.0."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from nvcolor.gamma_control import hard_reset

if __name__ == "__main__":
    applied = hard_reset(all_displays=True)
    print("Hard reset applied to:", applied)
