"""Compatibility launcher for the main backend dashboard routes."""

import os
from pathlib import Path

from backend.config import Settings
from backend.presentation.api.app import create_app


def create_bridge(settings=None, session_factory=None):
    return create_app(settings or Settings(), session_factory)


def application():
    settings = Settings()
    if not os.getenv("COCONERD_DATABASE_URL"):
        raise RuntimeError(
            "Set COCONERD_DATABASE_URL to your existing migrated database; "
            "the bridge never creates or migrates user data."
        )
    database = settings.database_url.removeprefix("sqlite+aiosqlite:///").split("?", 1)[0]
    if not Path(database).is_file():
        raise RuntimeError(
            "The selected database does not exist. "
            "Use the database already configured for the backend worker."
        )
    return create_bridge(settings)
