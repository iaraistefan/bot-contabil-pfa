"""
D700 — o obligație UNICA n-are numărătoare inversă.

De ce există testul ăsta
------------------------
`compute_obligation` punea obligațiilor UNICA `termen = today + 7 zile`,
recalculat la fiecare rulare. Consecința nu era o dată imprecisă, ci un termen
care nu se apropia NICIODATĂ: `zile_ramase` ieșea invariabil 7, deci
`proactive_alerts._determine_alert_type` se potrivea la nesfârșit pe pragul de 7
zile. Deduplicarea (cod + an + lună) o oprea doar în cadrul lunii → un
„D700 în 7 zile" trimis lunar, la infinit, cu un termen inventat.

Reparația are două jumătăți, și amândouă sunt verificate aici:

1. Pragurile 0/3/7 nu se aplică unei obligații UNICA. E declanșată de un
   EVENIMENT, nu de o dată din calendar — pragurile nu descriu nimic pentru ea.
   Restanța rămâne: aia e adevărată și trebuie să escaladeze.

2. Termenul se derivă din cel mai vechi venit al userului. Art. 317 alin. (1)
   lit. c) cere înregistrarea „înaintea primirii serviciilor respective", iar
   pentru un șofer serviciul se primește la prima cursă (vezi §D700 în
   `fiscal_calendar` și `test_d700_declansator.py`). Data primei curse e deci
   ultima zi la care mai erai la timp → după ea, RESTANTĂ.

Ce verifică gardianul, mai exact
-------------------------------
TIPARUL, nu cifra 7. Un termen calculat din `today + N` are o semnătură care nu
depinde de N: se MIȘCĂ odată cu `today`. Testul rulează aceeași obligație cu
două date de referință diferite și cere ca termenul să nu se clintească. Cade
la `today + 7`, cade la `today + 3`, cade la `today + 30` — și cade și dacă
cineva încearcă să „repare" jucând cifra ca să rateze pragurile.

Rulează pe TOATE definițiile cu frecvența UNICA, nu doar pe D700: dacă mâine
apare a doua obligație unică, gardianul o prinde din prima zi.
"""

from datetime import date, timedelta

import pytest

from app.domain import fiscal_calendar as fc
from app.domain.compliance_guardian import get_compliance_status
from app.domain.fiscal_calendar import (
    DEFINITII_OBLIGATII,
    FrecventaObligatie,
    TERMEN_NEDETERMINAT,
    compute_obligation,
    get_obligations_for_user,
    profil_califica_pentru,
)
from app.services.proactive_alerts import _determine_alert_type

# Contextul unui PFA ridesharing neplătitor TVA fără cod special — profilul
# pentru care D700 chiar e o obligație.
CTX = dict(forma_juridica="PFA", activity_code="ridesharing")

PRIMA_CURSA = date(2026, 3, 12)

UNICE = [
    (cheie, d) for cheie, d in DEFINITII_OBLIGATII.items()
    if d.frecventa == FrecventaObligatie.UNICA
]


def test_exista_cel_putin_o_obligatie_unica():
    """Fără asta, gardianul de mai jos ar trece pe o listă goală."""
    assert UNICE, "nicio definiție UNICA — gardianul ar fi vid, deci inutil"


# ══════════════════════════════════════════════════════════════
#  GARDIANUL: termenul unei UNICA nu urmărește `today`
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("cheie,definitie", UNICE, ids=[c for c, _ in UNICE])
def test_gardian_termen_unica_nu_urmareste_today(cheie, definitie):
    """
    Injectare deliberată: aceeași obligație, două `today` diferite.

    `today + N` (orice N) deplasează termenul cu exact atâtea zile cât diferă
    cele două date de referință. Un termen legat de un eveniment nu se mișcă.
    """
    t1 = date(2026, 6, 1)
    t2 = t1 + timedelta(days=97)     # ales să nu semene cu niciun prag

    o1 = compute_obligation(
        definitie, 2026, 6, **CTX, today=t1, prima_activitate=PRIMA_CURSA,
    )
    o2 = compute_obligation(
        definitie, 2026, 6, **CTX, today=t2, prima_activitate=PRIMA_CURSA,
    )

    assert o1.termen == o2.termen == PRIMA_CURSA, (
        f"{definitie.cod}: termenul s-a mișcat cu `today` "
        f"({o1.termen} → {o2.termen}). Ăsta e tiparul `today + N`, "
        f"indiferent de N: o obligație UNICA e declanșată de un eveniment, "
        f"nu de calendar."
    )

    # Corolarul care făcea alerta să se repete la infinit: zilele rămase erau
    # constante. Acum se consumă, ca la orice termen real.
    assert o1.zile_ramase != o2.zile_ramase
    assert o2.zile_ramase == o1.zile_ramase - 97


@pytest.mark.parametrize("cheie,definitie", UNICE, ids=[c for c, _ in UNICE])
def test_gardian_termen_unica_nu_e_in_viitorul_apropiat(cheie, definitie):
    """
    A doua față a aceluiași tipar, verificată fără a compara două rulări:
    un termen derivat din `today + N` cu N mic (pragurile de alertă) ar cădea
    în fereastra 0..60 de zile de la `today`. Cel real e ANTERIOR primei curse.
    """
    today = date(2026, 9, 5)
    o = compute_obligation(
        definitie, 2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
    )
    delta = (o.termen - today).days
    assert not (0 <= delta <= 60), (
        f"{definitie.cod}: termen la {delta} zile în viitor de la `today` — "
        f"miroase a `today + N`. Termenul unei obligații UNICA e ANTERIOR "
        f"evenimentului care o naște, deci în trecut din clipa în care există."
    )


# ══════════════════════════════════════════════════════════════
#  1. Pragurile 0/3/7 nu se aplică unei UNICA
# ══════════════════════════════════════════════════════════════

@pytest.mark.parametrize("zile", [0, 3, 7])
def test_unica_exclusa_din_numaratoarea_inversa(zile):
    assert _determine_alert_type(zile) is not None, (
        "control: pragul chiar produce o alertă pentru obligațiile normale"
    )
    assert _determine_alert_type(zile, FrecventaObligatie.UNICA) is None


@pytest.mark.parametrize("zile", [-1, -5, -8, -15])
def test_unica_pastreaza_escaladarea_pe_restanta(zile):
    """Excludem pragurile, nu obligația: restanța e adevărată și escaladează."""
    assert _determine_alert_type(zile) == _determine_alert_type(
        zile, FrecventaObligatie.UNICA
    )
    assert _determine_alert_type(zile, FrecventaObligatie.UNICA) is not None


def test_frecventele_normale_nu_sunt_atinse():
    for frecventa in (
        FrecventaObligatie.LUNARA,
        FrecventaObligatie.TRIMESTRIALA,
        FrecventaObligatie.ANUALA,
    ):
        assert _determine_alert_type(7, frecventa) is not None


# ══════════════════════════════════════════════════════════════
#  2. Termenul spune adevărul: derivat din prima cursă
# ══════════════════════════════════════════════════════════════

def test_d700_apare_restant_din_data_primei_curse():
    today = date(2026, 9, 5)
    obl = get_obligations_for_user(
        2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
    )
    d700 = next(o for o in obl if o.definitie.cod == "D700")

    assert d700.termen == PRIMA_CURSA
    assert d700.zile_ramase == (PRIMA_CURSA - today).days < 0
    assert d700.status == fc.StatusObligatie.DEPASIT


def test_perioada_unica_vine_din_termen_nu_din_luna_privita():
    """
    Jobul de alerte verifică TREI luni la fiecare rulare și deduplică pe
    (cod, perioada_an, perioada_luna). Cu luna privită drept perioadă, aceeași
    obligație unică primea trei chei distincte → pleca de trei ori și era
    numărată de trei ori în scor. Perioada ei e momentul nașterii, nu luna în
    care te uiți la ea.
    """
    today = date(2026, 9, 5)
    perioade = set()
    for an, luna in ((2026, 9), (2026, 8), (2026, 7)):
        o = compute_obligation(
            DEFINITII_OBLIGATII["D700"], an, luna, **CTX,
            today=today, prima_activitate=PRIMA_CURSA,
        )
        perioade.add((o.perioada_an, o.perioada_luna))

    assert perioade == {(PRIMA_CURSA.year, PRIMA_CURSA.month)}


def test_obligatiile_periodice_isi_pastreaza_perioada():
    """Contra-proba: schimbarea de mai sus e DOAR pentru UNICA."""
    o = compute_obligation(
        DEFINITII_OBLIGATII["D212"], 2026, 7, **CTX, today=date(2026, 9, 5),
    )
    assert (o.perioada_an, o.perioada_luna) == (2026, 7)


# ══════════════════════════════════════════════════════════════
#  3. Fără venit: iese din calendar, DAR prevenția rămâne aprinsă
# ══════════════════════════════════════════════════════════════

def test_fara_venit_d700_lipseste_din_calendar_dar_prevenita_ramane():
    """
    Cele două jumătăți ale ACELEIAȘI decizii, verificate împreună — dacă
    cineva le desparte peste un an, testul trebuie să pice.

    Jumătatea 1: fără niciun venit n-avem declanșatorul (prima cursă), deci
    n-avem termenul. Obligația e prospectivă, nu restantă; nu-i inventăm o dată
    ca s-o putem afișa. Iese din calendar.

    Jumătatea 2: exact omul ăsta — cel care n-a început încă — e singurul care
    mai poate depune LA TIMP. Recomandarea de prevenție se declanșează pe PROFIL
    (te califici + n-ai cod special), nu pe prezența D700 în lista de termene.
    Legată de listă, s-ar fi stins aici și s-ar fi aprins abia DUPĂ prima cursă,
    adică prea târziu — același declanșator greșit reparat în PR #158, mutat din
    text în logică.
    """
    today = date(2026, 9, 5)

    # Jumătatea 1 — calendarul tace.
    obl = get_obligations_for_user(
        2026, 9, **CTX, today=today, prima_activitate=None,
    )
    assert not [o for o in obl if o.definitie.cod == "D700"], (
        "D700 în calendar fără niciun venit — înseamnă că are un termen, "
        "iar orice termen de acolo e inventat"
    )

    # Jumătatea 2 — prevenția vorbește.
    status = get_compliance_status(
        2026, 9, **CTX, today=today, prima_activitate=None,
    )
    assert any("D700" in r for r in status.recomandari), (
        "recomandarea D700 s-a stins odată cu dispariția din calendar — "
        "omul care e PE CALE să înceapă nu mai află nimic, și ar afla abia "
        "după prima cursă, cu obligația deja restantă"
    )


def test_cu_venit_apar_amandoua():
    """Contra-proba: prezența venitului nu stinge prevenția, o dublează."""
    today = date(2026, 9, 5)
    obl = get_obligations_for_user(
        2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
    )
    assert [o for o in obl if o.definitie.cod == "D700"]

    status = get_compliance_status(
        2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
    )
    assert any("D700" in r for r in status.recomandari)


def test_cu_cod_special_tac_amandoua():
    """Cine are deja codul special nu mai are nici obligația, nici sfatul."""
    today = date(2026, 9, 5)
    obl = get_obligations_for_user(
        2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
        has_cod_special_tva=True,
    )
    assert not [o for o in obl if o.definitie.cod == "D700"]

    status = get_compliance_status(
        2026, 9, **CTX, today=today, prima_activitate=PRIMA_CURSA,
        has_cod_special_tva=True,
    )
    assert not any("D700" in r for r in status.recomandari)


def test_profilul_necalificat_nu_primeste_prevenitia():
    """Prevenția e decuplată de calendar, nu de profil."""
    assert profil_califica_pentru("D700", "PFA", "ridesharing")
    assert not profil_califica_pentru("D700", "PFA", "consultanta")
    assert not profil_califica_pentru("INEXISTENT", "PFA", "ridesharing")

    status = get_compliance_status(
        2026, 9, forma_juridica="PFA", activity_code="consultanta",
        today=date(2026, 9, 5), prima_activitate=None,
    )
    assert not any("D700" in r for r in status.recomandari)


# ══════════════════════════════════════════════════════════════
#  Sentinelul: vizibil dacă scapă, niciodată plauzibil
# ══════════════════════════════════════════════════════════════

def test_sentinelul_nu_poate_trece_drept_termen_real():
    """
    O UNICA fără declanșator primește `TERMEN_NEDETERMINAT`, fiindcă `termen` e
    `date`, nu `Optional[date]`. Alegerea sentinelului e despre modul de eșec:
    dacă scapă vreodată într-un ecran, trebuie să se vadă că e un bug. `today`
    ar fi trecut drept adevăr și ar fi reintrodus exact minciuna scoasă aici.
    """
    today = date(2026, 9, 5)
    o = compute_obligation(
        DEFINITII_OBLIGATII["D700"], 2026, 9, **CTX,
        today=today, prima_activitate=None,
    )
    assert not o.aplicabil_acum
    assert "venit" in (o.motiv_neaplicabil or "")
    assert o.termen == TERMEN_NEDETERMINAT
    assert o.termen.year == 9999, "sentinelul trebuie să fie absurd la vedere"
    assert o.status != fc.StatusObligatie.CRITIC
    # Se poate formata fără să crape — dacă scapă, scapă vizibil, nu cu excepție.
    assert o.termen.strftime("%d.%m.%Y") == "31.12.9999"


# ══════════════════════════════════════════════════════════════
#  Sursa datei: occurred_on, nu data_doc; locked NU se filtrează
# ══════════════════════════════════════════════════════════════

def _mk_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db import Base
    import app.models  # noqa: F401  — înregistrează tabelele

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _add_income(session, user_id, doc_id, occurred_on, locked=False):
    """`occurred_on` e coloana pe care se sortează; `data_doc` (textul „zz.ll.aaaa")
    trăiește pe Document și e deliberat NEfolosit la MIN()."""
    from app.models import Transaction
    session.add(Transaction(
        user_id=user_id, document_id=doc_id, tx_type="INCOME",
        category="ride_revenue", amount_brut=100.0,
        occurred_on=occurred_on, locked=locked,
    ))


def test_first_income_date_ignora_locked():
    """
    Tranzacțiile dintr-o perioadă fiscală ÎNCHISĂ sunt exact cele mai vechi. Cu
    `locked == False` în filtru, data primei curse ar migra înainte pe măsură ce
    se închid perioadele, iar obligația ar părea tot mai puțin restantă cu
    fiecare închidere — un termen care se repară singur în timp.
    """
    from app.repositories import transactions as tx_repo

    session = _mk_session()
    try:
        _add_income(session, 1, 1, date(2026, 3, 12), locked=True)
        _add_income(session, 1, 2, date(2026, 8, 4), locked=False)
        session.commit()

        assert tx_repo.first_income_date(session, 1) == date(2026, 3, 12)
    finally:
        session.close()


def test_first_income_date_nu_sorteaza_lexicografic():
    """
    `Document.data_doc` e `String(20)` în „zz.ll.aaaa": MIN() pe el ar da
    „01.12.2025" < „02.01.2026", adică decembrie „mai vechi" decât ianuarie
    următoare. Sortăm pe `occurred_on`, care e `Date` real.
    """
    from app.repositories import transactions as tx_repo

    session = _mk_session()
    try:
        _add_income(session, 1, 1, date(2025, 12, 1))
        _add_income(session, 1, 2, date(2026, 1, 2))
        session.commit()

        assert tx_repo.first_income_date(session, 1) == date(2025, 12, 1)
    finally:
        session.close()


def test_first_income_date_izolat_pe_user_si_pe_tip():
    from app.repositories import transactions as tx_repo
    from app.models import Transaction

    session = _mk_session()
    try:
        _add_income(session, 2, 1, date(2026, 3, 12))
        session.add(Transaction(
            user_id=1, document_id=2, tx_type="EXPENSE", category="fuel",
            amount_brut=50.0, occurred_on=date(2025, 1, 1),
        ))
        session.commit()

        assert tx_repo.first_income_date(session, 1) is None
        assert tx_repo.first_income_date(session, 2) == date(2026, 3, 12)
    finally:
        session.close()
