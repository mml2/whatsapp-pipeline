import csv
import os
from pathlib import Path

from pipeline.logger import log
from pipeline.models import AnalysisResult, MessageType, WhatsAppMessage

QUESTION_HEADERS = [
    "question_id", "timestamp", "sender", "message_text",
    "is_service_valid", "confidence", "needs_review",
]

ANSWER_HEADERS = [
    "timestamp", "question_text", "message", "phone", "name", "business",
    "confidence", "question_id",
]


class Storage:
    """
    Appends analysis results to questions.csv and answers.csv.

    QUESTION  → questions.csv
    ANSWER    → answers.csv
    CHAT      → skipped (no write)
    ANNOUNCEMENT → skipped (no write)

    Headers are written automatically on the first write to each file.
    Both the AnalysisResult and the original WhatsAppMessage are required
    because message_text lives on the message, not on the analysis result.
    """

    def __init__(self, questions_path: str, answers_path: str) -> None:
        self._questions_path = questions_path
        self._answers_path = answers_path
        os.makedirs(Path(questions_path).parent, exist_ok=True)
        os.makedirs(Path(answers_path).parent, exist_ok=True)
        self._question_texts: dict[str, str] = {}   # question_id → message_text cache

    def store(self, result: AnalysisResult, msg: WhatsAppMessage) -> None:
        if result.message_type == MessageType.QUESTION:
            self._write_question(result, msg)
        elif result.message_type == MessageType.ANSWER:
            if result.answer_analysis.is_actionable:
                self._write_answer(result, msg)
            else:
                log("STORE", "SKIP", message_id=result.message_id,
                    type="ANSWER", reason="not_actionable")
        else:
            log("STORE", "SKIP", message_id=result.message_id, type=result.message_type.value)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_question(self, result: AnalysisResult, msg: WhatsAppMessage) -> None:
        qa = result.question_analysis
        row = {
            "question_id":    result.message_id,
            "timestamp":      result.timestamp,
            "sender":         result.sender,
            "message_text":   msg.text,
            "is_service_valid": qa.is_service_valid,
            "confidence":     qa.confidence.value if qa.confidence else None,
            "needs_review":   qa.needs_review,
        }
        self._question_texts[result.message_id] = msg.text or ""
        self._append(self._questions_path, QUESTION_HEADERS, row)
        log("STORE", "OK", question_id=result.message_id, needs_review=qa.needs_review)

    def _write_answer(self, result: AnalysisResult, msg: WhatsAppMessage) -> None:
        aa = result.answer_analysis
        contact = aa.contact or {}
        phone      = contact.phone      if hasattr(contact, "phone")      else contact.get("phone")
        name       = contact.name       if hasattr(contact, "name")       else contact.get("name")
        business   = contact.business   if hasattr(contact, "business")   else contact.get("business")
        source     = contact.source_type if hasattr(contact, "source_type") else contact.get("source_type")

        row = {
            "timestamp":     result.timestamp,
            "question_text": self._question_texts.get(aa.parent_question_id or "", ""),
            "message":       msg.text,
            "phone":         phone,
            "name":          name,
            "business":      business,
            "confidence":    aa.confidence.value if aa.confidence else None,
            "question_id":   aa.parent_question_id,
        }
        self._append(self._answers_path, ANSWER_HEADERS, row)
        log(
            "STORE", "OK",
            answer_id=result.message_id,
            linked_to=aa.parent_question_id,
            needs_review=aa.needs_review,
        )

    def _append(self, path: str, headers: list, row: dict) -> None:
        file_exists = Path(path).exists()
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
