import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TARGET_JID = "111111111111@g.us"
TARGET_NAME = "Wayne Desi Gals"
OTHER_JID = "999999999999@g.us"

# Real dump constants — active Wayne Desi Gals group from messages_dump.sql
REAL_TARGET_JID = "19735135649-1526821682@g.us"
REAL_TARGET_NAME = "Wayne Desi Gals"


# ---------------------------------------------------------------------------
# In-memory SQLite seeded from messages.sql (synthetic fixture data)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn():
    """
    In-memory SQLite connection seeded with all fixture messages.
    Passed to fetcher and any test that needs raw DB access.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    sql = (FIXTURES_DIR / "messages.sql").read_text()
    conn.executescript(sql)
    conn.commit()

    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# In-memory SQLite seeded from messages_dump.sql (real exported data)
# ---------------------------------------------------------------------------

@pytest.fixture
def db_conn_dump():
    """
    In-memory SQLite connection seeded from the real WhatsApp DB export.
    Used by tests that validate behaviour against actual production data.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    sql = (FIXTURES_DIR / "messages_dump.sql").read_bytes().decode("utf-8", errors="replace")
    conn.executescript(sql)
    conn.commit()

    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Fixture message objects (WhatsAppMessage dicts as loaded from messages.json)
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_messages():
    """Raw list of dicts matching WhatsAppMessage schema, from messages.json."""
    return json.loads((FIXTURES_DIR / "messages.json").read_text())


@pytest.fixture
def wayne_desi_gals_messages(fixture_messages):
    """Only the Wayne Desi Gals messages (msg_001 through msg_010)."""
    return [m for m in fixture_messages if m["group"] == TARGET_NAME]


# ---------------------------------------------------------------------------
# Config dict (mirrors config.yaml structure)
# ---------------------------------------------------------------------------

@pytest.fixture
def test_config(tmp_path):
    """
    Minimal config dict for tests. Uses tmp_path for CSV output so each
    test gets a clean directory.
    """
    return {
        "database": {"path": ":memory:"},
        "group": {
            "jid": TARGET_JID,
            "name": TARGET_NAME,
        },
        "pipeline": {"polling_interval_seconds": 1},
        "output": {
            "directory": str(tmp_path),
            "questions_file": "questions.csv",
            "answers_file": "answers.csv",
        },
        "logging": {"level": "DEBUG", "file": str(tmp_path / "test.log")},
        "anthropic": {
            "api_key_env": "ANTHROPIC_API_KEY",
            "model": "claude-sonnet-4-6",
        },
    }


# ---------------------------------------------------------------------------
# Mock Anthropic client
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_anthropic(mocker):
    """
    Patches anthropic.Anthropic so no real API calls are made.
    Returns the mock client instance — tests set mock_anthropic.messages.create.return_value
    to control what Claude "returns".
    """
    mock_client = MagicMock()
    mocker.patch("anthropic.Anthropic", return_value=mock_client)
    return mock_client


def make_claude_response(content: str):
    """
    Helper: wrap a JSON string in the shape anthropic SDK returns.
    Usage in tests:
        mock_anthropic.messages.create.return_value = make_claude_response(json.dumps({...}))
    """
    mock_response = MagicMock()
    mock_content_block = MagicMock()
    mock_content_block.text = content
    mock_response.content = [mock_content_block]
    return mock_response


# ---------------------------------------------------------------------------
# Stubbed Go bridge (localhost:8080)
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_go_bridge(responses):
    """
    Registers a fake Go bridge download endpoint using the `responses` library.
    Tests that exercise media_handler will have this fixture auto-applied.

    Default behaviour: returns a successful download pointing to a temp file.
    Override in individual tests by adding more responses.register() calls.
    """
    responses.add(
        responses.POST,
        "http://localhost:8080/api/download",
        json={"success": True, "message": "downloaded", "file_path": "/tmp/test_media_file"},
        status=200,
    )
    return responses
