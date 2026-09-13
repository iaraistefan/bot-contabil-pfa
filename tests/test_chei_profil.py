"""
Gardian de CLASĂ: orice `profile.get("…")` din cod trebuie să întrebe după o cheie pe
care `users_repo.get_profile_dict` chiar o produce.

De ce există testul ăsta
------------------------
`app/http/app.py` citea `profile.get("forma_juridica")`. Cheia nu există în dict — el
are `firma_forma_juridica` — deci expresia cădea MEREU pe fallback-ul „PFA", pentru
orice user, la fiecare cerere pe /api/v1/obligatii.

Nu era un `or` de siguranță. Era o nepotrivire de chei mascată de un implicit care se
întâmplă să fie corect azi: toți userii reali sunt PFA (sau au forma NULL, care cade
tot pe PFA). Un bug de felul ăsta nu produce nicio eroare și nu lasă nicio urmă —
arată identic cu o valoare implicită bine aleasă. De asta a trăit nevăzut, și de asta
nu ajunge să-l repari: clasa lui trebuie păzită.

Miza reală e divergența. Drumul Telegram citește cheia CORECTĂ
(`proactive_alerts._build_user_context` → `fiscal_profile.from_user_dict`, care ia
`firma_forma_juridica`). Dacă vreodată un user are altă formă decât PFA, web-ul ar
spune una și botul alta, pe același profil, tăcut — exact tiparul pentru care
`_compute_termen_anual_rolling` a fost făcută sursă unică.

Cheile se DERIVĂ, nu se scriu de mână
-------------------------------------
Lista validă se obține CHEMÂND `get_profile_dict` pe un user real (SQLite temporar),
nu citind dict-ul din sursă și nu copiindu-l aici. Dacă cineva redenumește un câmp
sau restructurează funcția, testul urmărește funcția. O listă scrisă de mână ar
deveni ea însăși a doua sursă de adevăr — adică bug-ul pe care-l păzim, mutat în test.
"""

import re
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.repositories import users as users_repo

APP_DIR = Path(__file__).resolve().parents[1] / "app"
BOT = Path(__file__).resolve().parents[1] / "bot_contabil.py"

# `profile.get("…")` / `profile_dict.get("…")`. DELIBERAT fără `p.get(`: numele scurt
# e folosit în `bolt_sync.py` / `bolt_reconcile.py` pentru payload-uri Bolt
# (`ride_price`, `net_earnings`, `brand`), care n-au nicio legătură cu profilul. Un
# pattern mai lat ar aduce fals-pozitive și ar forța un allowlist gras, care dezarmează
# gardianul. Numele lung e convenția pentru profilul user-ului în tot codul.
_APEL = re.compile(r"\b(?:profile|profile_dict)\.get\(\s*[\"']([a-zA-Z_0-9]+)[\"']")

# ── Excepții, pe (fișier, cheie), fiecare cu motiv scris ──────────────
#
# declaratii_service.py / "adresa" — sondare DELIBERATĂ a unui câmp care nu a fost
#   adăugat niciodată, cu fallback documentat pe loc („adresa din judet + localitate
#   daca nu exista camp dedicat", L162). Diferă în esență de bug-ul de mai sus: acolo
#   fallback-ul MASCA o nepotrivire, aici el E comportamentul intenționat, iar autorul
#   a scris că știe că nu există câmp dedicat. Rămâne în allowlist, nu scos din cod:
#   dacă se adaugă vreodată `adresa` în profil, liniile astea încep să funcționeze
#   singure. Două locuri, același înțeles: L163 (DateFirma) și L858 (IdentitateD212).
ALLOWLIST = {
    ("declaratii_service.py", "adresa"),
}


def _chei_valide(tmp_path):
    """Cheile pe care `get_profile_dict` le produce EFECTIV — derivate la rulare."""
    eng = create_engine(f"sqlite:///{(tmp_path / 'chei.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    try:
        u = User(telegram_id=1234)
        s.add(u)
        s.commit()
        profil = users_repo.get_profile_dict(s, u.id)
        assert profil, "get_profile_dict n-a întors nimic pentru un user real"
        return set(profil.keys())
    finally:
        s.close()


def _fisiere():
    for p in APP_DIR.rglob("*.py"):
        if "__pycache__" not in p.parts:
            yield p
    if BOT.exists():
        yield BOT


def test_get_profile_dict_produce_cheile_asteptate(tmp_path):
    """
    Ancoră: dacă asta cade, s-a redenumit un câmp — nu „repara" testul, verifică ce
    consumă cheia. Verificăm doar cele câteva chei de care atârnă decizii fiscale.
    """
    chei = _chei_valide(tmp_path)
    for must in ("firma_forma_juridica", "regim_tva", "regim_impunere",
                 "activity_code", "judet", "cnp", "onboarding_completed"):
        assert must in chei, f"get_profile_dict nu mai produce {must!r}"
    # Cheia care a produs bug-ul NU trebuie să reapară ca sinonim: două chei pentru
    # același fapt ar readuce exact divergența dintre suprafețe.
    assert "forma_juridica" not in chei, (
        "get_profile_dict a căpătat și `forma_juridica` pe lângă `firma_forma_juridica`. "
        "Două chei pentru aceeași formă juridică = suprafețele pot citi fiecare alta. "
        "Păstrează UNA."
    )


def test_niciun_profile_get_pe_cheie_inexistenta(tmp_path):
    """
    Gardianul de clasă. Scanează tot `app/` + `bot_contabil.py`.

    Cade dacă vreun `profile.get("x")` întreabă după o cheie pe care
    `get_profile_dict` nu o produce — tăcut, cu fallback care pare intenționat.
    """
    chei = _chei_valide(tmp_path)
    vinovati = []

    for p in _fisiere():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in _APEL.finditer(txt):
            cheie = m.group(1)
            if cheie in chei:
                continue
            if (p.name, cheie) in ALLOWLIST:
                continue
            nr = txt[:m.start()].count("\n") + 1
            rel = p.name if p == BOT else p.relative_to(APP_DIR)
            vinovati.append(f"{rel}:{nr} → {cheie!r}")

    assert not vinovati, (
        "`profile.get(...)` pe chei care NU exista in get_profile_dict:\n  "
        + "\n  ".join(vinovati)
        + "\n\nO cheie greșită nu da eroare: cade pe fallback si arata ca o valoare "
        "implicita bine aleasa. Verifica numele real in users_repo.get_profile_dict "
        "(ex. forma juridica e `firma_forma_juridica`, nu `forma_juridica`). Daca "
        "sondarea e deliberata, adaug-o in ALLOWLIST cu motiv scris."
    )


def test_forma_juridica_web_citeste_cheia_corecta():
    """
    Instanța reparată, prinsă pe text: /api/v1/obligatii nu mai are voie să citească
    `forma_juridica`. Gardianul de mai sus ar prinde-o oricum — testul ăsta numește
    bug-ul concret, ca să se vadă în raport ce anume s-a reparat.
    """
    txt = (APP_DIR / "http" / "app.py").read_text(encoding="utf-8", errors="ignore")
    assert 'profile.get("firma_forma_juridica")' in txt, (
        "app.py nu mai citeste firma_forma_juridica pentru forma juridica"
    )
    assert 'profile.get("forma_juridica")' not in txt, (
        "a reaparut profile.get(\"forma_juridica\") — cheie inexistenta, cade mereu pe PFA"
    )
