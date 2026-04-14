import csv
import json
from pathlib import Path

import pytest

from pipeline.models import AnalysisResult, WhatsAppMessage
from pipeline.storage import Storage, QUESTION_HEADERS, ANSWER_HEADERS

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixtures():
    messages = {
        m["message_id"]: WhatsAppMessage(**m)
        for m in json.loads((FIXTURES_DIR / "messages.json").read_text())
    }
    results = {
        r["message_id"]: AnalysisResult(**r)
        for r in json.loads((FIXTURES_DIR / "analysis_results.json").read_text())
    }
    return messages, results


def read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def storage(tmp_path):
    return Storage(
        questions_path=str(tmp_path / "questions.csv"),
        answers_path=str(tmp_path / "answers.csv"),
    )


@pytest.fixture
def fixtures():
    return load_fixtures()


# ---------------------------------------------------------------------------
# Routing — correct file receives the row
# ---------------------------------------------------------------------------

class TestRouting:
    def test_question_written_to_questions_csv(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        assert (tmp_path / "questions.csv").exists()
        assert not (tmp_path / "answers.csv").exists()

    def test_answer_written_to_answers_csv(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        assert (tmp_path / "answers.csv").exists()

    def test_non_actionable_answer_not_written(self, storage, fixtures, tmp_path):
        import copy
        messages, results = fixtures
        non_actionable = copy.deepcopy(results["msg_003"])
        non_actionable.answer_analysis.is_actionable = False
        storage.store(non_actionable, messages["msg_003"])
        assert not (tmp_path / "answers.csv").exists()

    def test_chat_produces_no_file(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_005"], messages["msg_005"])
        assert not (tmp_path / "questions.csv").exists()
        assert not (tmp_path / "answers.csv").exists()

    def test_announcement_produces_no_file(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_006"], messages["msg_006"])
        assert not (tmp_path / "questions.csv").exists()
        assert not (tmp_path / "answers.csv").exists()


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_questions_csv_has_correct_headers(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        rows = read_csv(str(tmp_path / "questions.csv"))
        assert list(rows[0].keys()) == QUESTION_HEADERS

    def test_answers_csv_has_correct_headers(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])  # store question first
        storage.store(results["msg_003"], messages["msg_003"])
        rows = read_csv(str(tmp_path / "answers.csv"))
        assert list(rows[0].keys()) == ANSWER_HEADERS

    def test_headers_written_only_once_on_multiple_writes(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_010"], messages["msg_010"])
        rows = read_csv(str(tmp_path / "questions.csv"))
        # If headers were duplicated they'd show up as a data row
        assert len(rows) == 2


# ---------------------------------------------------------------------------
# questions.csv row content
# ---------------------------------------------------------------------------

class TestQuestionRow:
    def test_question_id_is_message_id(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        row = read_csv(str(tmp_path / "questions.csv"))[0]
        assert row["question_id"] == "msg_001"

    def test_message_text_from_original_message(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        row = read_csv(str(tmp_path / "questions.csv"))[0]
        assert row["message_text"] == messages["msg_001"].text

    def test_is_service_valid_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        row = read_csv(str(tmp_path / "questions.csv"))[0]
        assert row["is_service_valid"] == "True"

    def test_confidence_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        row = read_csv(str(tmp_path / "questions.csv"))[0]
        assert row["confidence"] == "HIGH"

    def test_needs_review_true_written_for_low_confidence(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_002"], messages["msg_002"])
        row = read_csv(str(tmp_path / "questions.csv"))[0]
        assert row["needs_review"] == "True"


# ---------------------------------------------------------------------------
# answers.csv row content
# ---------------------------------------------------------------------------

class TestAnswerRow:
    def test_question_id_linked_correctly(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["question_id"] == "msg_001"

    def test_question_text_populated_from_parent(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["question_text"] == messages["msg_001"].text

    def test_message_text_from_original_message(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["message"] == messages["msg_003"].text

    def test_phone_number_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["phone"] == "+971501234567"

    def test_orphan_answer_has_empty_question_id(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_009"], messages["msg_009"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["question_id"] == ""   # None written as empty string by csv.DictWriter

    def test_name_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["name"] == "Ahmed Plumbing"

    def test_business_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["business"] == "Ahmed Plumbing"

    def test_answer_confidence_written(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        row = read_csv(str(tmp_path / "answers.csv"))[0]
        assert row["confidence"] == "HIGH"


# ---------------------------------------------------------------------------
# Append behaviour
# ---------------------------------------------------------------------------

class TestAppend:
    def test_multiple_questions_appended(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_002"], messages["msg_002"])
        storage.store(results["msg_010"], messages["msg_010"])
        rows = read_csv(str(tmp_path / "questions.csv"))
        assert len(rows) == 3

    def test_multiple_answers_appended(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        for mid in ["msg_003", "msg_004", "msg_009"]:
            storage.store(results[mid], messages[mid])
        rows = read_csv(str(tmp_path / "answers.csv"))
        assert len(rows) == 3

    def test_question_and_answer_go_to_separate_files(self, storage, fixtures, tmp_path):
        messages, results = fixtures
        storage.store(results["msg_001"], messages["msg_001"])
        storage.store(results["msg_003"], messages["msg_003"])
        q_rows = read_csv(str(tmp_path / "questions.csv"))
        a_rows = read_csv(str(tmp_path / "answers.csv"))
        assert len(q_rows) == 1
        assert len(a_rows) == 1
