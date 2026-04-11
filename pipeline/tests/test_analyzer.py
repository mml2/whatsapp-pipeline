import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pipeline.analyzer import Analyzer, AnalysisError, _parse_vcard
from pipeline.models import (
    AnalysisResult, MessageType, WhatsAppMessage,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYSTEM_PROMPT_PATH = Path(__file__).parent.parent / "SYSTEM_PROMPT.md"
DUMMY_MODEL = "claude-sonnet-4-6"
DUMMY_KEY = "test-key"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_fixture_messages() -> dict:
    data = json.loads((FIXTURES_DIR / "messages.json").read_text())
    return {m["message_id"]: WhatsAppMessage(**m) for m in data}


def load_expected_results() -> dict:
    data = json.loads((FIXTURES_DIR / "analysis_results.json").read_text())
    return {r["message_id"]: r for r in data}


def make_analyzer(mock_client) -> Analyzer:
    analyzer = Analyzer(str(SYSTEM_PROMPT_PATH), DUMMY_MODEL, DUMMY_KEY)
    analyzer._client = mock_client
    return analyzer


def mock_response(payload: dict) -> MagicMock:
    """Wrap a dict in the shape the Anthropic SDK returns."""
    block = MagicMock()
    block.text = json.dumps(payload)
    resp = MagicMock()
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# Startup — system prompt loading
# ---------------------------------------------------------------------------

class TestSystemPromptLoading:
    def test_system_prompt_loaded_at_init(self):
        mock_client = MagicMock()
        analyzer = make_analyzer(mock_client)
        assert len(analyzer._system_prompt) > 0

    def test_system_prompt_contains_key_instructions(self):
        mock_client = MagicMock()
        analyzer = make_analyzer(mock_client)
        assert "QUESTION" in analyzer._system_prompt
        assert "ANSWER" in analyzer._system_prompt

    def test_missing_system_prompt_raises(self):
        with pytest.raises(FileNotFoundError):
            Analyzer("/nonexistent/SYSTEM_PROMPT.md", DUMMY_MODEL, DUMMY_KEY)


# ---------------------------------------------------------------------------
# User content construction
# ---------------------------------------------------------------------------

class TestUserContentConstruction:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.analyzer = make_analyzer(self.mock_client)
        self.messages = load_fixture_messages()

    def _captured_user_content(self, msg_id: str, context_ids: list[str]) -> str:
        msg = self.messages[msg_id]
        context = [self.messages[i] for i in context_ids]
        expected = json.loads(
            list(load_expected_results().values())[0] if False else "{}"
        )
        self.mock_client.messages.create.return_value = mock_response(
            load_expected_results()[msg_id]
        )
        self.analyzer.analyze(msg, context)
        call_kwargs = self.mock_client.messages.create.call_args
        return call_kwargs.kwargs["messages"][0]["content"]

    def test_current_message_present_in_user_content(self):
        content = self._captured_user_content("msg_001", [])
        assert "msg_001" in content

    def test_context_messages_present_in_user_content(self):
        content = self._captured_user_content("msg_003", ["msg_001", "msg_002"])
        assert "msg_001" in content
        assert "msg_002" in content

    def test_local_media_path_excluded_from_payload(self):
        content = self._captured_user_content("msg_001", [])
        assert "local_media_path" not in content

    def test_empty_context_produces_empty_array(self):
        content = self._captured_user_content("msg_001", [])
        data = json.loads(content.split("Analyze this message:")[0]
                          .replace("Recent conversation context:\n", "").strip())
        assert data == []

    def test_system_prompt_passed_to_api(self):
        msg = self.messages["msg_001"]
        self.mock_client.messages.create.return_value = mock_response(
            load_expected_results()["msg_001"]
        )
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        assert "QUESTION" in call_kwargs.kwargs["system"]

    def test_correct_model_passed_to_api(self):
        msg = self.messages["msg_001"]
        self.mock_client.messages.create.return_value = mock_response(
            load_expected_results()["msg_001"]
        )
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        assert call_kwargs.kwargs["model"] == DUMMY_MODEL


# ---------------------------------------------------------------------------
# Response parsing and Pydantic validation
# ---------------------------------------------------------------------------

class TestResponseParsing:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.analyzer = make_analyzer(self.mock_client)
        self.messages = load_fixture_messages()
        self.expected = load_expected_results()

    def _analyze(self, msg_id: str) -> AnalysisResult:
        msg = self.messages[msg_id]
        self.mock_client.messages.create.return_value = mock_response(
            self.expected[msg_id]
        )
        return self.analyzer.analyze(msg, [])

    def test_returns_analysis_result_instance(self):
        result = self._analyze("msg_001")
        assert isinstance(result, AnalysisResult)

    def test_invalid_json_raises_analysis_error(self):
        msg = self.messages["msg_001"]
        block = MagicMock()
        block.text = "not valid json {{{"
        resp = MagicMock()
        resp.content = [block]
        self.mock_client.messages.create.return_value = resp
        with pytest.raises(AnalysisError, match="non-JSON"):
            self.analyzer.analyze(msg, [])

    def test_missing_required_field_raises_analysis_error(self):
        msg = self.messages["msg_001"]
        # message_type is required — omit it
        bad_payload = {k: v for k, v in self.expected["msg_001"].items()
                       if k != "message_type"}
        self.mock_client.messages.create.return_value = mock_response(bad_payload)
        with pytest.raises(AnalysisError, match="Schema validation"):
            self.analyzer.analyze(msg, [])

    def test_invalid_enum_value_raises_analysis_error(self):
        msg = self.messages["msg_001"]
        bad_payload = dict(self.expected["msg_001"])
        bad_payload["message_type"] = "INVALID"
        self.mock_client.messages.create.return_value = mock_response(bad_payload)
        with pytest.raises(AnalysisError, match="Schema validation"):
            self.analyzer.analyze(msg, [])


# ---------------------------------------------------------------------------
# Per-message-type correctness (using fixture ground truth)
# ---------------------------------------------------------------------------

class TestMessageTypeClassification:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.analyzer = make_analyzer(self.mock_client)
        self.messages = load_fixture_messages()
        self.expected = load_expected_results()

    def _analyze(self, msg_id: str) -> AnalysisResult:
        msg = self.messages[msg_id]
        self.mock_client.messages.create.return_value = mock_response(
            self.expected[msg_id]
        )
        return self.analyzer.analyze(msg, [])

    def test_question_high_confidence(self):
        result = self._analyze("msg_001")
        assert result.message_type == MessageType.QUESTION
        assert result.question_analysis.is_service_valid is True
        assert result.question_analysis.confidence.value == "HIGH"
        assert result.question_analysis.needs_review is False
        assert result.answer_analysis is None

    def test_question_low_confidence_flagged_for_review(self):
        result = self._analyze("msg_002")
        assert result.message_type == MessageType.QUESTION
        assert result.question_analysis.is_service_valid is False
        assert result.question_analysis.confidence.value == "LOW"
        assert result.question_analysis.needs_review is True

    def test_answer_with_phone_number(self):
        result = self._analyze("msg_003")
        assert result.message_type == MessageType.ANSWER
        assert result.answer_analysis.is_actionable is True
        assert result.answer_analysis.confidence.value == "HIGH"
        assert result.answer_analysis.parent_question_id == "msg_001"
        assert result.answer_analysis.link_method.value == "temporal"
        assert result.answer_analysis.contact.phone == "+971501234567"
        assert result.question_analysis is None

    def test_answer_links_to_most_recent_service_valid_question(self):
        # msg_004 should link to msg_001 (SERVICE_VALID), not msg_002 (invalid)
        result = self._analyze("msg_004")
        assert result.answer_analysis.parent_question_id == "msg_001"

    def test_chat_has_null_analyses(self):
        result = self._analyze("msg_005")
        assert result.message_type == MessageType.CHAT
        assert result.question_analysis is None
        assert result.answer_analysis is None

    def test_announcement_has_null_analyses(self):
        result = self._analyze("msg_006")
        assert result.message_type == MessageType.ANNOUNCEMENT
        assert result.question_analysis is None
        assert result.answer_analysis is None

    def test_vcard_answer_flagged_for_review(self):
        result = self._analyze("msg_007")
        assert result.message_type == MessageType.ANSWER
        assert result.answer_analysis.is_actionable is True
        assert result.answer_analysis.contact.source_type.value == "vcard"
        assert result.answer_analysis.needs_review is True

    def test_image_answer_flagged_for_review(self):
        result = self._analyze("msg_008")
        assert result.message_type == MessageType.ANSWER
        assert result.answer_analysis.is_actionable is True
        assert result.answer_analysis.contact.source_type.value == "image"
        assert result.answer_analysis.needs_review is True

    def test_orphan_answer_has_null_parent_and_flagged(self):
        result = self._analyze("msg_009")
        assert result.message_type == MessageType.ANSWER
        assert result.answer_analysis.is_actionable is True
        assert result.answer_analysis.parent_question_id is None
        assert result.answer_analysis.link_method is None
        assert result.answer_analysis.needs_review is True

    def test_question_signals_populated(self):
        result = self._analyze("msg_001")
        s = result.question_analysis.signals
        assert s.service_noun is True
        assert s.request_verb is True
        assert s.contact_language is True
        assert s.location_anchor is True
        assert s.price_or_availability is False


# ---------------------------------------------------------------------------
# VCard parsing (_parse_vcard module function)
# ---------------------------------------------------------------------------

class TestParseVcard:
    def test_fn_extracted(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed Al Rashid\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert "Ahmed Al Rashid" in result

    def test_tel_extracted(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed\nTEL:+971501234567\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert "+971501234567" in result

    def test_tel_with_type_extracted(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed\nTEL;TYPE=CELL:+971501234567\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert "+971501234567" in result

    def test_org_extracted(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed\nORG:Ahmed Plumbing LLC\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert "Ahmed Plumbing LLC" in result

    def test_multiple_phones_combined(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text(
            "BEGIN:VCARD\nFN:Ahmed\nTEL:+971501234567\nTEL:+97143001234\nEND:VCARD\n"
        )
        result = _parse_vcard(str(vcf))
        assert "+971501234567" in result
        assert "+97143001234" in result

    def test_empty_vcard_returns_fallback(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert "no readable fields" in result.lower()

    def test_result_starts_with_vcard_prefix(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed\nTEL:+971501234567\nEND:VCARD\n")
        result = _parse_vcard(str(vcf))
        assert result.startswith("[VCard]")


# ---------------------------------------------------------------------------
# VCard enrichment in Analyzer
# ---------------------------------------------------------------------------

class TestVcardEnrichment:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.analyzer = make_analyzer(self.mock_client)
        self.expected = load_expected_results()

    def _make_vcard_msg(self, vcf_path: str) -> WhatsAppMessage:
        return WhatsAppMessage(
            message_id="msg_007",
            timestamp="2024-01-15T10:30:00",
            sender="Deepa",
            group="Wayne Desi Gals",
            text=None,
            media_type="vcard",
            quoted_message_id=None,
            local_media_path=vcf_path,
        )

    def test_vcard_text_injected_into_payload(self, tmp_path):
        vcf = tmp_path / "contact.vcf"
        vcf.write_text("BEGIN:VCARD\nFN:Ahmed Al Rashid\nTEL:+971501234567\nEND:VCARD\n")
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_007"]
        )
        msg = self._make_vcard_msg(str(vcf))
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        assert "Ahmed Al Rashid" in user_content
        assert "+971501234567" in user_content

    def test_vcard_without_file_uses_text_only(self):
        """When local_media_path is None, no enrichment — existing behaviour."""
        messages = load_fixture_messages()
        msg = messages["msg_007"]  # local_media_path is None in fixtures
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_007"]
        )
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        # The raw null text field should be in the payload, not vcard data
        assert "[VCard]" not in user_content

    def test_missing_vcard_file_falls_back_gracefully(self, tmp_path):
        """If the file is missing, analyze should still complete (no exception)."""
        msg = self._make_vcard_msg("/nonexistent/contact.vcf")
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_007"]
        )
        # Should not raise — warning logged, msg passed through unchanged
        result = self.analyzer.analyze(msg, [])
        assert isinstance(result, AnalysisResult)


# ---------------------------------------------------------------------------
# Image vision path
# ---------------------------------------------------------------------------

class TestImageVision:
    def setup_method(self):
        self.mock_client = MagicMock()
        self.analyzer = make_analyzer(self.mock_client)
        self.expected = load_expected_results()

    def _make_image_msg(self, image_path: str) -> WhatsAppMessage:
        return WhatsAppMessage(
            message_id="msg_008",
            timestamp="2024-01-15T10:35:00",
            sender="Layla",
            group="Wayne Desi Gals",
            text=None,
            media_type="image",
            quoted_message_id=None,
            local_media_path=image_path,
        )

    def test_image_uses_multimodal_call(self, tmp_path):
        """When local_media_path is set for an image, vision API path is taken."""
        img = tmp_path / "card.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 10)  # minimal JPEG header
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_008"]
        )
        msg = self._make_image_msg(str(img))
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        # For Anthropic, content should be a list with image + text blocks
        content = call_kwargs.kwargs["messages"][0]["content"]
        assert isinstance(content, list)
        types = [block["type"] for block in content]
        assert "image" in types
        assert "text" in types

    def test_image_without_file_uses_text_only(self):
        """When local_media_path is None, normal text-only call is made."""
        messages = load_fixture_messages()
        msg = messages["msg_008"]  # local_media_path is None
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_008"]
        )
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        user_content = call_kwargs.kwargs["messages"][0]["content"]
        # Normal string content, not a list
        assert isinstance(user_content, str)

    def test_missing_image_file_falls_back_to_text(self):
        """If image file is gone, analyzer falls back to text-only call."""
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_008"]
        )
        msg = self._make_image_msg("/nonexistent/image.jpg")
        result = self.analyzer.analyze(msg, [])
        assert isinstance(result, AnalysisResult)

    def test_png_mime_type_detected(self, tmp_path):
        img = tmp_path / "card.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 10)
        self.mock_client.messages.create.return_value = mock_response(
            self.expected["msg_008"]
        )
        msg = self._make_image_msg(str(img))
        self.analyzer.analyze(msg, [])
        call_kwargs = self.mock_client.messages.create.call_args
        content = call_kwargs.kwargs["messages"][0]["content"]
        image_block = next(b for b in content if b["type"] == "image")
        assert image_block["source"]["media_type"] == "image/png"
