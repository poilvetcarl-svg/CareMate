"""Shared pytest fixtures for the CareMate test suite."""
import os
import sys

# Make the project root importable regardless of where pytest is invoked from
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use an in-memory database and disable external services during tests.
# Set keys to empty strings (not pop) — app.py's load_dotenv() does not override
# existing env vars, so this reliably forces the AI fallback paths.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ["OPENAI_API_KEY"] = ""
os.environ["TAVUS_API_KEY"] = ""

import pytest  # noqa: E402

from app import app as flask_app  # noqa: E402


@pytest.fixture()
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    yield flask_app


@pytest.fixture()
def client(app):
    return app.test_client()
