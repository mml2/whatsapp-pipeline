import requests

from pipeline.logger import log
from pipeline.models import WhatsAppMessage

DOWNLOAD_URL = "http://localhost:8080/api/download"

# These Go bridge error messages mean media metadata was never stored
# (historical messages synced without full metadata). Treat as a skip,
# not a hard error — the analyzer will mark needs_review: true.
_SKIP_REASONS = (
    "incomplete media information for download",
    "not a media message",
    "failed to find message",
)


class MediaDownloadError(Exception):
    """Raised when the Go bridge returns an unexpected failure."""


class MediaNotAvailable(Exception):
    """
    Raised when media metadata is absent from the DB — typically for
    historical messages synced before the bridge was connected.
    Callers should continue processing the message without media.
    """


def download(msg: WhatsAppMessage, timeout: int = 10) -> WhatsAppMessage:
    """
    Download media for a message that has a non-text media_type.

    Calls the Go bridge at localhost:8080/api/download, attaches the
    returned local file path to msg.local_media_path, and returns the
    updated message.

    Rules:
    - Text messages (media_type == "text" or None) are returned unchanged.
    - On a successful download, local_media_path is set.
    - On "incomplete media information" (historical message), raises
      MediaNotAvailable — callers should skip media and continue.
    - On any other bridge failure or network error, raises MediaDownloadError.
    """
    if not msg.media_type or msg.media_type == "text":
        return msg

    try:
        response = requests.post(
            DOWNLOAD_URL,
            json={"message_id": msg.message_id, "chat_jid": msg.group},
            timeout=timeout,
        )
    except (requests.RequestException, ConnectionError) as exc:
        log("MEDIA", "ERROR", message_id=msg.message_id, detail=str(exc))
        raise MediaDownloadError(f"Network error for {msg.message_id}: {exc}") from exc

    # Try to read JSON body regardless of HTTP status code
    try:
        data = response.json()
    except Exception:
        # Non-JSON body — fall back to HTTP status
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            log("MEDIA", "ERROR", message_id=msg.message_id, detail=str(exc))
            raise MediaDownloadError(f"Bridge HTTP error for {msg.message_id}: {exc}") from exc
        data = {}

    if not data.get("success"):
        detail = data.get("message") or data.get("Message") or response.reason or "unknown error"

        # Known skip condition — historical message without media metadata
        if any(reason in detail.lower() for reason in _SKIP_REASONS):
            log("MEDIA", "SKIP", message_id=msg.message_id,
                detail="media metadata unavailable (historical message)")
            raise MediaNotAvailable(detail)

        # Unexpected failure
        log("MEDIA", "ERROR", message_id=msg.message_id, detail=detail)
        raise MediaDownloadError(f"Go bridge failed for {msg.message_id}: {detail}")

    file_path = data.get("file_path") or data.get("path")
    log("MEDIA", "OK", message_id=msg.message_id, media_type=msg.media_type, file_path=file_path)

    return msg.model_copy(update={"local_media_path": file_path})
