"""
Ghid de obligații — sub-pas Ghid 2: surfațare (Telegram /ghid + web /api/v1/ghid).

SURSĂ UNICĂ: ambele surfețe citesc din DEFINITII_OBLIGATII (registrul pedagogic,
sub-pas 1). Testăm: gruparea pe frecvență, endpoint-ul web, navigarea Telegram
(listă → card), și că textul NU e duplicat (vine din registru).
"""

from types import SimpleNamespace

import pytest

from app.domain import fiscal_calendar as fc
from app.domain.fiscal_calendar import DEFINITII_OBLIGATII, ghid_obligation_codes, ghid_grupuri
from app.services import ghid_ui


# ════════════════════════════════════════════════════════
# 1. Helper coduri + grupare pe frecvență
# ════════════════════════════════════════════════════════

def test_codes_none_intoarce_toate():
    assert set(ghid_obligation_codes()) == set(DEFINITII_OBLIGATII.keys())
    assert len(ghid_obligation_codes()) == 8


def test_grupare_pe_frecventa():
    grupuri = {g["cheie"]: [d.cod for d in g["obligatii"]] for g in ghid_grupuri()}
    assert grupuri["lunar"] == ["D100 poz. 634", "D301", "D390", "D300"]   # LUNARA
    assert "D212" in grupuri["anual"] and "D207" in grupuri["anual"]        # ANUALA
    assert "D101" in grupuri["anual"]                                       # TRIMESTRIALA → anual
    assert grupuri["o_data"] == ["D700"]                                    # UNICA
    # ordinea grupurilor: lunar → anual → o_data
    assert [g["cheie"] for g in ghid_grupuri()] == ["lunar", "anual", "o_data"]


def test_grupuri_goale_omise():
    g = ghid_grupuri(["D700"])                # doar UNICA
    assert [x["cheie"] for x in g] == ["o_data"]


# ════════════════════════════════════════════════════════
# 2. Web /api/v1/ghid — serializează registrul (nu hardcodat)
# ════════════════════════════════════════════════════════

def test_endpoint_ghid_serializeaza_registrul(monkeypatch):
    from app.http import app as webapp
    monkeypatch.setattr(webapp, "_require_user", lambda: (1, None))
    client = webapp.flask_app.test_client()

    r = client.get("/api/v1/ghid")
    assert r.status_code == 200
    data = r.get_json()
    grupuri = data["grupuri"]
    assert [g["cheie"] for g in grupuri] == ["lunar", "anual", "o_data"]

    # toate cele 8, fiecare cu câmpurile pedagogice
    toate = [o for g in grupuri for o in g["obligatii"]]
    assert len(toate) == 8
    for o in toate:
        for camp in ("ce_e", "cui_se_aplica", "cand", "cum_depun", "de_ce", "penalty_info"):
            assert o[camp], f"{o['cod']}.{camp} gol în endpoint"

    # SURSĂ UNICĂ: textul == cel din registru (nu duplicat/rescris în endpoint)
    d100_api = next(o for o in toate if o["cod"] == "D100 poz. 634")
    assert d100_api["de_ce"] == DEFINITII_OBLIGATII["D100_634"].de_ce


def test_endpoint_ghid_cere_user(monkeypatch):
    from app.http import app as webapp
    monkeypatch.setattr(webapp, "_require_user", lambda: (None, ("err", 401)))
    client = webapp.flask_app.test_client()
    r = client.get("/api/v1/ghid")
    assert r.status_code == 401


# ════════════════════════════════════════════════════════
# 3. Telegram — listă navigabilă + card (sursă unică)
# ════════════════════════════════════════════════════════

def test_kb_lista_grupata_cu_butoane_view():
    kb = ghid_ui._kb_lista()
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    # un buton view per declarație (8) + anteturi noop (3) + închide
    view = [c for c in cbs if c.startswith("ghid|view|")]
    assert len(view) == 8
    assert cbs.count("nav|noop") == 3          # 3 anteturi de grup (lunar/anual/o dată)
    assert "nav|close" in cbs
    # cheile din callback sunt cele reale din registru
    keys = {c.split("|")[2] for c in view}
    assert keys == set(DEFINITII_OBLIGATII.keys())


def test_card_din_registru():
    card = ghid_ui._card("D100_634")
    d = DEFINITII_OBLIGATII["D100_634"]
    assert d.cod in card and d.ce_e in card and d.de_ce in card  # text DIN registru
    assert "De ce?" in card and "Dacă nu depui" in card          # structura profesor


class _Q:
    def __init__(self): self.text = None; self.kb = None
    async def edit_message_text(self, text, **kw):
        self.text = text; self.kb = kw.get("reply_markup")


@pytest.mark.asyncio
async def test_callback_view_apoi_list():
    q = _Q()
    upd = SimpleNamespace(callback_query=q)
    ctx = SimpleNamespace()

    # ghid|view|D212 → cardul D212
    await ghid_ui.handle_callback(upd, ctx, ["ghid", "view", "D212"])
    assert "D212" in q.text and DEFINITII_OBLIGATII["D212"].de_ce in q.text

    # ghid|list → re-listă (butoane view)
    await ghid_ui.handle_callback(upd, ctx, ["ghid", "list"])
    cbs = [b.callback_data for row in q.kb.inline_keyboard for b in row]
    assert any(c.startswith("ghid|view|") for c in cbs)
