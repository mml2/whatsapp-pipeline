# WhatsApp Contact Extraction Pipeline

A pipeline that monitors a WhatsApp group, classifies messages using Claude/GPT-4o, and extracts service contact information into structured CSV files. This is a PoC project ONLY.

## What it does

1. Polls a WhatsApp group's SQLite database (written by the Go bridge) every N seconds
2. Classifies each message as `QUESTION`, `ANSWER`, `CHAT`, or `ANNOUNCEMENT`
3. Links answers to the questions they respond to (temporal threading within a 120-minute window)
4. Extracts contact info (phone, name, business) from answers
5. Writes results to `questions.csv` and `answers.csv`

## Prerequisites

- Python 3.11
- [whatsapp-mcp](https://github.com/lharries/whatsapp-mcp) Go bridge running and authenticated
- Anthropic or OpenAI API key

## Setup

### 1. Start the Go bridge

Clone and run the Go bridge so it starts syncing your WhatsApp messages to SQLite:

```bash
git clone https://github.com/lharries/whatsapp-mcp ../mcp
cd ../mcp/whatsapp-bridge
go run main.go   # scan the QR code to authenticate
```

The bridge writes messages to `../mcp/whatsapp-bridge/store/messages.db`.

### 2. Find your group JID

```bash
sqlite3 ../mcp/whatsapp-bridge/store/messages.db \
  "SELECT jid, name FROM chats;"
```

Copy the `@g.us` JID for your target group.

### 3. Install Python dependencies

```bash
pip install -r pipeline/requirements.txt
```

### 4. Configure the pipeline

```bash
cp pipeline/config.yaml.example pipeline/config.yaml
```

Edit `pipeline/config.yaml`:

```yaml
database:
  path: "../mcp/whatsapp-bridge/store/messages.db"

group:
  jid: "XXXXXXXXXXXXXXXXX@g.us"   # from step 2
  name: "Your Group Name"          # must match exactly

pipeline:
  polling_interval_seconds: 10

output:
  directory: "./output"
  questions_file: "questions.csv"
  answers_file: "answers.csv"

logging:
  level: "INFO"
  file: "./logs/pipeline.log"

anthropic:
  provider: "anthropic"            # "anthropic" or "openai"
  api_key_env: "ANTHROPIC_API_KEY" # env var holding your key
  model: "claude-sonnet-4-6"       # vision-capable model required for image extraction
```

### 5. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
# or for OpenAI:
export OPENAI_API_KEY="sk-..."
```

### 6. Run

```bash
cd pipeline
python main.py
# or with a custom config path:
python main.py --config /path/to/config.yaml
```

Press `Ctrl+C` for a clean shutdown. Progress is saved to `output/watermark.txt` so the pipeline resumes where it left off.

## Output

| File | Contents |
|---|---|
| `output/questions.csv` | Service-seeking questions with confidence score and `needs_review` flag |
| `output/answers.csv` | Actionable answers linked to their parent question, with extracted phone/name/business |

Messages classified as `CHAT` or `ANNOUNCEMENT` are not written to any file.

## Running tests

```bash
cd pipeline
pytest tests/ --cov=pipeline --cov-report=term-missing
```

Target: **90% coverage minimum** before any production run.

## Project structure

```
pipeline/
├── main.py                  # Entry point — poll loop
├── config.yaml.example      # Configuration template
├── SYSTEM_PROMPT.md         # Claude prompt (edit to tune behavior)
├── ARCHITECTURE.md          # Detailed architecture and schema notes
├── SETUP.md                 # Setup reference
├── requirements.txt
│
├── pipeline/
│   ├── models.py            # Pydantic models: WhatsAppMessage, AnalysisResult
│   ├── fetcher.py           # SQLite polling; group JID/name validation
│   ├── media_handler.py     # vcard/image download via Go bridge HTTP API
│   ├── context_window.py    # 120-minute rolling message buffer
│   ├── analyzer.py          # Claude/GPT API call; response validation
│   ├── storage.py           # CSV writer
│   └── logger.py            # Structured [STAGE][STATUS] logging
│
└── tests/
    ├── conftest.py
    ├── fixtures/
    └── test_*.py
```

## Known limitations

- **No quoted-message threading** — the Go bridge does not store reply/quote IDs. Answer-to-question linking uses temporal proximity (120-minute window) only.
- **Media requires a live Go bridge** — historical messages whose media was never downloaded are skipped silently.
- **Read-only** — the pipeline never sends messages to WhatsApp.

## Architecture

See [pipeline/ARCHITECTURE.md](pipeline/ARCHITECTURE.md) for the full data-flow diagram, SQLite schema, and component descriptions.
