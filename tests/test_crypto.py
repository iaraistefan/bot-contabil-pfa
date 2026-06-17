"""
#2-A — criptare secrete la rest (Fernet, app/domain/crypto.py).

SECURITATE: secretul NICIODATĂ în clar (doar token Fernet); cheia DOAR în env;
helper-ul nu loghează plaintext. Testăm round-trip + token≠plaintext + degradare
grațioasă fără cheie + decriptare cu cheie greșită eșuează.

Cheia de test (dummy) e setată în conftest.py (CONTAI_ENC_KEY).
"""

import pytest
from cryptography.fernet import Fernet

from config import settings
from app.domain import crypto


def test_round_trip():
    for plain in ["secret-bolt-123", "", "căsuță ăîâșț 🚗", "a"*500, "x"]:
        assert crypto.decrypt(crypto.encrypt(plain)) == plain


def test_token_nu_contine_plaintextul():
    # CRITIC: tokenul stocat în DB NU trebuie să conțină secretul (nici ca substring).
    secret = "BOLT_SUPER_SECRET_value_42"
    token = crypto.encrypt(secret)
    assert secret not in token
    assert token != secret
    # token Fernet e base64 (gAAAA...) — nu plaintext
    assert token.startswith("gAAAA")


def test_is_available_cu_cheie():
    assert crypto.is_available() is True


def test_fara_cheie_degradare_gratioasa(monkeypatch):
    monkeypatch.setattr(settings, "contai_enc_key", None)
    assert crypto.is_available() is False
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")
    with pytest.raises(RuntimeError):
        crypto.decrypt("gAAAAblabla")


def test_cheie_invalida_degradare_gratioasa(monkeypatch):
    monkeypatch.setattr(settings, "contai_enc_key", "nu-e-o-cheie-fernet-valida")
    assert crypto.is_available() is False
    with pytest.raises(RuntimeError):
        crypto.encrypt("x")


def test_decriptare_cu_cheie_gresita_esueaza(monkeypatch):
    token = crypto.encrypt("secret")            # cu cheia din conftest
    monkeypatch.setattr(settings, "contai_enc_key", Fernet.generate_key().decode())  # altă cheie
    with pytest.raises(RuntimeError):
        crypto.decrypt(token)                   # token vechi + cheie nouă → eroare clară
