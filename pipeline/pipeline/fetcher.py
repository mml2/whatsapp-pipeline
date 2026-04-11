import sqlite3
from typing import List

from pipeline.logger import log
from pipeline.models import WhatsAppMessage


class GroupMismatchError(Exception):
    """Raised when the configured JID does not match the expected group name."""


class Fetcher:
    """
    Reads new messages from the Go bridge SQLite database.

    Schema note (github.com/lharries/whatsapp-mcp):
    - messages table has NO quoted_message_id column; quoted_message_id is
      always set to None. Threading relies on Claude's temporal linking only
      (SYSTEM_PROMPT Step 4, Rule 2).
    - chat name is stored in the chats table, not the messages table;
      fetcher JOINs to resolve it.

    Responsibilities:
    - Validate at startup that the configured JID resolves to the expected
      group name (aborts the pipeline if misconfigured).
    - Poll for messages newer than the last watermark.
    - Remap SQLite column names to the WhatsAppMessage schema.
    - Advance the watermark so each message is processed exactly once.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        group_jid: str,
        group_name: str,
        start_after: str = "1970-01-01T00:00:00",
    ) -> None:
        self._conn = conn
        self._group_jid = group_jid
        self._group_name = group_name
        self._watermark = start_after
        self._seen_ids: set[str] = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_group(self) -> None:
        """
        Cross-check the configured JID against the chats table.
        Raises GroupMismatchError if the JID is unknown or the name differs.
        Must be called once before the first fetch_new().
        """
        row = self._conn.execute(
            "SELECT name FROM chats WHERE jid = ?", (self._group_jid,)
        ).fetchone()

        if row is None:
            raise GroupMismatchError(
                f"JID '{self._group_jid}' not found in chats table. "
                "Has the Go bridge synced yet?"
            )

        actual_name = row[0] if isinstance(row, tuple) else row["name"]
        if actual_name != self._group_name:
            raise GroupMismatchError(
                f"JID '{self._group_jid}' resolves to '{actual_name}', "
                f"expected '{self._group_name}'. Check config.yaml."
            )

        log("FETCH", "OK", detail=f"group validated: {self._group_name}")

    def fetch_new(self) -> List[WhatsAppMessage]:
        """
        Return all messages in the target group with timestamp > watermark,
        ordered oldest-first. Advances the watermark to the latest timestamp
        seen. Skips any message_id already processed this session.
        """
        rows = self._conn.execute(
            """
            SELECT  m.id,
                    c.name  AS group_name,
                    m.sender,
                    m.content,
                    m.timestamp,
                    m.media_type
            FROM    messages m
            JOIN    chats    c ON c.jid = m.chat_jid
            WHERE   m.chat_jid  = ?
              AND   m.timestamp > ?
            ORDER   BY m.timestamp ASC
            """,
            (self._group_jid, self._watermark),
        ).fetchall()

        messages: List[WhatsAppMessage] = []
        for row in rows:
            msg_id = row[0] if isinstance(row, tuple) else row["id"]

            if msg_id in self._seen_ids:
                continue

            msg = self._remap(row)
            self._seen_ids.add(msg_id)
            messages.append(msg)
            log("FETCH", "OK", message_id=msg_id, sender=msg.sender)

        if messages:
            self._watermark = messages[-1].timestamp

        return messages

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _remap(self, row) -> WhatsAppMessage:
        """Map a SQLite row to a WhatsAppMessage (SYSTEM_PROMPT input schema)."""
        if isinstance(row, tuple):
            id_, group_name, sender, content, timestamp, media_type = row
        else:
            id_         = row["id"]
            group_name  = row["group_name"]
            sender      = row["sender"]
            content     = row["content"]
            timestamp   = row["timestamp"]
            media_type  = row["media_type"]

        return WhatsAppMessage(
            message_id=id_,
            timestamp=timestamp,
            sender=sender,
            group=group_name or self._group_name,
            text=content,
            media_type=media_type,
            quoted_message_id=None,   # not stored by the Go bridge
        )
