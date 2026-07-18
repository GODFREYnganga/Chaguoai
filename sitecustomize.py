"""Local import path setup for tests and development scripts.

Adds the ``backend`` directory to ``sys.path`` so tests can import modules
such as ``method_selection`` without per-test path hacks.
"""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if BACKEND_DIR.exists() and str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
