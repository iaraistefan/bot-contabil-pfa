"""
Fiscal #1 — cota TVA în generarea XML D301/D390/D100 (back-out al bazei din TVA).

BUG (bot_contabil.py:1447, REPARAT): `baza = round(vat_out / 0.21, 2)` — cotă
hardcodată. Pe luni cu 19% (înainte de 01.08.2025) baza ieșea prea mică → XML
subdeclara ȘI baza ȘI TVA (~9,5%). Fix: cota din sursa unică (totals["cota_tva"]
= tax_rules.cota_tva(data)), aceeași pe care o folosește și generatorul.

Testele alimentează GENERATORUL REAL (`declaratii_service.genereaza`) cu baza
calculată cu o cotă dată și verifică round-trip-ul vat_out → baza → tva_xml.

Producția (după fix) folosește cota_tva(data lunii) → exact `cota_fix` de mai jos.
"""

import re
from datetime import date

import pytest

from app.integrations.anaf import declaratii_service as decl
from app.domain.tax_rules import cota_tva


def _xml_attr(xml: str, name: str) -> float:
    m = re.search(rf'\b{name}="([\d.]+)"', xml)
    assert m, f"atributul {name} lipsește din XML"
    return float(m.group(1))


def _genereaza(vat_out: float, an: int, luna: int, cota: float):
    """Generează D301 cu baza = round(vat_out / cota, 2); întoarce (baza_xml, tva_xml)."""
    baza = round(vat_out / cota, 2)
    rez = decl.genereaza("D301", an=an, luna=luna, baza_intracom_lei=baza)
    return _xml_attr(rez.xml, "baza4"), _xml_attr(rez.xml, "tva4")


VAT_OUT_19 = 1900.0   # iulie 2025 (19%): baza reală = 1900/0.19 = 10.000
VAT_OUT_21 = 2100.0   # august 2025 (21%): baza reală = 2100/0.21 = 10.000


# ============================================================
#  FIX (= producția): cota_tva pe dată → round-trip corect pe AMBELE cote.
#  Testul "A" (19%) — pica pe /0.21, TRECE acum prin cota_tva. Plus "B" (21%).
# ============================================================
@pytest.mark.parametrize("vat_out,an,luna,cota", [
    (VAT_OUT_19, 2025, 7, 0.19),   # A: luna care pica pe codul vechi
    (VAT_OUT_21, 2025, 8, 0.21),   # B: regresie 21%
])
def test_fix_cota_tva_roundtrip(vat_out, an, luna, cota):
    assert cota_tva(date(an, luna, 1)) == cota               # cota corectă a lunii
    cota_fix = cota_tva(date(an, luna, 1))                   # exact ca producția
    baza_xml, tva_xml = _genereaza(vat_out, an, luna, cota_fix)
    assert baza_xml == pytest.approx(round(vat_out / cota))  # baza corectă
    assert tva_xml == pytest.approx(vat_out, abs=0.5)        # round-trip → vat_out


# ============================================================
#  BUG documentat permanent: /0.21 pe lună de 19% subdeclară baza ȘI TVA.
# ============================================================
def test_021_subdeclara_pe_19pct():
    baza_021, tva_021 = _genereaza(VAT_OUT_19, 2025, 7, 0.21)
    baza_corect = round(VAT_OUT_19 / 0.19)        # 10.000
    assert baza_021 < baza_corect                 # 9048 < 10000 (bază prea mică)
    assert tva_021 < VAT_OUT_19                    # ~1719 < 1900 (TVA subdeclarat)


# ============================================================
#  REGRESIE: pe 21% fixul (cota_tva) == vechiul /0.21 (XML neschimbat).
# ============================================================
def test_21pct_fix_identic_cu_021():
    b_fix, t_fix = _genereaza(VAT_OUT_21, 2025, 8, cota_tva(date(2025, 8, 1)))
    b_old, t_old = _genereaza(VAT_OUT_21, 2025, 8, 0.21)
    assert (b_fix, t_fix) == (b_old, t_old)
