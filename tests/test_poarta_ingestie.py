"""
Poarta de ingestie: fara onboarding terminat, niciun document nu se citeste.

Gardianul vechi testa `user_is_in_onboarding`, care e True DOAR pentru pasii
intermediari — `STEP_NOT_STARTED = 0` intoarce False, si la fel un user fara rand
in DB. Iar `/start` nu seteaza niciun pas pentru useri noi (arata butonul WebApp
si atat). Deci exista o fereastra „nici inceput, nici terminat" prin care poza
trecea direct la OpenAI. Predicatul corect exista deja si era nefolosit aici:
`user_is_onboarded`, care citeste `onboarding_completed`.

POZITIA verificarii e portanta, nu cosmetica. Daca ajunge dupa
`download_as_bytearray()` sau dupa `register_source_file`, se plateste banda si
se scriu randuri chiar daca apelul AI e oprit. Ultimul test din fisier pazeste
exact asta.
"""

import inspect
import re
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User


def _db(tmp_path, nume, *, completed, cu_rand=True, step=0):
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    if cu_rand:
        s = S()
        s.add(User(telegram_id=777, onboarding_completed=completed,
                   onboarding_step=step))
        s.commit()
        s.close()
    return S


class _FakeTgFile:
    file_id = "f1"

    def __init__(self, spion):
        self._spion = spion

    async def download_as_bytearray(self):
        self._spion["download"] = True
        return bytearray(b"pixeli")


class _FakePhoto:
    def __init__(self, spion):
        self._spion = spion

    async def get_file(self):
        self._spion["get_file"] = True
        return _FakeTgFile(self._spion)


class _FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, **kw):
        self.messages.append(kw)


class _FakeMessage:
    def __init__(self, spion):
        self.photo = [_FakePhoto(spion)]
        self.caption = None
        self.replies = []

    async def reply_text(self, text, **kw):
        self.replies.append(text)


def _update(spion):
    msg = _FakeMessage(spion)
    return SimpleNamespace(
        message=msg,
        effective_user=SimpleNamespace(id=777, full_name="Test", username="test"),
        effective_chat=SimpleNamespace(id=999),
    ), msg


def _monteaza(monkeypatch, S, spion):
    """Leaga botul de DB-ul de test si pune spioni pe tot ce COSTA."""
    import bot_contabil
    from app.services import onboarding as onb

    monkeypatch.setattr(bot_contabil, "get_session", lambda: S())
    monkeypatch.setattr(onb, "get_session", lambda: S())

    def _register(**kw):
        spion["register"] = True
        return {"id": 1, "is_duplicate": False, "created_at": None}

    monkeypatch.setattr(bot_contabil, "register_source_file", _register)

    def _extract(**kw):
        spion["openai"] = True
        return {"items": [], "validation_errors": []}

    monkeypatch.setattr(bot_contabil.ai_client, "extract_document", _extract)
    return bot_contabil


# ── 1. Neonboardat: nimic nu costa ───────────────────────────

@pytest.mark.asyncio
async def test_neonboardat_nu_descarca_nu_scrie_nu_cheama_openai(tmp_path, monkeypatch):
    spion = {}
    S = _db(tmp_path, "neonb.db", completed=False)
    bot = _monteaza(monkeypatch, S, spion)
    update, msg = _update(spion)

    await bot.handle_photo_wrapper(update, None)

    assert spion.get("get_file") is None, "s-a cerut fisierul de la Telegram"
    assert spion.get("download") is None, "s-a descarcat fisierul (banda platita)"
    assert spion.get("register") is None, "s-a scris un source_file"
    assert spion.get("openai") is None, "s-a chemat OpenAI"
    assert msg.replies and "Coniar" in msg.replies[0]


@pytest.mark.asyncio
async def test_user_inexistent_in_db_e_oprit_la_fel(tmp_path, monkeypatch):
    # cazul care scapa cel mai usor: nici macar n-a dat /start
    spion = {}
    S = _db(tmp_path, "fararand.db", completed=False, cu_rand=False)
    bot = _monteaza(monkeypatch, S, spion)
    update, msg = _update(spion)

    await bot.handle_photo_wrapper(update, None)

    assert not any(spion.get(k) for k in ("get_file", "download", "register", "openai"))
    assert msg.replies and "/start" in msg.replies[0]


@pytest.mark.asyncio
async def test_step_intermediar_ramane_oprit(tmp_path, monkeypatch):
    # comportamentul vechi se pastreaza: cine e in mijlocul configurarii e oprit
    spion = {}
    S = _db(tmp_path, "inmijloc.db", completed=False, step=3)
    bot = _monteaza(monkeypatch, S, spion)
    update, _ = _update(spion)

    await bot.handle_photo_wrapper(update, None)
    assert not any(spion.get(k) for k in ("get_file", "download", "register", "openai"))


# ── 2. Onboardat: trece neatins ──────────────────────────────

@pytest.mark.asyncio
async def test_onboardat_trece_si_ajunge_la_extractie(tmp_path, monkeypatch):
    spion = {}
    S = _db(tmp_path, "onb.db", completed=True, step=99)
    bot = _monteaza(monkeypatch, S, spion)
    update, msg = _update(spion)
    context = SimpleNamespace(bot=_FakeBot())

    await bot.handle_photo_wrapper(update, context)

    assert spion.get("get_file") is True
    assert spion.get("download") is True
    assert spion.get("openai") is True          # drumul normal, neatins
    assert not any("Coniar" in r and "/start" in r for r in msg.replies)


# ── 3. Textul portii ─────────────────────────────────────────

def test_mesajul_spune_ce_e_coniar_ce_urmeaza_si_are_engleza():
    import bot_contabil
    m = bot_contabil.MESAJ_POARTA_INGESTIE
    assert "Coniar" in m                                 # ce e
    assert "PFA" in m and "ANAF" in m                    # pentru cine
    assert "/start" in m                                 # ce sa faca
    assert "Începe configurarea" in m                    # SI butonul de dupa
    assert "This is Coniar" in m                         # linia in engleza
    assert "tap /start" in m


def test_mesajul_nu_promite_un_timp_pe_care_nu_il_tinem():
    """Wizardul are 4 pasi pentru non-sofer, dar 7-8 pentru sofer (wizSteps():
    +masina, +platforme, +nerezident, +apibolt) — iar soferul e chiar publicul
    mesajului. „Sub un minut" nu se tine la primul contact."""
    import bot_contabil
    m = bot_contabil.MESAJ_POARTA_INGESTIE
    assert "sub un minut" not in m.lower()
    assert "under a minute" not in m.lower()


def test_ambele_porti_folosesc_acelasi_text():
    # doua porti, un singur text — fara divergenta tacuta
    import bot_contabil
    for fn in (bot_contabil.handle_photo_wrapper,
               bot_contabil.handle_bank_statement_wrapper):
        assert "MESAJ_POARTA_INGESTIE" in inspect.getsource(fn)


# ── 4. GARDIAN DE POZITIE (cel care conteaza) ────────────────

_COSTURI = ["get_file(", "download_as_bytearray", "register_source_file",
            "ensure_user("]


@pytest.mark.parametrize("nume_fn", ["handle_photo_wrapper",
                                     "handle_bank_statement_wrapper"])
def test_poarta_sta_inaintea_oricarui_cost(nume_fn):
    """Verificarea trebuie sa fie INAINTEA a tot ce costa bani sau randuri.

    Daca ajunge dupa descarcare, oprim apelul AI dar platim banda si scriem in
    DB — adica poarta apara timpul, nu portofelul. Testul cade la mutare.
    """
    import bot_contabil
    src = inspect.getsource(getattr(bot_contabil, nume_fn))
    # comentariile NU conteaza: unul dintre ele numeste chiar get_file(), ca sa
    # explice de ce sta poarta acolo. Se masoara codul, nu proza despre el.
    linii = ["" if l.strip().startswith("#") else l for l in src.splitlines()]

    poarta = next(
        (i for i, l in enumerate(linii) if "user_is_onboarded" in l), None
    )
    assert poarta is not None, f"{nume_fn}: poarta a disparut"

    for cost in _COSTURI:
        primul = next((i for i, l in enumerate(linii) if cost in l), None)
        if primul is None:
            continue
        assert poarta < primul, (
            f"{nume_fn}: poarta (linia {poarta}) e DUPA {cost} (linia {primul}) — "
            f"cine e oprit tot plateste"
        )


@pytest.mark.parametrize("nume_fn", ["handle_photo_wrapper",
                                     "handle_bank_statement_wrapper"])
def test_predicatul_vechi_nu_mai_e_folosit_ca_poarta(nume_fn):
    # user_is_in_onboarding lasa sa treaca step=0 si userii fara rand — exact
    # fereastra prin care se scurgea ingestia
    import bot_contabil
    src = inspect.getsource(getattr(bot_contabil, nume_fn))
    assert "user_is_in_onboarding" not in src
