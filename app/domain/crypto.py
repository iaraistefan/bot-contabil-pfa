"""
Criptare secrete la rest (Fernet) — #2-A Bolt sync per-user.

Folosit pentru a NU stoca niciodată în clar secrete sensibile (ex. Bolt API
client_secret) în baza de date. Stocăm DOAR token-ul Fernet; decriptăm doar la
momentul folosirii (apel API), în memorie.

Cheia: `settings.contai_enc_key` (env `CONTAI_ENC_KEY`, base64 Fernet, 32 bytes).
DOAR în env (Render secret) — NICIODATĂ în repo/cod/loguri. Lipsă/invalidă →
`is_available()` False → apelantul (fluxul de conectare Bolt, #2-B) refuză grațios.

Generarea cheii (owner, o dată):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

REGULĂ: acest modul NU loghează NICIODATĂ plaintext-ul sau secretul.
"""

import logging
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import settings

logger = logging.getLogger(__name__)


def _fernet() -> Optional[Fernet]:
    """Instanță Fernet din cheia env, sau None dacă lipsește/invalidă. NU loghează cheia."""
    key = (settings.contai_enc_key or "").strip()
    if not key:
        return None
    try:
        return Fernet(key.encode("utf-8"))
    except Exception:
        # cheie prezentă dar invalidă (format greșit) → tratăm ca indisponibilă
        logger.error("CONTAI_ENC_KEY prezentă dar invalidă (format Fernet greșit).")
        return None


def is_available() -> bool:
    """True dacă criptarea e utilizabilă (cheie setată + validă)."""
    return _fernet() is not None


def encrypt(plaintext: str) -> str:
    """Criptează un text → token Fernet (str). Ridică RuntimeError dacă cheia lipsește."""
    f = _fernet()
    if f is None:
        raise RuntimeError("Criptare indisponibilă: CONTAI_ENC_KEY nesetată/invalidă.")
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decriptează un token Fernet → plaintext. Ridică RuntimeError la cheie/ token invalid."""
    f = _fernet()
    if f is None:
        raise RuntimeError("Decriptare indisponibilă: CONTAI_ENC_KEY nesetată/invalidă.")
    try:
        return f.decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        # token corupt SAU cheie greșită (ex. cheia a fost rotită) → eroare clară,
        # FĂRĂ a expune token-ul în mesaj/loguri.
        raise RuntimeError("Token invalid pentru cheia curentă (corupt sau cheie schimbată).")
