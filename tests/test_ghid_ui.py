"""
Ghid de obligații — sub-pas Ghid 2 (surfațare) + 3 (personalizare „Ghidul MEU").

SURSĂ UNICĂ: Telegram + web citesc din DEFINITII_OBLIGATII via `ghid_codes_for_user`
(filtru pe profil) + `ghid_grupuri` (grupare pe frecvență). Testăm: grupare, filtrare
personalizată, toggle toate↔ale-mele, și EDGE anti-omisiune (profil incomplet → TOATE,
NU lista săracă care ar ascunde D100/D301/D390).
"""

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.fiscal_calendar import (
    DEFINITII_OBLIGATII, ghid_obligation_codes, ghid_grupuri,
)
from app.services import ghid_ui
from app.services.ghid_ui import ghid_codes_for_user
from app.models import User


# ════════════════════════════════════════════════════════
# 1. Grupare pe frecvență (sub-pas 2)
# ════════════════════════════════════════════════════════

def test_codes_none_intoarce_toate():
    assert set(ghid_obligation_codes()) == set(DEFINITII_OBLIGATII.keys()) and len(ghid_obligation_codes()) == 8


def test_grupare_pe_frecventa():
    grupuri = {g["cheie"]: [d.cod for d in g["obligatii"]] for g in ghid_grupuri()}
    assert grupuri["lunar"] == ["D100 poz. 634", "D301", "D390", "D300"]
    assert "D212" in grupuri["anual"] and "D207" in grupuri["anual"] and "D101" in grupuri["anual"]
    assert grupuri["o_data"] == ["D700"]
    assert [g["cheie"] for g in ghid_grupuri()] == ["lunar", "anual", "o_data"]


def test_grupuri_goale_omise():
    assert [x["cheie"] for x in ghid_grupuri(["D700"])] == ["o_data"]


# ════════════════════════════════════════════════════════
# 2. ghid_codes_for_user — personalizare (sub-pas 3) + EDGE anti-omisiune
# ════════════════════════════════════════════════════════

def _db(tmp_path, **user_kw):
    eng = create_engine(f"sqlite:///{(tmp_path / 'g.db').as_posix()}")
    User.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    u = User(telegram_id=1, **user_kw)
    s.add(u); s.commit()
    return s, u.id


def test_force_all_intoarce_toate(tmp_path):
    s, uid = _db(tmp_path, onboarding_completed=True, activity_code="ridesharing")
    codes, personalizat, nudge = ghid_codes_for_user(s, uid, force_all=True)
    assert set(codes) == set(DEFINITII_OBLIGATII.keys())
    assert personalizat is False and nudge is False
    s.close()


def test_personalizat_ridesharing_fara_d101_d300(tmp_path):
    # PFA ridesharing, neplătitor TVA cu cod special (SPECIAL_INTRACOM).
    s, uid = _db(tmp_path, onboarding_completed=True, activity_code="ridesharing",
                 firma_forma_juridica="PFA", regim_tva="SPECIAL_INTRACOM")
    codes, personalizat, nudge = ghid_codes_for_user(s, uid)
    assert personalizat is True and nudge is False
    # obligațiile LUI:
    for c in ("D100_634", "D212", "D207", "D301", "D390", "D700"):
        assert c in codes, f"{c} lipsește din ghidul personalizat"
    # NU ale altora:
    assert "D101" not in codes        # SRL Normal
    assert "D300" not in codes        # decont TVA plătitori
    s.close()


def test_edge_profil_incomplet_arata_TOT_plus_nudge(tmp_path):
    # TESTUL-CHEIE anti-omisiune (ca fiscal #4): profil neterminat → TOATE, nu lista
    # săracă (D212/D300/D101) care ar ASCUNDE D100/D301/D390/D700 unui „generic".
    s, uid = _db(tmp_path, onboarding_completed=False)   # neterminat, fără activity_code
    codes, personalizat, nudge = ghid_codes_for_user(s, uid)
    assert nudge is True and personalizat is False
    assert set(codes) == set(DEFINITII_OBLIGATII.keys())   # TOATE
    # dovada: obligațiile ridesharing NU sunt ascunse de un profil gol
    for c in ("D100_634", "D301", "D390", "D700"):
        assert c in codes
    s.close()


def test_user_inexistent_arata_tot(tmp_path):
    s, _ = _db(tmp_path, onboarding_completed=True)
    codes, personalizat, nudge = ghid_codes_for_user(s, 9999)   # nu există
    assert nudge is True and set(codes) == set(DEFINITII_OBLIGATII.keys())
    s.close()


# ════════════════════════════════════════════════════════
# 3. Web /api/v1/ghid — default personalizat + ?all toggle
# ════════════════════════════════════════════════════════

def _web(monkeypatch, tmp_path, **user_kw):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'w.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1, **user_kw); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client()


def test_endpoint_default_personalizat(monkeypatch, tmp_path):
    client = _web(monkeypatch, tmp_path, onboarding_completed=True, activity_code="ridesharing",
                  firma_forma_juridica="PFA", regim_tva="SPECIAL_INTRACOM")
    d = client.get("/api/v1/ghid").get_json()
    assert d["personalizat"] is True and d["nudge"] is False
    coduri = [o["cod"] for g in d["grupuri"] for o in g["obligatii"]]
    assert "D100 poz. 634" in coduri and "D101" not in coduri and "D300" not in coduri
    # sursă unică: text din registru
    d100 = next(o for g in d["grupuri"] for o in g["obligatii"] if o["cod"] == "D100 poz. 634")
    assert d100["de_ce"] == DEFINITII_OBLIGATII["D100_634"].de_ce


def test_endpoint_all_intoarce_toate(monkeypatch, tmp_path):
    client = _web(monkeypatch, tmp_path, onboarding_completed=True, activity_code="ridesharing",
                  firma_forma_juridica="PFA", regim_tva="SPECIAL_INTRACOM")
    d = client.get("/api/v1/ghid?all=1").get_json()
    assert d["personalizat"] is False
    coduri = [o["cod"] for g in d["grupuri"] for o in g["obligatii"]]
    assert len(coduri) == 8 and "D101" in coduri and "D300" in coduri


def test_endpoint_profil_incomplet_nudge(monkeypatch, tmp_path):
    client = _web(monkeypatch, tmp_path, onboarding_completed=False)
    d = client.get("/api/v1/ghid").get_json()
    assert d["nudge"] is True
    coduri = [o["cod"] for g in d["grupuri"] for o in g["obligatii"]]
    assert len(coduri) == 8        # toate — anti-omisiune


# ════════════════════════════════════════════════════════
# 4. Telegram — listă (toggle) + card din registru
# ════════════════════════════════════════════════════════

def test_kb_lista_personalizat_are_toggle_vezi_toate():
    kb = ghid_ui._kb_lista(list(DEFINITII_OBLIGATII.keys()), personalizat=True)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "ghid|all" in cbs and "ghid|list" not in cbs       # toggle „vezi toate"
    assert len([c for c in cbs if c.startswith("ghid|view|")]) == 8


def test_kb_lista_toate_are_toggle_doar_ale_mele():
    kb = ghid_ui._kb_lista(list(DEFINITII_OBLIGATII.keys()), personalizat=False)
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "ghid|list" in cbs and "ghid|all" not in cbs       # toggle „doar ale mele"


def test_card_din_registru():
    card = ghid_ui._card("D100_634")
    d = DEFINITII_OBLIGATII["D100_634"]
    assert d.cod in card and d.ce_e in card and d.de_ce in card
    assert "De ce?" in card and "Dacă nu depui" in card


class _Q:
    def __init__(self): self.text = None; self.kb = None
    async def edit_message_text(self, text, **kw):
        self.text = text; self.kb = kw.get("reply_markup")


@pytest.mark.asyncio
async def test_callback_view_card():
    q = _Q()
    upd = SimpleNamespace(callback_query=q)
    await ghid_ui.handle_callback(upd, SimpleNamespace(), ["ghid", "view", "D212"])
    assert "D212" in q.text and DEFINITII_OBLIGATII["D212"].de_ce in q.text
