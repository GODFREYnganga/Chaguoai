"""Offline unit tests.

These tests import backend modules from the ``backend`` application folder.
"""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
