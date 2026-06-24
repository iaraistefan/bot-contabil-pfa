"""
Validare prospețime auth_date pe Telegram WebApp init_data (fix securitate #3-B).

HMAC-ul e validat corect deja; aici verificăm că un init_data cu auth_date prea
vechi (peste fereastra de 24h) e RESPINS chiar dacă semnătura e validă — altfel un
header X-Telegram-Init-Data capturat rămâne valabil indefinit (sesiune care nu expiră).
"""

import hashlib
import hmac
import json
from urllib.parse import quote

from app.http import app as webapp

BOT_TOKEN = "123456:TEST_TOKEN_pentru_hmac"
MAX_AGE = 86400          # 24h — convenția Telegram
NOW = 1_700_000_000      # timp fix injectabil (mockabil)


def _make_init_data(auth_date, *, bot_token=BOT_TOKEN, user=None,
                    tamper=False, omit_auth_date=False):
    """Construiește un init_data cu HMAC CORECT (calea 'fără signature')."""
    user = user or {"id": 555, "first_name": "Test"}
    pairs = {
        "query_id": "AAExampleQueryId123",
        "user": json.dumps(user, separators=(",", ":")),
    }
    if not omit_auth_date:
        pairs["auth_date"] = str(int(auth_date))
    # data_check_string: "k=v" sortat pe valorile DECODATE, fără hash/signature
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    h = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if tamper:
        h = "0" * len(h)                       # semnătură invalidă
    parts = [f"{k}={quote(str(v), safe='')}" for k, v in pairs.items()]
    parts.append(f"hash={h}")
    return "&".join(parts)


def test_fresh_auth_date_acceptat():
    init = _make_init_data(NOW - 60)           # acum 1 minut
    r = webapp._validate_telegram_init_data(
        init, BOT_TOKEN, max_age_seconds=MAX_AGE, now=NOW)
    assert r is not None
    assert r["user_obj"]["id"] == 555


def test_stale_auth_date_respins_chiar_cu_hmac_valid():
    # cu 1h PESTE fereastra de 24h — semnătura E validă, dar e prea vechi
    init = _make_init_data(NOW - (MAX_AGE + 3600))
    r = webapp._validate_telegram_init_data(
        init, BOT_TOKEN, max_age_seconds=MAX_AGE, now=NOW)
    assert r is None                            # RESPINS (sesiune expirată)


def test_hmac_invalid_respins_regresie():
    # comportamentul existent NU se schimbă: HMAC greșit → respins
    init = _make_init_data(NOW - 60, tamper=True)
    r = webapp._validate_telegram_init_data(
        init, BOT_TOKEN, max_age_seconds=MAX_AGE, now=NOW)
    assert r is None


def test_auth_date_lipsa_respins():
    # HMAC valid dar fără auth_date → nu putem stabili prospețimea → respins
    init = _make_init_data(NOW, omit_auth_date=True)
    r = webapp._validate_telegram_init_data(
        init, BOT_TOKEN, max_age_seconds=MAX_AGE, now=NOW)
    assert r is None


def test_boundary_exact_la_fereastra_acceptat():
    # exact 24h vechime → acceptat (respingem doar strict mai vechi de fereastră)
    init = _make_init_data(NOW - MAX_AGE)
    r = webapp._validate_telegram_init_data(
        init, BOT_TOKEN, max_age_seconds=MAX_AGE, now=NOW)
    assert r is not None
