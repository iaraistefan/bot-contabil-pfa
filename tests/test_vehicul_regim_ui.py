"""
Felia gardieni UI regim (bot) — fluxul de setare regim_utilizare pe vehicul.

Acoperă comportamentul CRITIC: EXCLUSIV NU se poate seta ocolind gardianul de
avertisment (uz exclusiv → dovadă la ANAF). Vehicul REAL în DB (nu monkeypatch),
mock minimal pentru update/context (pattern din test_vehicul_detail_casing).
"""

import asyncio
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import vehicule
from app.models import User, Vehicul


class _Capture:
    def __init__(self):
        self.text = None
        self.markup = None

    async def edit_message_text(self, text, **kw):
        self.text = text
        self.markup = kw.get("reply_markup")


def _setup(monkeypatch, tmp_path, regim="MIXT"):
    eng = create_engine(f"sqlite:///{(tmp_path / 'r.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=555)
    s.add(u); s.commit(); uid = u.id
    v = Vehicul(user_id=uid, nr_inmatriculare="B-RE-GIM", activ=True,
                regim_utilizare=regim)
    s.add(v); s.commit(); vid = v.id
    s.close()
    monkeypatch.setattr(vehicule, "get_session", lambda: S())
    monkeypatch.setattr(vehicule.audit_repo, "write", lambda *a, **k: None)
    return S, uid, vid


def _ctx(vid):
    return SimpleNamespace(user_data={vehicule._WIZARD_KEY: {
        "mode": "edit", "step": "regim", "vehicul_id": vid, "data": {}}})


def _update():
    cap = _Capture()
    upd = SimpleNamespace(callback_query=cap, effective_user=SimpleNamespace(id=555))
    return upd, cap


def _regim_in_db(S, vid):
    s = S()
    r = s.get(Vehicul, vid).regim_utilizare
    s.close()
    return r


# 1. CRITIC — EXCLUSIV NU salvează, arată gardianul; DB rămâne MIXT.
def test_handle_regim_exclusiv_nu_salveaza_arata_gardian(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="MIXT")
    upd, cap = _update()
    asyncio.run(vehicule._handle_regim(upd, _ctx(vid), "EXCLUSIV"))
    assert _regim_in_db(S, vid) == "MIXT"          # NEschimbat — gardianul nu se ocolește
    assert "uz exclusiv" in (cap.text or "").lower()  # gardianul afișat
    # butonul de confirmare (regimok) e prezent în markup
    cbs = [b.callback_data for row in cap.markup.inline_keyboard for b in row]
    assert "vehicul|regimok" in cbs


# 2. MIXT → salvează direct (fără gardian).
def test_handle_regim_mixt_salveaza_direct(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="EXCLUSIV")  # start EXCLUSIV
    upd, cap = _update()
    asyncio.run(vehicule._handle_regim(upd, _ctx(vid), "MIXT"))
    assert _regim_in_db(S, vid) == "MIXT"          # schimbat direct
    assert "salvat" in (cap.text or "").lower()


# 3. regimok → confirmă și salvează EXCLUSIV.
def test_handle_regim_confirm_salveaza_exclusiv(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="MIXT")
    upd, cap = _update()
    asyncio.run(vehicule._handle_regim_confirm(upd, _ctx(vid)))
    assert _regim_in_db(S, vid) == "EXCLUSIV"


# 4. Regim invalid → eroare, nimic salvat.
def test_handle_regim_invalid(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="MIXT")
    upd, cap = _update()
    asyncio.run(vehicule._handle_regim(upd, _ctx(vid), "BLA"))
    assert _regim_in_db(S, vid) == "MIXT"
    assert "nu recunosc" in (cap.text or "").lower()


# 5. Detaliu — EXCLUSIV: linie „Utilizare" + explainer; MIXT: linie fără explainer.
def test_detaliu_exclusiv_linie_si_explainer(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="EXCLUSIV")
    upd, cap = _update()
    asyncio.run(vehicule._show_vehicul_detail(upd, None, uid, vid))
    assert "Utilizare:" in cap.text
    assert "se deduce 100%" in cap.text            # explainerul uz exclusiv


def test_detaliu_mixt_linie_fara_explainer(monkeypatch, tmp_path):
    S, uid, vid = _setup(monkeypatch, tmp_path, regim="MIXT")
    upd, cap = _update()
    asyncio.run(vehicule._show_vehicul_detail(upd, None, uid, vid))
    assert "Utilizare:" in cap.text                # linia apare
    assert "se deduce 100%" not in cap.text        # explainerul NU
