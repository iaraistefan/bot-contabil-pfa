"""
Wrapper subțire peste OpenAI pentru extragere documente.
"""

import base64
import json
import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI

from config import settings
from app.ai.prompts import PROMPT_VERSION, build_extraction_system_prompt
from app.ai.schemas import validate_items, ValidationReport

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=settings.openai_api_key)


def _clean_json_response(text: str) -> str:
    """Elimină markdown fences ```json ... ``` din răspuns."""
    return text.replace("```json", "").replace("```", "").strip()


def extract_document(
    user_input: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    today_str: Optional[str] = None,
) -> dict:
    """
    Rulează extragerea pe text și/sau imagine, apoi validează.

    Returns dict cu:
        - "ok": bool
        - "items": list[ExtractionItem]
        - "validation_errors": list[str]
        - "raw_response": str
        - "prompt_version": str
        - "error": str | None
    """
    today_str = today_str or datetime.now().strftime("%d.%m.%Y")
    system_prompt = build_extraction_system_prompt(today_str)

    user_content = [
        {"type": "text", "text": user_input if user_input else "Analizeaza imaginea"}
    ]
    if image_bytes:
        image_b64 = base64.b64encode(image_bytes).decode("utf-8")
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        })

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        response = _client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            max_tokens=800,
            temperature=0.1,
        )
        raw_response = response.choices[0].message.content or ""
    except Exception as e:
        logger.error(f"OpenAI call failed: {e}")
        return {
            "ok": False,
            "items": [],
            "validation_errors": [],
            "raw_response": "",
            "prompt_version": PROMPT_VERSION,
            "error": f"openai_error: {e}",
        }

    cleaned = _clean_json_response(raw_response)
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"expected list, got {type(data).__name__}")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"JSON parse failed: {e} | raw: {raw_response[:200]}")
        return {
            "ok": False,
            "items": [],
            "validation_errors": [],
            "raw_response": raw_response,
            "prompt_version": PROMPT_VERSION,
            "error": f"json_parse_error: {e}",
        }

    report: ValidationReport = validate_items(data)

    if report.has_errors:
        logger.warning(f"Validation errors: {report.errors}")

    return {
        "ok": report.has_valid,
        "items": report.valid_items,
        "validation_errors": report.errors,
        "raw_response": raw_response,
        "prompt_version": PROMPT_VERSION,
        "error": None if report.has_valid else "no_valid_items",
    }
