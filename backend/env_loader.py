"""Load backend/.env regardless of the process working directory."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
DOTENV_PATH = BACKEND_DIR / ".env"
_loaded = False


def load_backend_dotenv() -> None:
    """Load environment variables from backend/.env once per process."""
    global _loaded
    if _loaded:
        return
    if DOTENV_PATH.is_file():
        # override=True ensures backend/.env wins over stale shell/session variables.
        load_dotenv(DOTENV_PATH, override=True)
    else:
        load_dotenv(override=True)
    _loaded = True
