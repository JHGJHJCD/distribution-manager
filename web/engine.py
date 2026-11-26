# -*- coding: utf-8 -*-
"""The one doorway to the rules engine.

`selection.py`, `scoring.py` and `holidays.py` live in the repository root and are shared
with the desktop program — pure modules (no database, no Qt). They are imported here
unchanged; every "who receives" decision of the website goes through them.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import holidays     # noqa: E402
import scoring      # noqa: E402
import selection    # noqa: E402

__all__ = ["selection", "scoring", "holidays"]
