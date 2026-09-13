"""
D207 se depune în ULTIMA ZI a lunii februarie — nu „pe 28".

Art. 231 alin. (1) Cod fiscal: declarația se depune „până în ultima zi a lunii
februarie inclusiv a anului curent pentru anul expirat" — modificat 24-12-2020 prin
pct. 154, art. I din Legea 296/2020 (MO 1269/21.12.2020). Forma consolidată
legislatie.just.ro valabilă la 08.08.2026.

Codul avea `ziua_termenului=28`, o TRANSCRIERE a legii, nu legea. În anii bisecți
ultima zi e 29, deci afirmația ieșea falsă. Direcția era conservatoare (userul ar fi
depus cu o zi mai devreme), dar D207 e ANUALA: data nu era doar scrisă în frază, era
CALCULATĂ — în ambele motoare (v2/web și v1/Telegram) și în bannerul D212.

Următorul an bisect: 2028. Testele de aici sunt scrise pe el, ca greșeala să cadă
ACUM, nu în februarie 2028.
"""

import calendar
from datetime import date

import pytest

from app.domain.fiscal_calendar import (
    ANNUAL_DEADLINES,
    DEFINITII_OBLIGATII,
    _compute_termen_anual_rolling,
    compute_obligation,
    get_annual_alerts,
)

BISECT = 2028        # următorul an bisect — 29 februarie
NEBISECT = 2027      # anul dinainte — 28 februarie


def _termen_d207(an_venit, luna_ref=12, today=None):
    """Termenul D207 calculat de motorul v2, pentru un an de venit."""
    o = compute_obligation(
        DEFINITII_OBLIGATII["D207"], an_venit, luna_ref,
        "PFA", "ridesharing", today=today or date(an_venit, 12, 31),
    )
    return o.termen


# ============================================================
#   1. FUNCȚIA DE TERMEN — inclusiv momentul în care se decide bisectul
# ============================================================

def test_ultima_zi_urmareste_bisectul():
    """Fără flag → ziua dată. Cu flag → ultima zi reală a lunii."""
    assert _compute_termen_anual_rolling(2027, 1, 2, 28) == date(2027, 2, 28)
    assert _compute_termen_anual_rolling(2027, 1, 2, 28, ultima_zi=True) == date(2027, 2, 28)
    assert _compute_termen_anual_rolling(2028, 1, 2, 28, ultima_zi=True) == date(2028, 2, 29)


def test_bisectul_se_ia_DUPA_roll_forward():
    """
    Partea subtilă, și singurul loc unde o implementare grăbită greșește: ziua se
    calculează pentru anul în care se DEPUNE, nu pentru anul de referință.

    Referință decembrie 2027 → roll-forward la 2028 → 29 februarie. Dacă bisectul
    s-ar lua din `year` (2027, nebisect), ar ieși 28 — cu un an întreg de întârziere
    până când cineva observă.
    """
    assert _compute_termen_anual_rolling(2027, 12, 2, 28, ultima_zi=True) == date(2028, 2, 29)
    assert _compute_termen_anual_rolling(2028, 12, 2, 28, ultima_zi=True) == date(2029, 2, 28)


def test_ziua_termenului_nu_mai_decide_cand_flagul_e_pus():
    """
    `ziua_termenului` rămâne 28 în definiție doar fiindcă e câmp obligatoriu.
    Dovedim că NU el produce data — altfel cineva l-ar „repara" la 29 și ar strica
    anii nebisecți.
    """
    for zi_absurda in (1, 15, 28):
        assert _compute_termen_anual_rolling(
            BISECT, 1, 2, zi_absurda, ultima_zi=True
        ) == date(BISECT, 2, 29)


# ============================================================
#   2. D207 PE MOTORUL v2 (web, bannere, /api/v1/obligatii)
# ============================================================

def test_d207_poarta_flagul():
    d = DEFINITII_OBLIGATII["D207"]
    assert d.termen_in_ultima_zi_a_lunii is True
    assert d.luna_anuala_termen == 2


def test_d207_in_an_bisect_cade_pe_29():
    """REGRESIA. Venit 2027 → depunere în 2028 (bisect) → 29 februarie."""
    assert _termen_d207(NEBISECT) == date(BISECT, 2, 29)


def test_d207_in_an_nebisect_ramane_28():
    """Reparația nu trebuie să împingă totul pe 29."""
    assert _termen_d207(BISECT) == date(2029, 2, 28)
    assert _termen_d207(2025) == date(2026, 2, 28)


@pytest.mark.parametrize("an_venit", range(2024, 2036))
def test_d207_e_mereu_ultima_zi_reala_a_lunii(an_venit):
    """Invariant pe 12 ani: termenul e exact ultima zi din februarie, orice an."""
    t = _termen_d207(an_venit)
    assert t.month == 2
    assert t.year == an_venit + 1
    assert t.day == calendar.monthrange(t.year, 2)[1]


# ============================================================
#   3. CALEA v1 (Telegram) — și acordul dintre motoare
# ============================================================

def test_v1_calculeaza_acelasi_termen_ca_v2():
    """
    Cele două motoare nu au voie să diverge. `_compute_termen_anual_rolling` e sursa
    unică a regulii; flag-ul trebuia dus pe AMBELE drumuri, nu doar pe cel web —
    altfel botul ar fi spus 28 și dashboardul 29, în aceeași zi.

    Atenție la semnături, sunt DIFERITE (și au fost deja o sursă de bug, fiscal #7):
      • v1 `get_annual_alerts(year, today)` — `year` e anul CURENT, iar roll-forward-ul
        se face pe `today.month`. Botul îl cheamă cu anul de azi.
      • v2 `compute_obligation(def, an_venit, luna_ref, ...)` — `an_venit` e anul
        DECLARAT, iar `luna_ref` e luna de referință (12 = an încheiat).
    Comparăm deci ACELAȘI moment din calendar, exprimat în cele două convenții:
    ianuarie 2028, pentru veniturile lui 2027 → ambele trebuie să dea 29.02.2028.
    """
    today = date(BISECT, 1, 15)
    alerte = get_annual_alerts(BISECT, today=today)
    d207 = [a for a in alerte if a["code"] == "D207"]
    assert len(d207) == 1
    assert d207[0]["deadline"] == "29.02.2028"
    assert d207[0]["deadline"] == _termen_d207(NEBISECT, today=today).strftime("%d.%m.%Y")


def test_v1_are_flagul_in_dict():
    d207 = [d for d in ANNUAL_DEADLINES if d["code"] == "D207"]
    assert len(d207) == 1
    assert d207[0].get("ultima_zi") is True


# ============================================================
#   4. FLAG-UL NU SE SCURGE LA CELELALTE TERMENE ANUALE
# ============================================================

def test_d212_ramane_25_mai():
    """D212 e pe zi FIXĂ (25 mai). Dacă flag-ul s-ar aplica global, ar deveni 31."""
    assert DEFINITII_OBLIGATII["D212"].termen_in_ultima_zi_a_lunii is False
    o = compute_obligation(
        DEFINITII_OBLIGATII["D212"], 2027, 12, "PFA", "ridesharing",
        today=date(2027, 12, 31),
    )
    assert o.termen == date(BISECT, 5, 25)


def test_restul_termenelor_anuale_v1_neatinse():
    for d in ANNUAL_DEADLINES:
        if d["code"] == "D207":
            continue
        assert not d.get("ultima_zi"), f"{d['code']} a căpătat flagul din greșeală"


def test_o_singura_obligatie_poarta_flagul():
    """
    Ancoră: azi doar D207 are termen definit ca „ultima zi a lunii". Dacă mai apare
    una, e o decizie fiscală care merită citită, nu o extindere tăcută.
    """
    cu_flag = [k for k, d in DEFINITII_OBLIGATII.items() if d.termen_in_ultima_zi_a_lunii]
    assert cu_flag == ["D207"], cu_flag


# ============================================================
#   5. TEXTELE LIVRATE — să nu rămână „28" ca afirmație
# ============================================================

def test_textele_d207_nu_mai_promit_28():
    """
    `cand` și `descriere` ajung la user (/ghid, ambele suprafețe). Au voie să
    MENȚIONEZE 28, dar nu ca termen necondiționat — doar alături de 29 / bisect.
    """
    d = DEFINITII_OBLIGATII["D207"]
    for camp in ("cand", "descriere"):
        txt = getattr(d, camp)
        assert "ultima zi" in txt.lower(), f"D207.{camp} nu numește regula reală"
        if "28" in txt:
            assert "bisec" in txt.lower() or "29" in txt, (
                f"D207.{camp} spune 28 fără să spună că în anii bisecți e 29"
            )


def test_ghidul_generatorului_da_ziua_reala():
    """Ghidul de completare (Telegram + dashboard) calculează ziua, nu o scrie."""
    from app.integrations.anaf import d207_generator as g

    ident = g.IdentitateD207(
        cui="53067338", denumire="PFA TEST", adresa="BN Bistrita",
        nume_declarant="TEST", prenume_declarant="USER",
    )
    benef = [g.BeneficiarD207(
        tip_venit="04", denumire="BOLT OPERATIONS OU", stat="EE",
        cif_strain="102090374", baza=1000, impozit=20, act_n="2",
    )]

    # an de venit 2027 → depunere 2028 (bisect) → 29 februarie
    txt = g.genereaza_ghid_d207(identitate=ident, beneficiari=benef, an=NEBISECT, plain=True)
    assert "29 februarie 2028" in txt
    assert "ultima zi a lunii februarie" in txt

    # an de venit 2028 → depunere 2029 (nebisect) → 28 februarie
    txt2 = g.genereaza_ghid_d207(identitate=ident, beneficiari=benef, an=BISECT, plain=True)
    assert "28 februarie 2029" in txt2
