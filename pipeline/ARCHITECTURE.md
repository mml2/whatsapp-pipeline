# WhatsApp Contact Extraction Pipeline — Architecture

## What the MCP repo reveals (and why it matters)

| Finding | Impact on architecture |
|---|---|
| MCP server uses **stdio transport** (not HTTP) | Cannot call it like a REST API; requires subprocess + JSON-RPC |
| Message object field is **`content`**, not `text`; **`id`** not `message_id` | Fetcher must remap fields to match SYSTEM_PROMPT's input schema |
| Go bridge stores everything in **SQLite at `../whatsapp-bridge/store/messages.db`** | Fetcher reads SQLite directly — simpler and gives all fields |
| **`download_media` tool** exists (calls Go bridge at `localhost:8080/api/download`) | Media pipeline must call Go bridge HTTP API for vcard/image payloads |
| **`quoted_message_id` is NOT stored** in the Go bridge SQLite schema | Threading Rule 1 (quoted link) is permanently unavailable; all answers fall through to Rule 2 (temporal) or Rule 3 (orphan) — see Known Limitation below |
| **`chat_name` is NOT a column on `messages`** — only on `chats` | Fetcher must JOIN `messages` to `chats` to resolve group name |

**Bottom line:** For a standalone pipeline, the cleanest approach is to bypass the stdio MCP layer for reading and query SQLite directly. The Go bridge HTTP API at `localhost:8080` is used only for media download. This avoids subprocess management and reflects the actual schema.

---

## Known Limitation — No Quoted Message Linking (Rule 1)

The Go bridge (`github.com/lharries/whatsapp-mcp`) does **not** store quoted/reply message IDs in its SQLite schema. The `messages` table has no `quoted_stanza_id` or equivalent column.

**Consequence:** SYSTEM_PROMPT Step 4, Rule 1 ("if the message uses WhatsApp's quote feature, the quoted message ID is the parent question ID") will **never fire** in this pipeline. Every answer message will always have `quoted_message_id: null` passed to Claude.

**Effective threading behaviour:**
- Rule 1 (quoted link) — **never available**
- Rule 2 (temporal) — primary linking method; Claude links to the most recent SERVICE_VALID question within 120 min of context provided
- Rule 3 (orphan) — `parent_question_id: null`, `needs_review: true` when no question exists in context window

**If Rule 1 is needed in future:** the Go bridge source would need to be modified to capture `quoted_stanza_id` from the whatsmeow message event and persist it to the DB. This is a bridge-level change, not a pipeline-level change.

---

## Actual SQLite Schema (from `whatsapp-bridge/main.go`)

```sql
CREATE TABLE IF NOT EXISTS chats (
    jid               TEXT PRIMARY KEY,
    name              TEXT,
    last_message_time TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id              TEXT,
    chat_jid        TEXT,
    sender          TEXT,
    content         TEXT,
    timestamp       TIMESTAMP,
    is_from_me      BOOLEAN,
    media_type      TEXT,
    filename        TEXT,
    url             TEXT,
    media_key       BLOB,
    file_sha256     BLOB,
    file_enc_sha256 BLOB,
    file_length     INTEGER,
    PRIMARY KEY (id, chat_jid),
    FOREIGN KEY (chat_jid) REFERENCES chats(jid)
);
```

Columns used by the pipeline:

| Column | Table | Maps to |
|---|---|---|
| `id` | `messages` | `message_id` |
| `content` | `messages` | `text` |
| `sender` | `messages` | `sender` |
| `timestamp` | `messages` | `timestamp` |
| `media_type` | `messages` | `media_type` |
| `filename` | `messages` | used by `media_handler` for download |
| `name` | `chats` (JOIN) | `group` |
| — | — | `quoted_message_id` always `null` |

---

## 1. File & Folder Structure

```
pipeline/
├── SYSTEM_PROMPT.md                  # (existing) Loaded at runtime as Claude system prompt
├── SETUP.md                          # (existing) Setup guide
├── ARCHITECTURE.md                   # (this file)
├── config.yaml                       # DB path, group JID + name, polling interval, output paths, API key env var name
├── main.py                           # Entry point: start the poll → analyze → store loop
│
├── pipeline/
│   ├── __init__.py
│   ├── models.py                     # Pydantic models: WhatsAppMessage, AnalysisResult, Contact
│   ├── fetcher.py                    # Polls SQLite messages.db; validates group JID vs name at startup; JOINs chats for group name
│   ├── media_handler.py              # Calls Go bridge HTTP API (localhost:8080/api/download) for vcard/image
│   ├── context_window.py             # Rolling 120-min message buffer; supplies Claude with conversation history
│   ├── analyzer.py                   # Builds Claude API payload; validates JSON response via Pydantic
│   ├── storage.py                    # Appends to questions.csv / answers.csv; skips CHAT/ANNOUNCEMENT
│   └── logger.py                     # Emits [STAGE][STATUS] key=val structured log lines
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                   # Fixtures: in-memory SQLite, mock Claude client, mock Go bridge
│   ├── test_fetcher.py               # SQLite polling, field remapping, deduplication, group isolation
│   ├── test_media_handler.py         # Go bridge HTTP call, failure handling, source_type routing
│   ├── test_context_window.py        # 120-min cutoff, window boundary, maxlen eviction
│   ├── test_analyzer.py              # Prompt construction, Claude response parse, Pydantic rejection
│   ├── test_storage.py               # QUESTION → questions.csv, ANSWER → answers.csv, CHAT skipped
│   └── fixtures/
│       ├── messages.sql              # INSERT statements matching exact Go bridge schema
│       ├── messages.json             # Sample WhatsAppMessage objects after fetcher remapping
│       └── analysis_results.json     # Expected AnalysisResult outputs keyed by message_id
│
└── requirements.txt
```

---

## 2. File Descriptions

| File | Purpose |
|---|---|
| `config.yaml` | SQLite DB path, target group JID (`@g.us`) **and name** ("Wayne Desi Gals"), polling interval, CSV output directory, log level |
| `main.py` | Load config; start infinite poll loop: fetch → (download media if needed) → build context → analyze → store |
| `pipeline/models.py` | `WhatsAppMessage` matches SYSTEM_PROMPT input schema; `AnalysisResult` mirrors SYSTEM_PROMPT output schema exactly |
| `pipeline/fetcher.py` | On startup: cross-checks configured JID against `chats` table — aborts if mismatch. At runtime: JOINs `messages` + `chats`; maps `id→message_id`, `content→text`, `chats.name→group`; `quoted_message_id` always `None` |
| `pipeline/media_handler.py` | For messages with non-null `media_type`, POSTs to Go bridge `localhost:8080/api/download`; returns local file path; sets `source_type` to `vcard` or `image` |
| `pipeline/context_window.py` | Deque of recent `WhatsAppMessage` objects; `add(msg)` and `get_recent(before_ts, minutes=120)` supply Claude with the 120-min history needed for temporal threading |
| `pipeline/analyzer.py` | Reads `SYSTEM_PROMPT.md` once at startup; serializes context + current message as user turn; calls `anthropic.messages.create`; validates response with Pydantic |
| `pipeline/storage.py` | Checks `message_type`; writes flat row to `questions.csv` or `answers.csv`; creates files with headers on first write |
| `pipeline/logger.py` | `log(stage, status, **kwargs)` formats and writes `[STAGE][STATUS] k=v \| k=v` lines to stdout + rotating file |
| `tests/conftest.py` | In-memory SQLite seeded from `messages.sql`; patched `anthropic.Anthropic`; stubbed Go bridge via `responses` library |
| `tests/fixtures/messages.sql` | Schema + INSERT rows matching exact Go bridge DDL; covers all message types and a second group for isolation tests |

---

## 3. Technology Stack

| Library | Version | Justification |
|---|---|---|
| `anthropic` | `>=0.26` | Official Claude SDK; handles auth, retries, structured message API |
| `pydantic` | `>=2.0` | Validates Claude's JSON output against exact SYSTEM_PROMPT schema before any CSV write; rejects hallucinated or missing fields |
| `sqlite3` | stdlib | Reads `messages.db` directly — avoids stdio subprocess complexity of MCP layer |
| `requests` | `>=2.32` | POSTs to Go bridge `localhost:8080/api/download` for media; already a dependency of the MCP server |
| `pyyaml` | `>=6.0` | Parses `config.yaml`; cleaner than `configparser` for nested keys |
| `python-dateutil` | `>=2.9` | Robust ISO 8601 and timezone-aware datetime parsing for 120-min window logic |
| `pytest` | `>=8.0` | Required by SETUP.md |
| `pytest-cov` | `>=5.0` | Coverage gating to 90% as required by SETUP.md |
| `pytest-mock` | `>=3.12` | Patches Claude client and Go bridge HTTP calls cleanly in unit tests |
| `responses` | `>=0.25` | Intercepts `requests` calls to `localhost:8080` in tests without a live Go bridge |
| `csv` | stdlib | Append-only CSV writes; no external dependency needed |
| `logging` + `RotatingFileHandler` | stdlib | Backs `logger.py`; handles file rotation without extra deps |

**Not used:**
- `mcp` SDK — not needed since we read SQLite directly; the MCP layer is for LLM-agent use, not standalone pipelines
- `httpx` / async — messages arrive sequentially; no concurrency benefit, and async would complicate the test surface

---

## 4. Data Flow: One Message, Start to Finish

```
┌──────────────────────────────────────────────────────┐
│  Go WhatsApp Bridge (running separately)             │
│  Maintains live WhatsApp connection via whatsmeow    │
│  Syncs all incoming messages to SQLite               │
│  ../whatsapp-bridge/store/messages.db                │
└──────────────────────┬───────────────────────────────┘
                       │  messages + chats tables
                       ▼
┌──────────────────────────────────────────────────────┐
│  fetcher.py  — STARTUP CHECK                         │
│  SELECT name FROM chats WHERE jid = configured_jid   │
│  Assert name == "Wayne Desi Gals" → abort if not     │
│                                                      │
│  POLL LOOP                                           │
│  SELECT m.*, c.name                                  │
│  FROM messages m JOIN chats c ON c.jid = m.chat_jid  │
│  WHERE m.chat_jid = group_jid                        │
│    AND m.timestamp > last_processed_ts               │
│  Map DB columns → WhatsAppMessage:                   │
│      id        → message_id                          │
│      content   → text                                │
│      c.name    → group                               │
│      quoted_message_id → None  (not in schema)       │
│  Advance watermark                                   │
└──────────────────────┬───────────────────────────────┘
                       │  WhatsAppMessage (Pydantic)
                       ▼
          ┌────────────────────────────┐
          │  media_type non-null?      │
          │  (vcard / image)           │
          └────────┬───────────────────┘
                   │ YES
                   ▼
        ┌──────────────────────────┐
        │  media_handler.py        │
        │  POST localhost:8080/    │
        │    api/download          │
        │  Returns local file path │
        │  Sets source_type field  │
        └──────────┬───────────────┘
                   │ file path attached to message
                   ▼
┌──────────────────────────────────────────────────────┐
│  context_window.py                                   │
│  context = window.get_recent(before_ts=msg.timestamp)│
│  window.add(msg)                                     │
│  → List[WhatsAppMessage] for Claude context          │
└──────────────────────┬───────────────────────────────┘
                       │  context list + current message
                       ▼
┌──────────────────────────────────────────────────────┐
│  analyzer.py                                         │
│  system: SYSTEM_PROMPT.md (loaded once at startup)   │
│  user:   [context messages as JSON array]            │
│          + current message as JSON                   │
│  → anthropic.messages.create()                       │
│  → parse response text as JSON                       │
│  → validate with AnalysisResult Pydantic model       │
│                                                      │
│  Threading outcome (Rule 1 never fires):             │
│    Rule 2 — temporal link from context window        │
│    Rule 3 — null parent + needs_review: true         │
└──────────────────────┬───────────────────────────────┘
                       │  AnalysisResult (Pydantic)
                       ▼
┌──────────────────────────────────────────────────────┐
│  storage.py                                          │
│  QUESTION    → append row to questions.csv           │
│  ANSWER      → append row to answers.csv             │
│  CHAT        → skip (no write)                       │
│  ANNOUNCEMENT → skip (no write)                      │
└──────────────────────┬───────────────────────────────┘
                       │  at every stage boundary
                       ▼
┌──────────────────────────────────────────────────────┐
│  logger.py                                           │
│  [FETCH][OK]    message_id=101 | sender=Ahmed        │
│  [ANALYZE][OK]  message_id=101 | type=QUESTION       │
│  [STORE][OK]    question_id=Q011 | confidence=HIGH   │
│  [THREAD][WARN] message_id=104 | detail=no parent    │
└──────────────────────────────────────────────────────┘
```

---

## 5. Group Isolation Enforcement

The pipeline enforces "Wayne Desi Gals only" at two levels:

| Level | Mechanism |
|---|---|
| **Startup (config validation)** | `fetcher.py` queries `SELECT name FROM chats WHERE jid = ?` and asserts the result matches `config.target_group_name`. Pipeline aborts with a clear error if the JID points to the wrong group. |
| **Runtime (SQL filter)** | Every poll query includes `WHERE chat_jid = ?` bound to the configured JID. Messages from all other groups are never loaded into memory. |

`config.yaml` stores both fields to enable the cross-check:
```yaml
group:
  jid: "120363xxxxxxxx@g.us"
  name: "Wayne Desi Gals"
```

---

## 6. External Dependencies

| Dependency | Type | Notes |
|---|---|---|
| **Go bridge process** | External process (must be running) | `whatsapp-bridge/main.go` compiled and running; authenticates WhatsApp session via QR code; writes to `messages.db`; exposes `localhost:8080` |
| **SQLite DB** | Local file | `../whatsapp-bridge/store/messages.db`; path configured in `config.yaml`; pipeline is read-only |
| **Go bridge HTTP API** | `localhost:8080` | Only used for media download (`POST /api/download`); not needed for text-only messages |
| **Anthropic API key** | Secret | `ANTHROPIC_API_KEY` env var; never in config files |
| **`SYSTEM_PROMPT.md`** | Local file | Loaded once at startup by `analyzer.py`; edit the file to change model behavior without touching code |
| **Group JID** | Config | Format `"<group-id>@g.us"`; find it by running `SELECT jid, name FROM chats;` in `messages.db` after the Go bridge has synced |
| **Python 3.11** | Runtime | MCP server `.python-version` pins 3.11; match this to avoid SQLite driver surprises |
