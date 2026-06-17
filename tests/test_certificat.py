"""
Certificat de rezidență Bolt — secțiune web + /certificat Telegram + reminder anual.

SURSĂ UNICĂ: app.services.certificat (nume fișier dinamic pe an + text + mesaje reminder).
ONESTITATE: document COMUN Bolt, NU personalizat.
"""

import db
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import certificat
from app.services import scheduler
from app.domain.fiscal_calendar import DEFINITII_OBLIGATII
from app.models import User


# ════════════════════════════════════════════════════════
# 1. Nume fișier DINAMIC pe an
# ════════════════════════════════════════════════════════

def test_filename_dinamic_pe_an():
    assert certificat.filename(2026) == "certificat_bolt_romania_2026.pdf"
    assert certificat.filename(2027) == "certificat_bolt_romania_2027.pdf"
    assert certificat.url(2026) == "/static/certificat_bolt_romania_2026.pdf"


def test_exists_false_fara_fisier():
    # an improbabil → fișierul nu există → degradare grațioasă (link absent)
    assert certificat.exists(3999) is False


# ════════════════════════════════════════════════════════
# 2. Mesaje reminder — gate cu MESAJE DIFERITE
# ════════════════════════════════════════════════════════

def test_reminder_cu_crf_reinnoire():
    m = certificat.mesaj_reminder(2027, "BOLT_CU_CRF")
    assert m and "Reînnoiește" in m and "2%" in m and "2027" in m
    assert "16%" not in m                       # reînnoire, nu optimizare


def test_reminder_fara_crf_optimizare():
    m = certificat.mesaj_reminder(2027, "BOLT_FARA_CRF")
    assert m and "16%" in m and "2%" in m
    assert "14%" in m or "Economise" in m       # mesaj de optimizare (economie)


def test_reminder_alti_useri_none():
    assert certificat.mesaj_reminder(2027, None) is None
    assert certificat.mesaj_reminder(2027, "UBER_CU_CRF") is None
    assert certificat.mesaj_reminder(2027, "") is None


# ════════════════════════════════════════════════════════
# 3. check_certificate_renewal — gate corect pe useri reali
# ════════════════════════════════════════════════════════

def _db(tmp_path, users):
    eng = create_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    for i, regim in enumerate(users, start=1):
        s.add(User(telegram_id=100 + i, regim_nerezident_bolt=regim))
    s.commit(); s.close()
    return S


def test_reminder_gate_pe_regim(tmp_path, monkeypatch):
    S = _db(tmp_path, ["BOLT_CU_CRF", "BOLT_FARA_CRF", "UBER_CU_CRF", None])
    monkeypatch.setattr(db, "get_session", lambda: S())
    sent = []
    monkeypatch.setattr(scheduler, "_send_telegram_message",
                        lambda token, tg_id, msg: sent.append((tg_id, msg)))

    scheduler.check_certificate_renewal("tok")

    # DOAR cei 2 Bolt primesc; Uber + nesetat → nimic
    assert len(sent) == 2
    by_tg = {tg: msg for tg, msg in sent}
    assert "Reînnoiește" in by_tg[101]          # BOLT_CU_CRF → reînnoire
    assert ("14%" in by_tg[102] or "Economise" in by_tg[102])  # BOLT_FARA_CRF → optimizare
    assert 103 not in by_tg and 104 not in by_tg  # Uber-only / nesetat → fără reminder


def test_reminder_fallback_camp_deprecat(tmp_path, monkeypatch):
    # user pre-migrare: regim pe câmpul vechi → tot primește reminder (fallback)
    eng = create_engine(f"sqlite:///{(tmp_path / 'd.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); s.add(User(telegram_id=200, regim_nerezident="BOLT_CU_CRF")); s.commit(); s.close()
    monkeypatch.setattr(db, "get_session", lambda: S())
    sent = []
    monkeypatch.setattr(scheduler, "_send_telegram_message",
                        lambda token, tg_id, msg: sent.append((tg_id, msg)))
    scheduler.check_certificate_renewal("tok")
    assert len(sent) == 1 and "Reînnoiește" in sent[0][1]


# ════════════════════════════════════════════════════════
# 4. Web /api/v1/certificat — sursă unică
# ════════════════════════════════════════════════════════

def test_endpoint_certificat(monkeypatch):
    from app.http import app as webapp
    monkeypatch.setattr(webapp, "_require_user", lambda: (1, None))
    d = webapp.flask_app.test_client().get("/api/v1/certificat").get_json()
    assert d["an"] == certificat.current_year()
    assert d["url"] == certificat.url(d["an"])
    assert d["intro"] == certificat.INTRO            # sursă unică (nu duplicat)
    assert d["ghid_obtinere"] == certificat.GHID_OBTINERE
    assert isinstance(d["disponibil"], bool)


# ════════════════════════════════════════════════════════
# 5. Cross-ref în Ghid D100 (surfațat pe ambele surfețe ghid)
# ════════════════════════════════════════════════════════

def test_ghid_d100_trimite_la_certificat():
    assert "/certificat" in DEFINITII_OBLIGATII["D100_634"].cum_depun


# ════════════════════════════════════════════════════════
# 6. Onestitate — nicăieri „certificatul TĂU"
# ════════════════════════════════════════════════════════

def test_onestitate_document_comun():
    blob = (certificat.INTRO + certificat.GHID_OBTINERE
            + (certificat.mesaj_reminder(2027, "BOLT_CU_CRF") or "")
            + (certificat.mesaj_reminder(2027, "BOLT_FARA_CRF") or "")).lower()
    assert "certificatul tău" not in blob and "certificatul tau" not in blob
    assert "comun" in certificat.INTRO.lower()       # spune explicit că e comun
