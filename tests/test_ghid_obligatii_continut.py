"""
Ghid de obligații — sub-pas 1: CONȚINUT pedagogic în registru (fundație, inert).

DEFINITII_OBLIGATII îmbogățit cu câmpuri „profesor" (ce_e/cui_se_aplica/cand/
cum_depun/de_ce) + penalty_info complet pe toate. Sub-pasul 1 NU surfațează încă
(ecran/comandă vin în sub-pas 2) — doar verificăm că fundația e completă și corectă.

Backward-compat: câmpurile sunt Optional → consumatorii actuali (calendar/plăți,
care citesc nume/descriere) neatinși; testul lor (test_calendar_d100_cota etc.) rămâne verde.
"""

import pytest

from app.domain.fiscal_calendar import DEFINITII_OBLIGATII

_PEDAGOGIC = ("ce_e", "cui_se_aplica", "cand", "cum_depun", "de_ce")


@pytest.mark.parametrize("key", list(DEFINITII_OBLIGATII.keys()))
def test_fiecare_obligatie_are_campuri_pedagogice(key):
    d = DEFINITII_OBLIGATII[key]
    for camp in _PEDAGOGIC:
        val = getattr(d, camp)
        assert val and len(val.strip()) > 20, f"{key}.{camp} gol/prea scurt"


@pytest.mark.parametrize("key", list(DEFINITII_OBLIGATII.keys()))
def test_fiecare_obligatie_are_penalty_info(key):
    # Toate (inclusiv cele care erau goale: D207/D390/D300/D101/D700) au acum consecințe.
    d = DEFINITII_OBLIGATII[key]
    assert d.penalty_info and len(d.penalty_info.strip()) > 20, f"{key}.penalty_info gol"


# ── Spot-check conținut: ambele platforme + miezul „de ce TU" ──

def test_d100_ambele_platforme_si_de_ce_tu():
    d = DEFINITII_OBLIGATII["D100_634"]
    assert "Bolt" in d.de_ce and "Uber" in d.de_ce
    assert "Art.12" in d.de_ce and "art.7" in d.de_ce      # temei dublu Estonia/Olanda
    assert "de ce tu" in d.de_ce.lower() or "TINE" in d.de_ce  # mecanismul, nu doar enunțul
    assert "CUI" in d.cum_depun and "special" in d.cum_depun.lower()  # capcana reală (NU codul special)


def test_d212_bonificatie_si_cas_cass():
    d = DEFINITII_OBLIGATII["D212"]
    assert "15 aprilie" in d.de_ce and "3%" in d.de_ce
    assert "CAS" in d.de_ce and "CASS" in d.de_ce
    assert "cont" in d.cum_depun.lower() and "CNP" in d.cum_depun  # cont unic pe CNP


def test_d207_uber_scutit_se_declara():
    d = DEFINITII_OBLIGATII["D207"]
    assert "Uber" in d.de_ce and "scut" in d.de_ce.lower()  # scutirea se declară tot aici


def test_d301_taxare_inversa_neplatitor():
    d = DEFINITII_OBLIGATII["D301"]
    assert "invers" in d.de_ce.lower()                      # taxare inversă
    assert "neplătitor" in d.cui_se_aplica.lower() or "cod special" in d.cui_se_aplica.lower()
