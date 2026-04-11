import logging
import logging.handlers
import os
from typing import Any


_logger = logging.getLogger("pipeline")
_configured = False


def configure(log_file: str, level: str = "INFO") -> None:
    """Call once at startup with values from config.yaml."""
    global _configured
    if _configured:
        return

    numeric_level = getattr(logging, level.upper(), logging.INFO)
    _logger.setLevel(numeric_level)

    formatter = logging.Formatter("%(message)s")

    stdout_handler = logging.StreamHandler()
    stdout_handler.setFormatter(formatter)
    _logger.addHandler(stdout_handler)

    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=3
    )
    file_handler.setFormatter(formatter)
    _logger.addHandler(file_handler)

    _configured = True


def log(stage: str, status: str, **kwargs: Any) -> None:
    """
    Emit a structured log line.

    Format: [STAGE][STATUS]  key=val | key=val

    Examples:
        log("CLASSIFY", "OK", message_id=101, type="QUESTION", confidence="HIGH")
        log("THREAD", "WARN", message_id=104, detail="no parent found, flagged for review")
        log("STORE", "OK", answer_id="A023", linked_to="Q011")
    """
    pairs = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    line = f"[{stage.upper()}][{status.upper()}]  {pairs}"

    if status.upper() in ("ERROR", "FAIL"):
        _logger.error(line)
    elif status.upper() == "WARN":
        _logger.warning(line)
    else:
        _logger.info(line)
