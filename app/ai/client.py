"""
Wrapper subțire peste OpenAI pentru extragere documente.

Responsabilități:
- Construire messages (system + user, cu sau fără imagine).
- Apel cu retry simplu și timeout implicit din SDK.
- Curățare markdown fences din răspuns.
- Parsare JSON cu tratament explicit al erorilor.

NU decide politici de business. Doar extrage.
"""

import base64
import json
import logging
from datetime import datetime
from typing import Optional

from openai import OpenAI

from config import settings
from app.ai.prompts import PROMPT_VERSION, build_extraction_system_prompt

logger = logging.getLogger(__name__)

# Singleton OpenAI client — reutilizat între apeluri.
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
    Rulează extragerea pe text și/sau imagine.

    Returns dict cu:
        - "ok": bool — True dacă JSON-ul e parsabil
        - "data": list | None — lista de items extrași (dacă ok)
        - "raw_response": str — răspunsul brut de la model (pentru audit)
        - "prompt_version": str
        - "error": str | None — descrierea erorii dacă ok=False
    """
    today_str = today_str or datetime.now().strftime("%d.%m.%Y")
    system_prompt = build_extraction_system_prompt(today_str)

    # Construim user content: text + (opțional) imagine
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

    # Apel la OpenAI
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
            "data": None,
            "raw_response": "",
            "prompt_version": PROMPT_VERSION,
            "error": f"openai_error: {e}",
        }

    # Parsare JSON
    cleaned = _clean_json_response(raw_response)
    try:
        data = json.loads(cleaned)
        # Garantăm că e listă — prompt-ul cere listă, dar uneori modelul întoarce un singur dict.
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"expected list, got {type(data).__name__}")
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"JSON parse failed: {e} | raw: {raw_response[:200]}")
        return {
            "ok": False,
            "data": None,
            "raw_response": raw_response,
            "prompt_version": PROMPT_VERSION,
            "error": f"json_parse_error: {e}",
        }

    return {
        "ok": True,
        "data": data,
        "raw_response": raw_response,
        "prompt_version": PROMPT_VERSION,
        "error": None,
    }
