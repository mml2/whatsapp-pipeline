"""
WhatsApp Contact Extraction Pipeline — Entry Point

Start the pipeline:
    python main.py

Optionally override config path:
    python main.py --config /path/to/config.yaml
"""

import argparse
import os
import signal
import sqlite3
import time
from pathlib import Path

import yaml

from pipeline.analyzer import Analyzer, AnalysisError
from pipeline.context_window import ContextWindow
from pipeline.fetcher import Fetcher, GroupMismatchError
from pipeline import logger
from pipeline.media_handler import download, MediaDownloadError, MediaNotAvailable
from pipeline.models import WhatsAppMessage
from pipeline.storage import Storage

WATERMARK_FILE = "watermark.txt"
_running = True


def _handle_signal(sig, frame):
    global _running
    logger.log("MAIN", "INFO", detail="shutdown signal received, finishing current batch")
    _running = False


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_watermark(output_dir: str) -> str:
    path = Path(output_dir) / WATERMARK_FILE
    if path.exists():
        ts = path.read_text().strip()
        logger.log("MAIN", "INFO", detail=f"resuming from watermark {ts}")
        return ts
    return "1970-01-01T00:00:00"


def save_watermark(output_dir: str, timestamp: str) -> None:
    path = Path(output_dir) / WATERMARK_FILE
    path.write_text(timestamp)


def process_message(
    msg: WhatsAppMessage,
    context_window: ContextWindow,
    analyzer: Analyzer,
    storage: Storage,
    output_dir: str,
) -> None:
    """Process a single message through the full pipeline."""

    # Step 1 — download media if needed
    if msg.media_type and msg.media_type != "text":
        try:
            msg = download(msg)
        except MediaNotAvailable:
            # Historical message — metadata never stored, skip media silently
            pass
        except MediaDownloadError as exc:
            logger.log("MEDIA", "WARN", message_id=msg.message_id, detail=str(exc))
            # Continue without media — analyzer will flag needs_review

    # Step 2 — build context (before adding current message)
    context = context_window.get_recent(before_ts=msg.timestamp)
    context_window.add(msg)

    # Step 3 — analyze
    result = analyzer.analyze(msg, context)
    logger.log(
        "CLASSIFY", "OK",
        message_id=msg.message_id,
        sender=msg.sender,
        type=result.message_type.value,
        text=(msg.text or "")[:60],
    )

    # Step 4 — store
    storage.store(result, msg)


def run(config_path: str) -> None:
    cfg = load_config(config_path)

    # Configure logger
    logger.configure(
        log_file=cfg["logging"]["file"],
        level=cfg["logging"]["level"],
    )
    logger.log("MAIN", "OK", detail="pipeline starting")

    # Output paths
    output_dir = cfg["output"]["directory"]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    questions_path = str(Path(output_dir) / cfg["output"]["questions_file"])
    answers_path   = str(Path(output_dir) / cfg["output"]["answers_file"])

    # Connect to SQLite
    db_path = cfg["database"]["path"]
    if not Path(db_path).exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    logger.log("MAIN", "OK", detail=f"connected to {db_path}")

    # Fetcher — validate group before first poll
    watermark = load_watermark(output_dir)
    fetcher = Fetcher(
        conn=conn,
        group_jid=cfg["group"]["jid"],
        group_name=cfg["group"]["name"],
        start_after=watermark,
    )
    try:
        fetcher.validate_group()
    except GroupMismatchError as exc:
        logger.log("MAIN", "ERROR", detail=str(exc))
        raise SystemExit(1) from exc

    # Pipeline components
    context_window = ContextWindow(minutes=120)
    analyzer = Analyzer(
        system_prompt_path="SYSTEM_PROMPT.md",
        model=cfg["anthropic"]["model"],
        api_key=os.environ[cfg["anthropic"]["api_key_env"]],
        provider=cfg["anthropic"].get("provider", "anthropic"),
    )
    storage = Storage(questions_path=questions_path, answers_path=answers_path)
    interval = cfg["pipeline"]["polling_interval_seconds"]

    # Graceful shutdown on SIGINT / SIGTERM
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.log("MAIN", "OK", detail=f"polling every {interval}s — press Ctrl+C to stop")

    # Poll loop
    while _running:
        messages = fetcher.fetch_new()

        for msg in messages:
            try:
                process_message(msg, context_window, analyzer, storage, output_dir)
            except AnalysisError as exc:
                logger.log("ANALYZE", "ERROR", message_id=msg.message_id, detail=str(exc))
            except Exception as exc:
                logger.log("MAIN", "ERROR", message_id=msg.message_id, detail=str(exc))

        if messages:
            save_watermark(output_dir, fetcher._watermark)
            logger.log("MAIN", "OK", detail=f"processed {len(messages)} messages, watermark saved")

        if _running:
            time.sleep(interval)

    conn.close()
    logger.log("MAIN", "OK", detail="pipeline stopped cleanly")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WhatsApp contact extraction pipeline")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    run(args.config)
