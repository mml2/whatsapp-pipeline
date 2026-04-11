import base64
import json
from pathlib import Path
from typing import List

from pydantic import ValidationError

from pipeline.logger import log
from pipeline.models import AnalysisResult, WhatsAppMessage

MAX_TOKENS = 1024

_IMAGE_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _parse_vcard(path: str) -> str:
    """
    Parse a .vcf file and return a compact text representation suitable for
    injecting into the LLM prompt.  Extracts FN, TEL, and ORG lines only.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    name = org = None
    phones: list[str] = []

    for line in text.splitlines():
        line = line.strip()
        upper = line.upper()
        if upper.startswith("FN:"):
            name = line[3:].strip()
        elif upper.startswith("ORG:"):
            org = line[4:].strip()
        elif upper.startswith("TEL"):
            # TEL:+971501234567  or  TEL;TYPE=CELL:+971501234567
            if ":" in line:
                phones.append(line.split(":", 1)[1].strip())

    parts: list[str] = []
    if name:
        parts.append(f"Name: {name}")
    if phones:
        parts.append(f"Phone: {', '.join(phones)}")
    if org:
        parts.append(f"Organization: {org}")

    return "[VCard] " + " | ".join(parts) if parts else "[VCard attached - no readable fields]"


class AnalysisError(Exception):
    """Raised when the LLM returns unparseable or schema-invalid output."""


class Analyzer:
    """
    Sends a WhatsApp message to an LLM for classification and contact extraction.

    Supports both Anthropic (Claude) and OpenAI (GPT) via the provider setting
    in config.yaml:

        anthropic:
          provider: "anthropic"
          model: "claude-sonnet-4-6"
          api_key_env: "ANTHROPIC_API_KEY"

        anthropic:
          provider: "openai"
          model: "gpt-4o-mini"
          api_key_env: "OPENAI_API_KEY"

    Loads SYSTEM_PROMPT.md once at startup. For each message, builds a user
    turn containing the 120-min context window followed by the current message,
    calls the API, and validates the JSON response against AnalysisResult.
    """

    def __init__(self, system_prompt_path: str, model: str, api_key: str, provider: str = "anthropic") -> None:
        self._system_prompt = Path(system_prompt_path).read_text()
        self._model = model
        self._provider = provider.lower()
        self._client = self._build_client(api_key)

    def _build_client(self, api_key: str):
        if self._provider == "anthropic":
            import anthropic
            return anthropic.Anthropic(api_key=api_key)
        elif self._provider == "openai":
            import openai
            return openai.OpenAI(api_key=api_key)
        else:
            raise ValueError(f"Unsupported provider: {self._provider}. Use 'anthropic' or 'openai'.")

    def analyze(
        self, msg: WhatsAppMessage, context: List[WhatsAppMessage]
    ) -> AnalysisResult:
        """
        Analyze a single message and return a validated AnalysisResult.

        For vcard messages with a downloaded file, the contact card is parsed
        and injected as text before the LLM call.
        For image messages with a downloaded file, a multimodal (vision) API
        call is made — the configured model must support vision.

        Raises AnalysisError if the LLM returns invalid JSON or output that
        does not conform to the AnalysisResult schema.
        """
        enriched_msg = self._enrich_vcard(msg)

        use_vision = (
            msg.media_type == "image"
            and msg.local_media_path is not None
        )

        if use_vision:
            text_content = self._build_user_content(enriched_msg, context)
            raw = self._call_with_image(msg.message_id, text_content, msg.local_media_path)
        else:
            user_content = self._build_user_content(enriched_msg, context)
            if self._provider == "anthropic":
                raw = self._call_anthropic(user_content)
            else:
                raw = self._call_openai(user_content)

        result = self._parse(msg.message_id, raw)

        log(
            "ANALYZE", "OK",
            message_id=msg.message_id,
            type=result.message_type.value,
        )
        return result

    # ------------------------------------------------------------------
    # Provider-specific API calls
    # ------------------------------------------------------------------

    def _call_anthropic(self, user_content: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=self._system_prompt,
            messages=[{"role": "user", "content": user_content}],
        )
        return response.content[0].text

    def _call_openai(self, user_content: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user",   "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    def _call_with_image(self, message_id: str, text_content: str, image_path: str) -> str:
        """Make a multimodal (vision) API call with text + image."""
        try:
            img_bytes = Path(image_path).read_bytes()
        except OSError as exc:
            log("ANALYZE", "WARN", message_id=message_id,
                detail=f"image read failed, falling back to text-only: {exc}")
            if self._provider == "anthropic":
                return self._call_anthropic(text_content)
            return self._call_openai(text_content)

        b64 = base64.b64encode(img_bytes).decode()
        mime = _IMAGE_MIME.get(Path(image_path).suffix.lower(), "image/jpeg")

        if self._provider == "anthropic":
            return self._call_anthropic_vision(text_content, b64, mime)
        return self._call_openai_vision(text_content, b64, mime)

    def _call_anthropic_vision(self, text_content: str, b64: str, mime: str) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            system=self._system_prompt,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": mime, "data": b64},
                    },
                    {"type": "text", "text": text_content},
                ],
            }],
        )
        return response.content[0].text

    def _call_openai_vision(self, text_content: str, b64: str, mime: str) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_content},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                    ],
                },
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _enrich_vcard(self, msg: WhatsAppMessage) -> WhatsAppMessage:
        """
        For vcard messages with a downloaded file, parse the .vcf and inject
        the contact card as the message text so the LLM can see it.
        """
        if msg.media_type != "vcard" or not msg.local_media_path:
            return msg
        try:
            vcard_text = _parse_vcard(msg.local_media_path)
            log("ANALYZE", "INFO", message_id=msg.message_id,
                detail=f"vcard parsed: {vcard_text[:80]}")
            return msg.model_copy(update={"text": vcard_text})
        except Exception as exc:
            log("ANALYZE", "WARN", message_id=msg.message_id,
                detail=f"vcard parse failed: {exc}")
            return msg

    def _build_user_content(
        self, msg: WhatsAppMessage, context: List[WhatsAppMessage]
    ) -> str:
        context_payload = [
            json.loads(m.model_dump_json(exclude={"local_media_path"}))
            for m in context
        ]
        message_payload = json.loads(
            msg.model_dump_json(exclude={"local_media_path"})
        )

        return (
            "Recent conversation context:\n"
            + json.dumps(context_payload, indent=2)
            + "\n\nAnalyze this message:\n"
            + json.dumps(message_payload, indent=2)
        )

    def _parse(self, message_id: str, raw: str) -> AnalysisResult:
        """Parse and validate the LLM's raw JSON response."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            log("ANALYZE", "ERROR", message_id=message_id, detail="invalid JSON")
            raise AnalysisError(
                f"LLM returned non-JSON for {message_id}: {exc}"
            ) from exc

        try:
            return AnalysisResult.model_validate(data)
        except ValidationError as exc:
            log("ANALYZE", "ERROR", message_id=message_id, detail="schema mismatch")
            raise AnalysisError(
                f"Schema validation failed for {message_id}: {exc}"
            ) from exc
