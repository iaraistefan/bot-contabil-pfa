"""
Orchestrare Uber în D390 + D301 (fix furnizor per-brand).

CONTEXT: înainte de fix, `declaratii_service.genereaza` hardcoda operatorul Bolt
(`operatori = [operator_bolt(baza)]`) → un șofer Uber primea furnizor GREȘIT în D390
(BOLT OPERATIONS OU / EE în loc de UBER B.V. / NL). Motorul de decizie (vat_engine)
știa deja Uber=NL; lipsea doar construcția operatorului Uber în orchestrare.

Fix: `genereaza(...)` acceptă `intracom_by_brand={brand: vat_out}` și construiește
un operator (D390) + o factură (D301) PE furnizor, împărțind baza proporțional
(Σ == baza). Neatribuit (cheia None) → OPREȘTE (opțiunea b), nu declară incomplet.

Regresie: fără `intracom_by_brand` (=None) → calea Bolt-only pe scalar, identică.
"""

import re
from datetime import date

import pytest

from app.integrations.anaf import declaratii_service as decl
from app.integrations.anaf import d390_generator as d390
from app.domain.tax_rules import UBER_VAT_ID_NUMERIC, BOLT_VAT_ID_NUMERIC


def _operatii(xml: str):
    """Extrage lista de <operatie .../> (tara, codO, denO, baza) din XML-ul D390."""
    out = []
    for m in re.finditer(r"<operatie\b([^/]*)/>", xml):
        blob = m.group(1)
        attr = dict(re.findall(r'(\w+)="([^"]*)"', blob))
        out.append(attr)
    return out


# ============================================================
# 1. operator_uber() — identitate NL din sursă unică (BRAND_DATABASE/tax_rules)
# ============================================================
def test_operator_uber_identitate_din_sursa_unica():
    op = d390.operator_uber(5000)
    assert op.tip == "S"                       # achiziție intracom de servicii
    assert op.tara == "NL"                      # Olanda, NU EE
    assert op.cod_operator == "852071589B01"    # fără prefix NL
    assert op.cod_operator == UBER_VAT_ID_NUMERIC   # sursă unică
    assert op.denumire == "UBER B.V."           # denumire legală
    assert op.baza == 5000


def test_operator_for_brand_dispatch_si_necunoscut():
    assert d390.operator_for_brand("uber", 100).tara == "NL"
    assert d390.operator_for_brand("Uber Eats", 100).tara == "NL"  # orice „uber…"
    assert d390.operator_for_brand("bolt", 100).tara == "EE"
    with pytest.raises(ValueError):
        d390.operator_for_brand("glovo", 100)      # brand necunoscut → nu presupunem


# ============================================================
# 2. D390 cu Bolt + Uber → 2 operatori (EE + NL), coduri corecte
# ============================================================
def test_d390_doua_branduri_doi_operatori():
    rez = decl.genereaza(
        "D390", an=2026, luna=7, baza_intracom_lei=1000,
        intracom_by_brand={"bolt": 700.0, "uber": 300.0},
    )
    ops = _operatii(rez.xml)
    assert len(ops) == 2
    tari = {o["tara"] for o in ops}
    assert tari == {"EE", "NL"}
    coduri = {o["tara"]: o["codO"] for o in ops}
    assert coduri["EE"] == BOLT_VAT_ID_NUMERIC
    assert coduri["NL"] == UBER_VAT_ID_NUMERIC
    denumiri = {o["denO"] for o in ops}
    assert "UBER B.V." in denumiri and "BOLT OPERATIONS OU" in denumiri


# ============================================================
# 3. D390 Bolt-only scalar (intracom_by_brand=None) == comportamentul de azi
# ============================================================
def test_d390_bolt_only_scalar_regresie():
    rez = decl.genereaza("D390", an=2026, luna=7, baza_intracom_lei=1000)  # fără by_brand
    ops = _operatii(rez.xml)
    assert len(ops) == 1
    assert ops[0]["tara"] == "EE"
    assert ops[0]["codO"] == BOLT_VAT_ID_NUMERIC
    assert ops[0]["denO"] == "BOLT OPERATIONS OU"
    assert int(ops[0]["baza"]) == 1000


def test_d390_bolt_only_via_by_brand_identic_cu_scalar():
    """{'bolt': X} (un singur brand) → identic cu calea scalară Bolt-only."""
    scalar = decl.genereaza("D390", an=2026, luna=7, baza_intracom_lei=1000)
    prin_brand = decl.genereaza(
        "D390", an=2026, luna=7, baza_intracom_lei=1000,
        intracom_by_brand={"bolt": 900.0, None: 0.0},
    )
    assert _operatii(scalar.xml) == _operatii(prin_brand.xml)


# ============================================================
# 4. D301 cu Uber → nr_doc etichetat UBER-…
# ============================================================
def test_d301_uber_eticheta_nr_doc():
    rez = decl.genereaza(
        "D301", an=2026, luna=7, baza_intracom_lei=500,
        intracom_by_brand={"uber": 500.0},
    )
    assert "UBER-2026-07" in rez.xml
    assert "BOLT-2026-07" not in rez.xml


def test_d301_bolt_only_scalar_regresie():
    rez = decl.genereaza("D301", an=2026, luna=7, baza_intracom_lei=500)
    assert "BOLT-2026-07" in rez.xml


# ============================================================
# 5. Invariant: Σ baza_b == baza agregată (niciun leu pierdut, inclusiv cu rezidual)
# ============================================================
@pytest.mark.parametrize("baza,by_brand", [
    (1000, {"bolt": 700.0, "uber": 300.0}),
    (999,  {"bolt": 500.0, "uber": 500.0}),   # forțează rezidual de rotunjire
    (1234, {"bolt": 1000.0, "uber": 234.0}),
])
def test_d390_invariant_suma_baze(baza, by_brand):
    rez = decl.genereaza("D390", an=2026, luna=7, baza_intracom_lei=baza,
                         intracom_by_brand=by_brand)
    ops = _operatii(rez.xml)
    assert sum(int(o["baza"]) for o in ops) == baza          # niciun leu pierdut
    assert all(int(o["baza"]) > 0 for o in ops)              # niciun operator gol


def test_d301_invariant_suma_valori():
    # Sume asimetrice → două facturi distincte (700 + 300). D301 listează fiecare
    # factură în două secțiuni (S4 + S4.1), deci folosim SETUL de valori distincte
    # ca să nu numărăm dublu; Σ pe set == baza (niciun leu pierdut).
    rez = decl.genereaza("D301", an=2026, luna=7, baza_intracom_lei=1000,
                         intracom_by_brand={"bolt": 700.0, "uber": 300.0})
    valori = {float(m) for m in re.findall(r'val_valuta="([\d.]+)"', rez.xml)}
    assert valori == {700.0, 300.0}
    assert round(sum(valori), 2) == 1000.0


# ============================================================
# 6. Backward-compat: apel scalar fără intracom_by_brand → Bolt
# ============================================================
def test_backward_compat_scalar_ambele():
    d390_rez = decl.genereaza("D390", an=2026, luna=7, baza_intracom_lei=800)
    d301_rez = decl.genereaza("D301", an=2026, luna=7, baza_intracom_lei=800)
    assert "BOLT OPERATIONS OU" in d390_rez.xml
    assert "BOLT-2026-07" in d301_rez.xml


# ============================================================
# 7. Brand neatribuit (None cu vat>0) → OPREȘTE (opțiunea b), NU generează XML
# ============================================================
@pytest.mark.parametrize("tip", ["D390", "D301"])
def test_neatribuit_opreste_cu_mesaj(tip):
    with pytest.raises(ValueError) as ei:
        decl.genereaza(tip, an=2026, luna=7, baza_intracom_lei=1000,
                       intracom_by_brand={"bolt": 600.0, None: 400.0})
    msg = str(ei.value).lower()
    assert "platform" in msg           # cere atribuirea platformei
    assert "400" in str(ei.value)      # menționează suma neatribuită


def test_neatribuit_total_opreste():
    """Tot VAT_OUT neatribuit → oprește (nu cade tăcut pe Bolt)."""
    with pytest.raises(ValueError):
        decl.genereaza("D390", an=2026, luna=7, baza_intracom_lei=1000,
                       intracom_by_brand={None: 1000.0})
