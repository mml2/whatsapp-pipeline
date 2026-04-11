from collections import deque
from datetime import datetime, timedelta
from typing import List

from pipeline.models import WhatsAppMessage


def _parse(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a naive datetime."""
    return datetime.fromisoformat(ts)


class ContextWindow:
    """
    Rolling buffer of recent WhatsApp messages for a single group.

    Used by analyzer.py to supply Claude with conversation history so it
    can apply temporal question linking (SYSTEM_PROMPT Step 4, Rule 2):
    "link to the most recent SERVICE_VALID question within the prior 120 min."

    Usage pattern (called by main.py):
        context = window.get_recent(before_ts=msg.timestamp)
        window.add(msg)
        analyzer.analyze(context, msg)

    get_recent() is always called BEFORE add() so the current message
    is never present in its own context.
    """

    def __init__(self, minutes: int = 120, maxlen: int = 500) -> None:
        self._minutes = minutes
        self._buffer: deque[WhatsAppMessage] = deque(maxlen=maxlen)

    def add(self, msg: WhatsAppMessage) -> None:
        """Append a message to the buffer."""
        self._buffer.append(msg)

    def get_recent(self, before_ts: str, minutes: int | None = None) -> List[WhatsAppMessage]:
        """
        Return messages with timestamps in the half-open interval:
            [before_ts - window_minutes,  before_ts)

        Parameters
        ----------
        before_ts : ISO 8601 string — upper bound (exclusive); typically the
                    current message's timestamp.
        minutes   : override the default window size for this call.
        """
        window_minutes = minutes if minutes is not None else self._minutes
        before_dt = _parse(before_ts)
        cutoff_dt = before_dt - timedelta(minutes=window_minutes)

        return [
            msg for msg in self._buffer
            if cutoff_dt <= _parse(msg.timestamp) < before_dt
        ]

    def __len__(self) -> int:
        return len(self._buffer)
