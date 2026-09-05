"""
Sentinelul `TERMEN_NEDETERMINAT` nu are voie să ajungă pe un drum de afișare.

De ce există testul ăsta
------------------------
O obligație UNICA fără declanșator (D700 la un user care n-are încă niciun venit)
primește `termen = date.max`, fiindcă `ObligatieCalculate.termen` e `date`, nu
`Optional[date]`. Sentinelul e ales ca să fie absurd la vedere — „31.12.9999" se
citește ca bug, pe când `today` ar fi trecut drept adevăr.

Azi nu iese nicăieri, fiindcă obligația e marcată `aplicabil_acum=False` și toți
apelanții cer `only_applicable=True`. Dar ăsta e un FILTRU, nu o imposibilitate:
un `only_applicable=False` scris din grabă, o suprafață nouă care iterează altfel,
o refactorizare care mută filtrul — și „31.12.9999" ajunge sub ochii unui om.

Un gardian se judecă după modul lui de eșec. Aici modul de eșec al filtrului e
chiar gaura păzită, deci filtrul singur nu e gardian. Ăsta e.

Ce acoperă
----------
Fiecare suprafață care poate tipări un `termen`, exercitată pe cazul care CHIAR
produce sentinelul (user fără niciun venit):

  • seam-ul comun    — `get_obligations_for_user` (toate drumurile trec pe aici)
  • calendarul botului — `format_calendar_telegram`
  • compliance        — `format_compliance_status_telegram`
  • bilanțul săptămânal — `_format_weekly_dashboard`
  • alertele zilnice  — `_determine_alert_type` + `_format_alert_message`
  • dashboard-ul web  — serializarea din `/api/v1/obligatii`
  • ghidul            — `/api/v1/ghid` (structural: n-are câmp `termen` deloc)

Injectarea care dovedește gardianul e în
`test_injectare_filtrul_slabit_face_gardianul_sa_pice`: slăbim filtrul exact cum
ar face-o o greșeală reală și confirmăm că detectorul se aprinde.

Verificat și pe codul de producție: cu `only_applicable` ignorat în
`get_obligations_for_user`, patru teste pică — seam-ul (×2), calendarul botului și
serializarea dashboard-ului. Compliance și bilanțul săptămânal NU pică, fiindcă au
o a doua barieră (tipăresc doar obligații sub 30 de zile, iar sentinelul cade în
DEPARTE); sunt marcate ca atare în docstring-urile lor, ca nimeni să nu le
citească drept tripwire-uri vii.
"""

from datetime import date

import pytest

from app.domain import fiscal_calendar as fc
from app.domain.compliance_guardian import (
    format_compliance_status_telegram,
    get_compliance_status,
)
from app.domain.fiscal_calendar import (
    TERMEN_NEDETERMINAT,
    FrecventaObligatie,
    format_calendar_telegram,
    get_obligations_for_user,
)
from app.services.proactive_alerts import (
    _determine_alert_type,
    _format_alert_message,
    _format_weekly_dashboard,
)

# Profilul care CHIAR produce sentinelul: se califică pentru D700, dar n-are
# niciun venit, deci n-are declanșator.
CTX = dict(forma_juridica="PFA", activity_code="ridesharing")
TODAY = date(2026, 9, 5)
AN, LUNA = 2026, 9

# Amprentele sentinelului în text. „9999" singur prinde orice format de dată
# (isoformat, %d.%m.%Y, %d.%m), deci e plasa cea mai largă.
AMPRENTE = ("9999", "31.12.9999", "9999-12-31")


def _fara_sentinel(text: str, unde: str) -> None:
    for amprenta in AMPRENTE:
        assert amprenta not in text, (
            f"sentinelul a ajuns pe un drum de afișare ({unde}): "
            f"amprenta [{amprenta}] apare in text. "
            f"Un om ar vedea o dată din anul 9999."
        )


def test_sentinelul_e_recunoscibil():
    """Dacă sentinelul devine o dată plauzibilă, tot testul ăsta e degeaba."""
    assert TERMEN_NEDETERMINAT == date.max
    assert TERMEN_NEDETERMINAT.year == 9999
    assert "9999" in TERMEN_NEDETERMINAT.isoformat()


# ══════════════════════════════════════════════════════════════
#  Seam-ul comun: nimic sentinel nu iese din calendar
# ══════════════════════════════════════════════════════════════

def test_seam_get_obligations_nu_intoarce_niciun_sentinel():
    """
    Toate suprafețele de mai jos trec prin funcția asta. E locul unde un sentinel
    scăpat ar contamina totul deodată, deci merită verificat separat de formatări.
    """
    obl = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
    )
    scapati = [o for o in obl if o.termen == TERMEN_NEDETERMINAT]
    assert not scapati, (
        f"obligații cu termen-sentinel returnate ca aplicabile: "
        f"{[o.definitie.cod for o in scapati]}"
    )


def test_seam_nicio_obligatie_returnata_n_are_termen_absurd():
    """
    Plasa mai largă: nu doar sentinelul exact, ci orice termen dincolo de un
    orizont fiscal rezonabil. O obligație reală nu are termen peste 5 ani.
    """
    obl = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
    )
    for o in obl:
        assert o.termen.year <= TODAY.year + 5, (
            f"{o.definitie.cod} are termen în {o.termen.year} — "
            f"nicio obligație reală nu se scadențează atât de departe"
        )


# ══════════════════════════════════════════════════════════════
#  Suprafețele de afișare, una câte una
# ══════════════════════════════════════════════════════════════

def test_calendar_bot_nu_arata_sentinelul():
    text = format_calendar_telegram(
        AN, LUNA, **CTX, prima_activitate=None,
    )
    _fara_sentinel(text, "format_calendar_telegram")


def test_compliance_telegram_nu_arata_sentinelul():
    """
    NOTA, ca nimeni sa nu creada ca testul asta e un tripwire viu: la injectarea
    filtrului (`only_applicable` ignorat) testul NU s-a aprins, si e corect asa.
    Suprafata are o A DOUA bariera, independenta — tipareste termene doar pentru
    obligatiile din bucket-urile critic/avertisment/proxim (<= 30 zile), iar un
    termen-sentinel cade in DEPARTE. Testul e plasa de rezerva pentru ziua in care
    bucket-urile se schimba, nu detectorul principal. Ala e testul de seam.
    """
    status = get_compliance_status(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
    )
    _fara_sentinel(format_compliance_status_telegram(status), "compliance")


def test_bilantul_saptamanal_nu_arata_sentinelul():
    """
    Aceeasi nota ca la compliance: si aici exista a doua bariera (`upcoming` taie
    la 30 de zile), deci la injectare testul n-a picat. Plasa de rezerva, nu
    detector principal — pastrat fiindca bariera aia e o alegere de afisare care
    se poate schimba oricand, iar sentinelul n-are voie sa treaca nici atunci.
    """
    obl = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
    )
    text = _format_weekly_dashboard(
        {"forma_juridica": "PFA", "activity_code": "ridesharing"},
        obl, (100, "Excelent", "🟢"), TODAY,
    )
    _fara_sentinel(text, "_format_weekly_dashboard")


def test_dashboard_web_nu_serializeaza_sentinelul():
    """
    Oglindește serializarea din `/api/v1/obligatii` (`app.py`): `termen.isoformat()`
    ar produce „9999-12-31" direct în JSON-ul citit de dashboard.
    """
    obl = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
    )
    payload = [
        {"cod": o.definitie.cod, "termen": o.termen.isoformat(),
         "zile_ramase": o.zile_ramase}
        for o in obl
    ]
    _fara_sentinel(repr(payload), "/api/v1/obligatii")


def test_ghidul_n_are_camp_termen_deloc():
    """
    `/api/v1/ghid` serializează `DefinitieObligatie` (conținut static), nu
    `ObligatieCalculate` — deci n-are de unde să scape un termen. Verificăm
    STRUCTURAL, nu pe valoare: dacă cineva adaugă cândva `termen` în payload,
    testul cade și îl obligă să se uite aici întâi.
    """
    campuri = set(vars(fc.DEFINITII_OBLIGATII["D700"]).keys())
    assert "termen" not in campuri
    assert "zile_ramase" not in campuri


# ══════════════════════════════════════════════════════════════
#  Alertele: sentinelul nu poate declanșa una
# ══════════════════════════════════════════════════════════════

def test_sentinelul_nu_poate_declansa_o_alerta():
    """
    Dublă barieră, verificată pe amândouă: obligația nici nu ajunge în listă
    (aplicabil_acum=False), iar dacă ar ajunge, `zile_ramase` ar fi enorm și
    `_determine_alert_type` întoarce None oricum — plus excluderea UNICA.
    """
    o = fc.compute_obligation(
        fc.DEFINITII_OBLIGATII["D700"], AN, LUNA, **CTX,
        today=TODAY, prima_activitate=None,
    )
    assert o.termen == TERMEN_NEDETERMINAT
    assert not o.aplicabil_acum
    assert _determine_alert_type(o.zile_ramase, o.definitie.frecventa) is None
    # și fără informația de frecvență, un termen atât de îndepărtat nu prinde
    # niciun prag (0/3/7 sau restanță)
    assert _determine_alert_type(o.zile_ramase) is None


def test_daca_totusi_s_ar_formata_o_alerta_ar_arata_sentinelul():
    """
    Contra-proba care justifică bariera de mai sus: `_format_alert_message` NU
    are nicio apărare proprie — tipărește ce primește. Dovada că protecția e în
    amonte, nu în formatare, și că mutarea filtrului chiar ar sparge ceva.
    """
    o = fc.compute_obligation(
        fc.DEFINITII_OBLIGATII["D700"], AN, LUNA, **CTX,
        today=TODAY, prima_activitate=None,
    )
    text = _format_alert_message(o, "advance_7d", {"forma_juridica": "PFA"})
    assert "9999" in text, (
        "dacă formatarea a învățat să se apere singură, bariera din amonte "
        "nu mai e singura — actualizează testul, nu-l șterge"
    )


# ══════════════════════════════════════════════════════════════
#  INJECTAREA: filtrul slăbit trebuie să aprindă gardianul
# ══════════════════════════════════════════════════════════════

def test_injectare_filtrul_slabit_face_gardianul_sa_pice():
    """
    Slăbim filtrul exact cum ar face-o o greșeală reală — `only_applicable=False`,
    un cuvânt schimbat — și confirmăm că detectorul se aprinde.

    Fără testul ăsta n-am ști dacă cele de mai sus trec fiindcă sistemul e curat
    sau fiindcă plasa e găurită. Verificăm plasa, nu doar peștele.
    """
    obl_slabit = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
        only_applicable=False,
    )
    scapati = [o for o in obl_slabit if o.termen == TERMEN_NEDETERMINAT]
    assert scapati, (
        "cu filtrul slăbit sentinelul TREBUIE să apară — dacă nu apare, "
        "cazul nu mai e reprodus și testele de mai sus trec degeaba"
    )

    # Și detectorul chiar se aprinde pe el:
    payload = repr([{"termen": o.termen.isoformat()} for o in obl_slabit])
    with pytest.raises(AssertionError):
        _fara_sentinel(payload, "injectare")


def test_injectare_unica_fara_declansator_ramane_singura_sursa():
    """
    Sentinelul are o singură cauză. Dacă mâine apare o a doua cale prin care un
    termen devine `date.max`, testul ăsta cade și obligă la o privire.
    """
    obl_slabit = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=None,
        only_applicable=False,
    )
    for o in obl_slabit:
        if o.termen == TERMEN_NEDETERMINAT:
            assert o.definitie.frecventa == FrecventaObligatie.UNICA, (
                f"{o.definitie.cod} are termen-sentinel dar nu e UNICA — "
                f"a apărut o a doua sursă de sentinel"
            )
            assert not o.aplicabil_acum


def test_cu_venit_sentinelul_dispare_complet():
    """Contra-proba pe cazul normal: cu declanșator, nicăieri niciun sentinel."""
    prima_cursa = date(2026, 3, 12)
    text = format_calendar_telegram(
        AN, LUNA, **CTX, prima_activitate=prima_cursa,
    )
    _fara_sentinel(text, "calendar cu venit")

    obl = get_obligations_for_user(
        AN, LUNA, **CTX, today=TODAY, prima_activitate=prima_cursa,
        only_applicable=False,
    )
    assert not [o for o in obl if o.termen == TERMEN_NEDETERMINAT]
    # și D700 chiar e acolo, cu termenul lui real — altfel testul de mai sus ar
    # trece fiindcă obligația lipsește, nu fiindcă e corectă
    d700 = next(o for o in obl if o.definitie.cod == "D700")
    assert d700.termen == prima_cursa
