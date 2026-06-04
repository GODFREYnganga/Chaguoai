"""Opt-in integration tests that may require live external credentials."""

from pathlib import Path
import sys


BACKEND_DIR = Path(__file__).resolve().parents[2] / "mhc-backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
