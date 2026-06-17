"""
E2E Ghid de obligații (sub-pași 1+2+3) — fluxul COMPLET cap-coadă.

Scenariu: PFA ridesharing Bolt+Uber, profil COMPLET → deschide /ghid (Telegram) +
pagina web → vede DOAR obligațiile LUI (D100/D212/D207/D301/D390/D700, fără D101/D300)
→ tap pe D100 → cardul pedagogic complet (ce_e/de_ce/penalty). + toggle „vezi toate" → 9.

Leagă: profil → filtrare (sub-pas 3) → afișare grupată (sub-pas 2) → card (sub-pas 1),
pe AMBELE surfețe, din aceeași sursă (DEFINITII_OBLIGATII).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.fiscal_calendar import DEFINITII_OBLIGATII, ghid_grupuri
from app.services import ghid_ui
from app.services.ghid_ui import ghid_codes_for_user
from app.models import User

# obligațiile unui PFA ridesharing (Bolt+Uber), neplătitor TVA cu cod special
ALE_MELE = {"D100_634", "D212", "D207", "D301", "D390", "D700"}
NU_ALE_MELE = {"D101", "D300"}


def _user(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'e2eghid.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=42, onboarding_completed=True, activity_code="ridesharing",
             firma_forma_juridica="PFA", regim_tva="SPECIAL_INTRACOM",
             regim_nerezident_bolt="BOLT_CU_CRF", regim_nerezident_uber="UBER_CU_CRF")
    s.add(u); s.commit(); uid = u.id; s.close()
    return S, uid


@pytest.mark.asyncio
async def test_e2e_ghid_telegram_personalizat_apoi_card(tmp_path):
    S, uid = _user(tmp_path)

    # PROFIL → FILTRARE: doar obligațiile lui
    s = S()
    codes, personalizat, nudge = ghid_codes_for_user(s, uid)
    s.close()
    assert personalizat is True and nudge is False
    assert ALE_MELE.issubset(set(codes))
    assert not (NU_ALE_MELE & set(codes))          # D101/D300 EXCLUSE

    # AFIȘARE: lista grupată pe frecvență, cu toggle „vezi toate"
    kb = ghid_ui._kb_lista(codes, personalizat=True)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "ghid|all" in cbs                        # toggle
    views = {c.split("|")[2] for c in cbs if c.startswith("ghid|view|")}
    assert views == ALE_MELE                        # exact obligațiile lui, navigabile
    grupuri = {g["cheie"] for g in ghid_grupuri(codes)}
    assert grupuri == {"lunar", "anual", "o_data"}  # D700 o-dată, D212/D207 anual, restul lunar

    # CARD: tap pe D100 → cardul pedagogic complet (din registru)
    class _Q:
        def __init__(self): self.text = None
        async def edit_message_text(self, text, **kw): self.text = text
    q = _Q()
    await ghid_ui.handle_callback(SimpleNamespace(callback_query=q), SimpleNamespace(),
                                  ["ghid", "view", "D100_634"])
    d = DEFINITII_OBLIGATII["D100_634"]
    assert d.ce_e in q.text and d.de_ce in q.text and d.penalty_info in q.text
    assert "Uber" in q.text and "Bolt" in q.text    # ambele platforme în „de ce TU"


def test_e2e_ghid_web_personalizat_si_toggle(monkeypatch, tmp_path):
    from app.http import app as webapp
    S, uid = _user(tmp_path)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    client = webapp.flask_app.test_client()

    # DEFAULT = personalizat: doar ale lui
    d = client.get("/api/v1/ghid").get_json()
    assert d["personalizat"] is True and d["nudge"] is False
    coduri = [o["cod"] for g in d["grupuri"] for o in g["obligatii"]]
    assert "D100 poz. 634" in coduri
    assert "D101" not in coduri and "D300" not in coduri
    # card complet pe D100 (sursă unică: text din registru)
    d100 = next(o for g in d["grupuri"] for o in g["obligatii"] if o["cod"] == "D100 poz. 634")
    assert d100["de_ce"] == DEFINITII_OBLIGATII["D100_634"].de_ce
    assert d100["penalty_info"] and d100["ce_e"]

    # TOGGLE „vezi toate" → toate 9
    da = client.get("/api/v1/ghid?all=1").get_json()
    assert da["personalizat"] is False
    coduri_all = [o["cod"] for g in da["grupuri"] for o in g["obligatii"]]
    assert len(coduri_all) == 8 and "D101" in coduri_all and "D300" in coduri_all
