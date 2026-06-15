"""
Fiscal #3 — SUB-PAS B: calcul D100 rate-aware (cota din profil, nu 2% fix).

Acoperă cele 4 ramuri pe lanțul declaratii_service.genereaza("D100", ...,
cota_nerezident=...) + garda dublă care face IMPOSIBIL un XML la cota 0/None:
  - 0.02 (Bolt cu certificat)   → XML, suma = round(baza×0.02)  [round-trip 2%]
  - 0.16 (Bolt fără certificat) → XML, suma = round(baza×0.16)
  - 0.0  (scutit, ex. Uber)     → generat=False, motiv "scutit", NICIUN XML (→ D207)
  - None (neconfigurat) → generat=False, motiv "neconfigurat", NICIUN XML

ATENȚIE rotunjire: D100 e în lei întregi. 657×0.02 = 13,14 → 13;
657×0.16 = 105,12 → 105. Testăm sumele rotunjite reale (date la ANAF).
"""

import pytest

from app.integrations.anaf import declaratii_service as decl
from app.integrations.anaf import d100_generator as d100

BAZA = 657  # comision Bolt ian. 2026 — din care venea „13 lei" la 2%


def _gen(cota, **kw):
    """genereaza D100 cu firma default (stefan), cota nerezident dată."""
    return decl.genereaza("D100", 2026, 1, BAZA, cota_nerezident=cota, **kw)


# ── Ramura cu generare (cota > 0) ───────────────────────────────────

def test_crf_2pct_round_trip_cu_vechiul_comportament():
    rez = _gen(0.02)
    assert rez.generat is True
    assert rez.suma_plata == 13.0           # round(657×0.02)=13, ca vechiul 2%
    assert rez.are_plata is True
    assert rez.xml and rez.nume_fisier_xml == "D100_2026_01.xml"
    assert 'suma_dat="13"' in rez.xml       # XML poartă suma corectă
    assert "2%" in rez.ghid_telegram        # cota afișată dinamic


def test_fara_crf_16pct():
    rez = _gen(0.16)
    assert rez.generat is True
    assert rez.suma_plata == 105.0          # round(657×0.16)=105
    assert 'suma_dat="105"' in rez.xml
    assert "16%" in rez.ghid_telegram
    # 16% dă mai mult decât 2% (rata vine din profil, nu fixă)
    assert rez.suma_plata > _gen(0.02).suma_plata


# ── Ramura scutit (cota 0) — NICIUN XML, trimite la D207 ────────────

def test_crf_scutit_nu_genereaza_xml():
    rez = _gen(0.0)
    assert rez.generat is False
    assert rez.motiv_negenerat == "scutit"
    assert rez.xml == ""                     # CRITIC: niciun XML
    assert rez.nume_fisier_xml == ""
    assert rez.are_plata is False and rez.suma_plata == 0.0
    assert "D207" in rez.ghid_telegram       # venitul scutit → D207


# ── Ramura neconfigurat (None) — NICIUN XML, prompt de setare ───────

def test_neconfigurat_nu_genereaza_xml():
    rez = _gen(None)
    assert rez.generat is False
    assert rez.motiv_negenerat == "neconfigurat"
    assert rez.xml == ""                     # CRITIC: niciun XML
    assert rez.nume_fisier_xml == ""
    assert "regim" in rez.ghid_telegram.lower()


def test_default_fara_cota_nu_presupune_2pct():
    # apel fără cota_nerezident (default None) → NU mai iese XML cu 2% presupus
    rez = decl.genereaza("D100", 2026, 1, BAZA)
    assert rez.generat is False
    assert rez.xml == ""


# ── Garda Strat 2 — generatorul refuză cota 0/None ──────────────────

def _ident():
    return d100.IdentitateD100(
        cui="12345678", denumire="X PFA", adresa="ADR",
        nume_declarant="A", prenume_declarant="B", functie_declarant="TITULAR",
    )


@pytest.mark.parametrize("cota", [0.0, None, -0.1])
def test_generator_refuza_cota_invalida(cota):
    # chiar dacă cineva ocolește service-ul, generatorul NU produce XML
    with pytest.raises(ValueError):
        d100.genereaza_d100(2026, 1, _ident(), BAZA, cota=cota)


@pytest.mark.parametrize("cota", [0.0, None, -0.1])
def test_calcul_refuza_cota_invalida(cota):
    with pytest.raises(ValueError):
        d100.calcul_impozit_nerezident(BAZA, cota)


def test_calcul_cota_pozitiva():
    assert d100.calcul_impozit_nerezident(657, 0.02) == 13.0
    assert d100.calcul_impozit_nerezident(657, 0.16) == 105.0


# ── Nicio rată hardcodată rămasă ────────────────────────────────────

def test_fara_constanta_hardcodata():
    assert not hasattr(d100, "COTA_NEREZIDENT_EE")
