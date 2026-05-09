"""
Wrapper subțire peste OpenAI pentru extragere documente.

Suportă acum activități plug-in: dacă primește user_id, prompt-ul AI va
include hint-uri specifice activității utilizatorului (ex: pentru Ridesharing,
AI-ul știe că "Lukoil" → categoria 'fuel').
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


def _get_activity_hints(user_id: Optional[int]) -> str:
    """
    Returnează hint-urile specifice activității utilizatorului.
    Dacă user_id e None sau nu are activitate, returnează șir gol.

    Hint-urile sunt apendizate la promptul de extracție pentru a ajuta
    AI-ul să clasifice corect cheltuielile (ex: Lukoil → fuel pentru Ridesharing).
    """
    if user_id is None:
        return ""

    try:
        from app.activities import get_activity_for_user
        activity_cls = get_activity_for_user(user_id)
        hints = activity_cls.ai_prompt_hints()
        if hints:
            logger.debug(
                f"Loaded AI hints for user_id={user_id} "
                f"activity={activity_cls.code}"
            )
        return hints or ""
    except Exception as e:
        logger.warning(f"Could not load activity hints for user_id={user_id}: {e}")
        return ""


def extract_document(
    user_input: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    today_str: Optional[str] = None,
    user_id: Optional[int] = None,
) -> dict:
    """
    Rulează extragerea pe text și/sau imagine, apoi validează.

    Args:
        user_input: textul scris de utilizator
        image_bytes: bytes-urile imaginii (poză bon/factură)
        today_str: data de azi (default: now)
        user_id: ID intern user — dacă e setat, AI-ul primește hint-uri
                 specifice activității utilizatorului

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

    # === Adăugăm hint-uri specifice activității utilizatorului ===
    activity_hints = _get_activity_hints(user_id)
    if activity_hints:
        system_prompt = f"{system_prompt}\n\n{activity_hints}"

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
