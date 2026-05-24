"""
Wrapper subtire peste OpenAI pentru extragere documente.

Suporta activitati plug-in: daca primeste user_id, prompt-ul AI va
include hint-uri specifice activitatii utilizatorului.

FIX EXTRACTOR (audit):
- detail="high" pe imagini -> modelul citeste text mic + scris de mana
- max_tokens marit (800 -> 3000) -> facturi complexe nu mai sunt taiate
- retry pe erori tranzitorii OpenAI (3 incercari cu backoff)
"""

import base64
import json
import logging
import time
from datetime import datetime
from typing import Optional

from openai import OpenAI

from config import settings
from app.ai.prompts import PROMPT_VERSION, build_extraction_system_prompt
from app.ai.schemas import validate_items, ValidationReport

logger = logging.getLogger(__name__)

_client = OpenAI(api_key=settings.openai_api_key)

# Numar de incercari pentru apelul OpenAI (erori tranzitorii: rate limit, timeout)
_MAX_RETRIES = 3
# Token-uri suficiente pentru facturi complexe cu multe campuri
_MAX_TOKENS = 3000


def _clean_json_response(text: str) -> str:
    """Elimina markdown fences ```json ... ``` din raspuns."""
    return text.replace("```json", "").replace("```", "").strip()


def _get_activity_hints(user_id: Optional[int]) -> str:
    """Returneaza hint-urile specifice activitatii utilizatorului."""
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


def _call_openai_with_retry(messages: list) -> str:
    """
    Apeleaza OpenAI cu retry pe erori tranzitorii.
    Returneaza raw_response sau arunca exceptia ultima daca toate esueaza.
    """
    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = _client.chat.completions.create(
                model=settings.openai_model,
                messages=messages,
                max_tokens=_MAX_TOKENS,
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            last_error = e
            logger.warning(
                f"OpenAI attempt {attempt}/{_MAX_RETRIES} failed: {e}"
            )
            if attempt < _MAX_RETRIES:
                # Backoff progresiv: 1.5s, 3s
                time.sleep(1.5 * attempt)

    # Toate incercarile au esuat
    raise last_error if last_error else RuntimeError("OpenAI call failed")


def extract_document(
    user_input: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    today_str: Optional[str] = None,
    user_id: Optional[int] = None,
) -> dict:
    """
    Ruleaza extragerea pe text si/sau imagine, apoi valideaza.

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

    # Hint-uri specifice activitatii utilizatorului
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
            "image_url": {
                "url": f"data:image/jpeg;base64,{image_b64}",
                # detail="high" -> OpenAI proceseaza imaginea la rezolutie mare,
                # esential pentru text mic de pe bonuri si scris de mana
                "detail": "high",
            },
        })

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    try:
        raw_response = _call_openai_with_retry(messages)
    except Exception as e:
        logger.error(f"OpenAI call failed after {_MAX_RETRIES} retries: {e}")
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
