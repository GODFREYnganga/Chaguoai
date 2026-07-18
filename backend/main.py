"""CLI entrypoint for the ChaguoAI backend."""

from __future__ import annotations

import os

from application import app

APP_ENV = os.environ.get("APP_ENV") or os.environ.get("FLASK_ENV", "development")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    is_prod = APP_ENV.lower() in {"production", "prod"}

    # Development defaults: listen on all interfaces and auto-reload on code changes.
    # Override with FLASK_RUN_HOST / FLASK_DEBUG in .env when needed.
    host = os.environ.get("FLASK_RUN_HOST")
    if not host:
        host = "127.0.0.1" if is_prod else "0.0.0.0"

    debug_env = os.environ.get("FLASK_DEBUG")
    if debug_env is None:
        debug = not is_prod
    else:
        debug = debug_env == "1" and not is_prod

    app.run(host=host, port=port, debug=debug)
