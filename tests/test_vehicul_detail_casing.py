"""
Bug casing tip_detinere (fix de CITIRE, vehicule._show_vehicul_detail).

`tip_detinere` e stocat UPPERCASE din bot (constante) sau lowercase din wizard-ul
web (app.py scrie verbatim valorile select-ului: "comodat"/"proprietate"/...).
Detaliul mașinii normaliza greșit case-sensitive → pt mașinile web (lowercase):
labelul deținerii ieșea "—" ȘI avertismentul fiscal RCA/CASCO lipsea. Fix: o
singură normalizare `.upper()` la citire acoperă ambele simptome.
"""

import asyncio
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import vehicule
from app.models import User, Vehicul, TIP_DETINERE_LABELS, TIP_DETINERE_COMODAT


class _Capture:
    def __init__(self):
        self.text = None

    async def edit_message_text(self, text, **kw):
        self.text = text


def _run_detail(monkeypatch, tmp_path, tip_detinere):
    eng = create_engine(f"sqlite:///{(tmp_path / 'veh.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(telegram_id=1)
    s.add(u); s.commit(); uid = u.id
    v = Vehicul(user_id=uid, nr_inmatriculare="B-10-DET", activ=True,
                tip_detinere=tip_detinere)
    s.add(v); s.commit(); vid = v.id
    s.close()
    monkeypatch.setattr(vehicule, "get_session", lambda: S())
    cap = _Capture()
    update = SimpleNamespace(callback_query=cap)
    asyncio.run(vehicule._show_vehicul_detail(update, None, uid, vid))
    return cap.text


def test_detail_comodat_lowercase_label_si_avertisment(monkeypatch, tmp_path):
    # Mașină salvată lowercase (ca din wizard-ul web) — ÎNAINTE: label "—" + fără warning.
    text = _run_detail(monkeypatch, tmp_path, "comodat")
    assert TIP_DETINERE_LABELS[TIP_DETINERE_COMODAT] in text   # label corect, nu "—"
    assert "RCA/CASCO" in text                                 # avertisment fiscal prezent


def test_detail_comodat_uppercase_la_fel(monkeypatch, tmp_path):
    # Mașină salvată UPPERCASE (ca din bot) — calea existentă neatinsă, tot merge.
    text = _run_detail(monkeypatch, tmp_path, "COMODAT")
    assert TIP_DETINERE_LABELS[TIP_DETINERE_COMODAT] in text
    assert "RCA/CASCO" in text


def test_detail_proprietate_lowercase_label_fara_avertisment(monkeypatch, tmp_path):
    # Non-comodat lowercase → label corect ȘI FĂRĂ avertismentul de comodat.
    text = _run_detail(monkeypatch, tmp_path, "proprietate")
    assert TIP_DETINERE_LABELS["PROPRIETATE"] in text
    assert "RCA/CASCO" not in text
