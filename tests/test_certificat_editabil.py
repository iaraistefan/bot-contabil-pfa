"""
Data certificatului ONRC se poate completa DUPA onboarding — pe amandoua drumurile.

De ce exista fisierul: #138 a adus captarea (numar automat + data confirmata la
configurare) si a lasat generatorul D212 sa refuze cu „o completezi in profil".
Numai ca profilul n-avea campul: cine amana data la configurare ramanea fara
drum inapoi, iar mesajul de refuz trimitea intr-un loc care nu exista.

Se masoara patru lucruri:
  1. din bot, cu onboarding-ul TERMINAT (inainte era imposibil — fluxul de
     confirmare traieste in handle_onboarding_text, care iese devreme la
     STEP_COMPLETED);
  2. din web, tot cu onboarding-ul terminat;
  3. o data invalida e refuzata pe amandoua, cu ACELASI mesaj;
  4. promisiunea din mesajul de refuz al D212 are destinatie reala pe AMBELE
     suprafete (gardianul de la coada fisierului).
"""

import inspect
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.doc_autorizare import MESAJ_DATA_INVALIDA
from app.models import User

_ROOT = Path(__file__).resolve().parent.parent
_HTML = (_ROOT / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _db(tmp_path, nume="cert.db"):
    """User cu onboarding TERMINAT si numar de certificat, dar fara data."""
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    u = User(
        telegram_id=1,
        onboarding_completed=True,          # ← exact cazul care nu avea drum
        onboarding_step=99,
        nr_doc_autorizare="F2025049962009",
        data_doc_autorizare=None,
    )
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return S, uid


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kw):
        self.messages.append(kw)


class _FakeMessage:
    def __init__(self, text):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def _update(text):
    msg = _FakeMessage(text)
    return SimpleNamespace(
        message=msg,
        effective_chat=SimpleNamespace(id=999),
    ), msg


# ════════════ 1. BOT — se poate seta dupa onboarding terminat ════════════

@pytest.mark.asyncio
async def test_bot_seteaza_data_dupa_onboarding_terminat(tmp_path, monkeypatch):
    import bot_contabil
    S, uid = _db(tmp_path, "bot_ok.db")
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda u: uid)

    update, msg = _update("05.12.2025")
    context = SimpleNamespace(user_data={"coduri_wizard": "certdata"}, bot=_FakeBot())

    await bot_contabil.handle_coduri_wizard_text(update, context)

    s = S()
    try:
        assert s.get(User, uid).data_doc_autorizare == date(2025, 12, 5)
    finally:
        s.close()
    assert "05.12.2025" in msg.replies[0]
    assert "coduri_wizard" not in context.user_data      # starea s-a curatat


@pytest.mark.asyncio
async def test_bot_butonul_de_certificat_apare_in_ecranul_de_coduri(tmp_path, monkeypatch):
    import bot_contabil
    S, uid = _db(tmp_path, "bot_kb.db")
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())

    s = S()
    try:
        profile_fara = {"nr_doc_autorizare": "F2025049962009", "data_doc_autorizare": None}
        kb = bot_contabil._kb_coduri(profile_fara)
    finally:
        s.close()
    coduri = [b.callback_data for rand in kb.inline_keyboard for b in rand]
    assert "coduri|set_certdata" in coduri


@pytest.mark.asyncio
async def test_bot_ecranul_de_coduri_arata_starea_datei(tmp_path):
    import bot_contabil
    txt = await bot_contabil._coduri_text(
        {"nr_doc_autorizare": "F2025049962009", "data_doc_autorizare": None}
    )
    assert "F2025049962009" in txt
    assert "nesetată" in txt                     # starea, nu tacere
    txt2 = await bot_contabil._coduri_text(
        {"nr_doc_autorizare": "F2025049962009", "data_doc_autorizare": "2025-12-05"}
    )
    assert "05.12.2025" in txt2                  # in formatul declaratiei


# ════════════ 2. WEB — se poate seta dupa onboarding terminat ════════════

def _web(monkeypatch, tmp_path, nume="web_cert.db"):
    from app.http import app as webapp
    S, uid = _db(tmp_path, nume)
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def test_web_seteaza_data_dupa_onboarding_terminat(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "web_ok.db")
    r = client.post("/api/v1/setari", json={"data_doc_autorizare": "05.12.2025"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    s = S()
    try:
        assert s.get(User, uid).data_doc_autorizare == date(2025, 12, 5)
    finally:
        s.close()


def test_web_setari_expune_certificatul(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "web_get.db")
    d = client.get("/api/v1/setari").get_json()
    assert d["nr_doc_autorizare"] == "F2025049962009"     # numarul, read-only
    assert d["data_doc_autorizare"] == ""                 # data, inca necompletata


def test_web_nu_atinge_data_daca_nu_o_trimite(monkeypatch, tmp_path):
    # salvarea datelor bancare nu are voie sa stearga data certificatului
    client, S, uid = _web(monkeypatch, tmp_path, "web_neutru.db")
    client.post("/api/v1/setari", json={"data_doc_autorizare": "05.12.2025"})
    client.post("/api/v1/setari", json={"banca": "Banca Transilvania"})
    s = S()
    try:
        assert s.get(User, uid).data_doc_autorizare == date(2025, 12, 5)
    finally:
        s.close()


# ════════════ 3. Refuz identic pe ambele drumuri ════════════

@pytest.mark.asyncio
async def test_data_invalida_refuzata_la_fel_pe_ambele(tmp_path, monkeypatch):
    import bot_contabil
    S, uid = _db(tmp_path, "invalid_bot.db")
    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(bot_contabil, "ensure_user", lambda u: uid)

    update, msg = _update("32.13.2025")          # zi si luna imposibile
    context = SimpleNamespace(user_data={"coduri_wizard": "certdata"}, bot=_FakeBot())
    await bot_contabil.handle_coduri_wizard_text(update, context)

    raspuns_bot = msg.replies[0]
    s = S()
    try:
        assert s.get(User, uid).data_doc_autorizare is None    # nimic scris
    finally:
        s.close()
    # starea RAMANE ridicata → userul mai poate incerca, fara sa reapese butonul
    assert context.user_data.get("coduri_wizard") == "certdata"

    client, S2, uid2 = _web(monkeypatch, tmp_path, "invalid_web.db")
    r = client.post("/api/v1/setari", json={"data_doc_autorizare": "32.13.2025"})
    assert r.status_code == 400
    raspuns_web = r.get_json()["message"]

    assert raspuns_bot == raspuns_web == MESAJ_DATA_INVALIDA


# ════════════ 4. Aceleasi promisiuni pe TOATE suprafetele ════════════
#
# #138 masura frazele purtatoare pe doua suprafete, dar partea de web citea TOT
# dashboard.html — un card nou de Setari fara frazele astea ar fi trecut pe
# spatele textului din wizard. Aici fiecare suprafata se masoara SEPARAT.

_PROMISIUNI = [
    "ANAF le vrea pereche",
    "Data eliberării",
    "documentul tău are dreptate",
    "zz.ll.aaaa",
]


def _bloc(inceput, sfarsit):
    m = re.search(re.escape(inceput) + r"(.*?)" + re.escape(sfarsit), _HTML, re.S)
    assert m, f"bloc negasit in dashboard.html: {inceput!r} → {sfarsit!r}"
    return m.group(0)


def _suprafete():
    from app.domain.doc_autorizare import text_confirmare_data
    return {
        # botul (configurare SI Setari — acelasi text, o singura sursa)
        "bot": text_confirmare_data(date(2025, 12, 5), nr_doc="F2025049962009"),
        "web_wizard": _bloc("📜 Data certificatului de la Registrul", "wiz-cert-msg"),
        "web_setari": _bloc("Data certificatului de la Registrul", "set-cert-msg"),
    }


@pytest.mark.parametrize("promisiune", _PROMISIUNI)
@pytest.mark.parametrize("nume", ["bot", "web_wizard", "web_setari"])
def test_fiecare_suprafata_face_aceleasi_promisiuni(nume, promisiune):
    text = _suprafete()[nume]
    assert promisiune.lower() in text.lower(), f"{promisiune!r} lipseste din {nume}"


# ════════════ 5. GARDIAN: promisiunea D212 are destinatie ════════════

def _fara_diacritice(s):
    import unicodedata
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def _bot_expune_data():
    src = (_ROOT / "bot_contabil.py").read_text(encoding="utf-8")
    return "coduri|set_certdata" in src and '"certdata"' in src


def _web_expune_data():
    from app.http import app as webapp
    return (
        'id="set-cert-data"' in _HTML
        and "data_doc_autorizare" in inspect.getsource(webapp.setari_post)
    )


def test_promisiunea_din_refuzul_d212_are_destinatie_pe_ambele_suprafete():
    """Daca D212 spune «o completezi in profil», profilul TREBUIE s-o accepte.

    Gardianul leaga o fraza de o capabilitate: cat timp mesajul trimite userul in
    profil, amandoua suprafetele trebuie sa aiba unde s-o primeasca. Altfel
    mesajul e o indicatie catre un loc care nu exista — exact starea de dupa #138.
    """
    from app.integrations.anaf import d212_generator
    src = _fara_diacritice(inspect.getsource(d212_generator.genereaza_d212)).lower()
    assert "in profil" in src, (
        "Mesajul de refuz al D212 nu mai trimite «in profil». Daca l-ai reformulat "
        "intentionat, muta gardianul pe destinatia noua — nu-l sterge."
    )
    assert _bot_expune_data(), (
        "D212 trimite userul in profil, dar BOTUL n-are unde sa primeasca data "
        "certificatului (lipseste coduri|set_certdata sau ramura de text)."
    )
    assert _web_expune_data(), (
        "D212 trimite userul in profil, dar WEB-ul n-are unde sa primeasca data "
        "certificatului (lipseste campul din Setari sau acceptarea in setari_post)."
    )
