"""Offline unit tests.

These tests import backend modules from the historical ``mhc-backend`` folder,
which is not a Python package name because it contains a hyphen.
"""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2] / "mhc-backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
