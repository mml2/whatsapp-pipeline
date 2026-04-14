# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
.venv/bin/pytest

# Run a single test file
.venv/bin/pytest tests/test_storage.py -v

# Run a single test
.venv/bin/pytest tests/test_storage.py::TestAnswerRow::test_phone_number_written -v

# Run with coverage
.venv/bin/pytest --cov=pipeline --cov-report=term-missing

# Run the pipeline
OPENAI_API_KEY=<key> .venv/bin/python main.py

# Run with a custom config
OPENAI_API_KEY=<key> .venv/bin/python main.py --config config.yaml

# Install dependencies
.venv/bin/pip install -r requirements.txt
```

## Architecture

The pipeline reads WhatsApp messages from a SQLite database written by a Go bridge (`mcp/whatsapp-bridge`), classifies them with an LLM, extracts contact information, and writes structured output to CSV files.

**Data flow:**
```
Go bridge (WhatsApp) → SQLite DB → Fetcher → MediaHandler → ContextWindow → Analyzer → Storage → CSV
```

**Pipeline components (`pipeline/`):**
- `fetcher.py` — polls SQLite with a watermark timestamp; JOINs `messages` + `chats` tables; validates group JID at startup
- `media_handler.py` — downloads media via Go bridge HTTP API at `localhost:8080/api/download`; raises `MediaNotAvailable` for historical messages (metadata not stored), `MediaDownloadError` for unexpected failures
- `context_window.py` — rolling 120-minute deque buffer; `get_recent()` is called **before** `add()` for each message
- `analyzer.py` — sends message + context to LLM; validates JSON response against Pydantic schema; handles vcard enrichment (parses `.vcf` file, injects as text) and image vision (base64 multimodal call)
- `storage.py` — routes QUESTION → `questions.csv`, ANSWER → `answers.csv` (only if `is_actionable=True`), skips CHAT/ANNOUNCEMENT
- `models.py` — all Pydantic v2 models; `quoted_message_id` is always `None` (Go bridge doesn't store it)

**LLM integration:**
- `SYSTEM_PROMPT.md` is loaded once at startup and passed as the system message
- Supports both OpenAI and Anthropic via `provider` in config — configured in `config.yaml`
- Vision model required (`gpt-4o` or `claude-sonnet-4-6`) — `gpt-4o-mini` does not support image analysis
- Responses are validated against `AnalysisResult` Pydantic model; `AnalysisError` raised on schema mismatch

**answers.csv columns:** `timestamp | question_text | message | phone | name | business | confidence | question_id`

**questions.csv columns:** `question_id | timestamp | sender | message_text | is_service_valid | confidence | needs_review`

## Key Design Decisions

- **Direct SQLite access** — bypasses MCP stdio layer; faster and simpler for a polling pipeline
- **Watermark persistence** — saved to `output/watermark.txt`; delete this file to reprocess all messages from the beginning
- **Historical media** — messages synced on first bridge connect have no media metadata; downloads will always fail with `MediaNotAvailable` (silently skipped). Only messages received in real-time while the bridge is running can be downloaded
- **No quoted message linking** — Go bridge doesn't store quoted message IDs; answers are linked to questions via temporal proximity only (120-minute window)
- **Group isolation** — enforced at two levels: startup JID/name cross-check in `Fetcher.validate_group()` and SQL `WHERE chat_jid = ?` filter

## Configuration

Copy `config.yaml.example` to `config.yaml`. Required fields:
- `group.jid` — WhatsApp group JID (find in Go bridge logs on first connect)
- `group.name` — must match exactly as stored in the DB
- `anthropic.api_key_env` — name of the environment variable holding the API key
- `database.path` — path to Go bridge SQLite DB (default: `../mcp/whatsapp-bridge/store/messages.db`)

## Tests

Test fixtures use **synthetic data only** — `tests/fixtures/messages.json` and `tests/fixtures/messages.sql` contain fake names and phone numbers. The real message dump (`tests/fixtures/messages_dump.sql`) is excluded from version control via `.gitignore`.

`conftest.py` provides:
- `db_conn` — in-memory SQLite from `messages.sql` (synthetic)
- `db_conn_dump` — in-memory SQLite from `messages_dump.sql` (real export, only for local testing)

## Privacy

Never commit:
- `config.yaml` — contains real group JID and name
- `output/` — contains real phone numbers, names, message text
- `tests/fixtures/messages_dump.sql` — real WhatsApp export
- `mcp/whatsapp-bridge/store/` — WhatsApp session keys and message DB
