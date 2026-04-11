from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    QUESTION = "QUESTION"
    ANNOUNCEMENT = "ANNOUNCEMENT"
    CHAT = "CHAT"
    ANSWER = "ANSWER"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class LinkMethod(str, Enum):
    QUOTED = "quoted"
    TEMPORAL = "temporal"


class SourceType(str, Enum):
    TEXT = "text"
    VCARD = "vcard"
    IMAGE = "image"


class MediaType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VCARD = "vcard"
    AUDIO = "audio"


# ---------------------------------------------------------------------------
# RawMessage — column names as stored by the Go bridge in SQLite
# ---------------------------------------------------------------------------

class RawMessage(BaseModel):
    id: str
    timestamp: str
    sender: str
    content: Optional[str]
    chat_jid: str
    chat_name: Optional[str]
    media_type: Optional[str]
    quoted_message_id: Optional[str]
    is_from_me: bool


# ---------------------------------------------------------------------------
# WhatsAppMessage — matches input_format in SYSTEM_PROMPT.md exactly
# ---------------------------------------------------------------------------

class WhatsAppMessage(BaseModel):
    message_id: str
    timestamp: str
    sender: str
    group: str
    text: Optional[str]
    media_type: Optional[str]
    quoted_message_id: Optional[str]
    local_media_path: Optional[str] = None   # populated by media_handler after download


# ---------------------------------------------------------------------------
# AnalysisResult — matches output_format in SYSTEM_PROMPT.md exactly
# ---------------------------------------------------------------------------

class Signals(BaseModel):
    service_noun: bool
    request_verb: bool
    contact_language: bool
    location_anchor: bool
    price_or_availability: bool


class QuestionAnalysis(BaseModel):
    is_service_valid: Optional[bool]
    signals: Optional[Signals]
    confidence: Optional[Confidence]
    needs_review: bool


class Contact(BaseModel):
    phone: Optional[str]
    name: Optional[str]
    business: Optional[str]
    source_type: Optional[SourceType]


class AnswerAnalysis(BaseModel):
    is_actionable: bool
    confidence: Optional[Confidence]
    parent_question_id: Optional[str]
    link_method: Optional[LinkMethod]
    contact: Optional[Contact]
    needs_review: bool


class AnalysisResult(BaseModel):
    message_id: str
    timestamp: str
    sender: str
    message_type: MessageType
    question_analysis: Optional[QuestionAnalysis]
    answer_analysis: Optional[AnswerAnalysis]
