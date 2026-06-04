"""CLI entrypoint for the ChaguoAI backend."""

from __future__ import annotations

import os

from application import app

APP_ENV = os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1" and APP_ENV.lower() not in {"production", "prod"}
    app.run(host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"), port=port, debug=debug)
