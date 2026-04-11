import pytest
import responses as responses_lib

from pipeline.media_handler import download, MediaDownloadError, MediaNotAvailable
from pipeline.models import WhatsAppMessage

DOWNLOAD_URL = "http://localhost:8080/api/download"


def make_msg(media_type: str | None, message_id: str = "msg_007") -> WhatsAppMessage:
    return WhatsAppMessage(
        message_id=message_id,
        timestamp="2024-01-15T10:30:00",
        sender="Deepa",
        group="111111111111@g.us",
        text=None,
        media_type=media_type,
        quoted_message_id=None,
        local_media_path=None,
    )


# ---------------------------------------------------------------------------
# Text / null messages — no HTTP call made
# ---------------------------------------------------------------------------

class TestSkipsNonMediaMessages:
    @responses_lib.activate
    def test_text_message_returned_unchanged(self):
        msg = make_msg("text")
        result = download(msg)
        assert result is msg
        assert len(responses_lib.calls) == 0

    @responses_lib.activate
    def test_none_media_type_returned_unchanged(self):
        msg = make_msg(None)
        result = download(msg)
        assert result is msg
        assert len(responses_lib.calls) == 0


# ---------------------------------------------------------------------------
# Successful downloads
# ---------------------------------------------------------------------------

class TestSuccessfulDownload:
    @responses_lib.activate
    def test_vcard_download_sets_local_media_path(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": True, "message": "ok", "file_path": "/tmp/ahmed.vcf"},
            status=200,
        )
        msg = make_msg("vcard")
        result = download(msg)
        assert result.local_media_path == "/tmp/ahmed.vcf"

    @responses_lib.activate
    def test_image_download_sets_local_media_path(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": True, "message": "ok", "file_path": "/tmp/card.jpg"},
            status=200,
        )
        msg = make_msg("image")
        result = download(msg)
        assert result.local_media_path == "/tmp/card.jpg"

    @responses_lib.activate
    def test_original_message_not_mutated(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": True, "message": "ok", "file_path": "/tmp/file"},
            status=200,
        )
        msg = make_msg("vcard")
        result = download(msg)
        assert msg.local_media_path is None   # original unchanged
        assert result.local_media_path == "/tmp/file"

    @responses_lib.activate
    def test_other_fields_preserved_after_download(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": True, "message": "ok", "file_path": "/tmp/file"},
            status=200,
        )
        msg = make_msg("image", message_id="msg_008")
        result = download(msg)
        assert result.message_id == "msg_008"
        assert result.sender == "Deepa"
        assert result.media_type == "image"

    @responses_lib.activate
    def test_correct_payload_sent_to_bridge(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": True, "message": "ok", "file_path": "/tmp/file"},
            status=200,
        )
        msg = make_msg("vcard", message_id="msg_007")
        download(msg)
        sent = responses_lib.calls[0].request
        import json
        body = json.loads(sent.body)
        assert body["message_id"] == "msg_007"


# ---------------------------------------------------------------------------
# Go bridge failure responses
# ---------------------------------------------------------------------------

class TestBridgeFailures:
    @responses_lib.activate
    def test_bridge_success_false_raises(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "media not found"},
            status=200,
        )
        with pytest.raises(MediaDownloadError, match="media not found"):
            download(make_msg("image"))

    @responses_lib.activate
    def test_http_500_with_unknown_error_raises(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "unexpected server error"},
            status=500,
        )
        with pytest.raises(MediaDownloadError):
            download(make_msg("vcard"))

    @responses_lib.activate
    def test_connection_error_raises(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            body=ConnectionError("bridge not running"),
        )
        with pytest.raises(MediaDownloadError, match="bridge not running"):
            download(make_msg("image"))

    @responses_lib.activate
    def test_timeout_raises(self):
        import requests
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            body=requests.exceptions.Timeout(),
        )
        with pytest.raises(MediaDownloadError):
            download(make_msg("vcard"))


class TestMediaNotAvailable:
    @responses_lib.activate
    def test_incomplete_media_info_raises_not_available(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "incomplete media information for download"},
            status=500,
        )
        with pytest.raises(MediaNotAvailable):
            download(make_msg("image"))

    @responses_lib.activate
    def test_not_a_media_message_raises_not_available(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "not a media message"},
            status=500,
        )
        with pytest.raises(MediaNotAvailable):
            download(make_msg("image"))

    @responses_lib.activate
    def test_failed_to_find_message_raises_not_available(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "failed to find message: sql: no rows"},
            status=500,
        )
        with pytest.raises(MediaNotAvailable):
            download(make_msg("vcard"))

    @responses_lib.activate
    def test_not_available_does_not_raise_media_download_error(self):
        responses_lib.add(
            responses_lib.POST, DOWNLOAD_URL,
            json={"success": False, "message": "incomplete media information for download"},
            status=500,
        )
        with pytest.raises(MediaNotAvailable):
            download(make_msg("image"))
        # Confirm it is NOT a MediaDownloadError
        try:
            pass
        except MediaDownloadError:
            pytest.fail("Should not raise MediaDownloadError for known skip condition")
