"""Local import path setup for tests and development scripts.

The backend lives in ``mhc-backend`` for historical compatibility with the
deployment layout. Because hyphens are not valid Python package names, adding
that directory to ``sys.path`` lets tests import modules such as
``method_selection`` without requiring ad hoc path hacks in every test file.
"""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parent / "mhc-backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
