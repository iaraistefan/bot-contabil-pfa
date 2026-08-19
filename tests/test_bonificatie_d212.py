"""
GARDIAN — bonificația NU se calculează, NU se afișează, NU intră în XML.

Fișierul ăsta bloca înainte *forma* bonificației (3% pe impozit, nu pe total).
Acum blochează *existența* ei. Motivul e în NOTA-BONIFICATIE din
`app/integrations/anaf/d212_calc.py`, pe scurt: art. 121 Cod fiscal e cadru
inert, se activează doar prin act anual, iar singura activare recentă
(OUG 8/2026 art. 8, pentru veniturile 2025) a avut termen 15 aprilie 2026 —
expirat. Pentru 2026 nu există nimic.

Gaura pe care o păzim NU e „procent greșit". E: o reducere necondiționată
intra în declarația depusă (bifa18=1 + oblimpozit_real_bonif), deci omul
declara mai puțin decât datorează. Cele trei gardieni de mai jos, în ordinea
gravității:
  1. XML-ul — verificat prin INJECTARE (rezultat fabricat care CERE bonificație)
  2. Totalul de plată — nediminuat, pe orice an
  3. Vocabularul — repo-wide, ca să nu reapară pe altă suprafață
"""

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.integrations.anaf import d212_generator as d212
from app.integrations.anaf.d212_calc import calculeaza_d212

RADACINA = Path(__file__).resolve().parents[1]
APP = RADACINA / "app"

MARCAJ_START = "==== NOTA-BONIFICATIE — START"
MARCAJ_STOP = "==== NOTA-BONIFICATIE — STOP"
FISIER_NOTA = APP / "integrations" / "anaf" / "d212_calc.py"


# ════════════════════════════════════════════════════════════
#   1. XML — gardian prin INJECTARE
# ════════════════════════════════════════════════════════════

@dataclass
class RezultatCuBonificatie:
    """Rezultat FABRICAT care cere explicit o bonificație.

    Are atributul `bonificatie` pe o valoare mare și necredibilă. Dacă
    generatorul îl citește în vreun fel — atribut, bifă, sumar — testul cade.
    Un rezultat real nu mai are câmpul deloc; ăsta îl are ca să dovedească nu
    doar că nu-l calculăm, ci că nu-l *consumăm* nici dacă i se pune în față.
    """
    venit_brut: float = 120000
    cheltuieli: float = 45000
    venit_net: float = 75000
    cas: float = 12150
    cas_baza: float = 48600
    cass: float = 7500
    cass_baza: float = 75000
    venit_impozabil: float = 55350
    impozit: float = 5535
    bonificatie: float = 9999          # ← injecția
    total_cu_bonificatie: float = 1
    salariu_minim: int = 4050
    regim: str = "SISTEM_REAL"


# Identitatea/activitatea sunt aceleași cu ale suitei de generator — refolosite,
# nu re-inventate: o a doua definiție ar diverge tăcut de forma pe care XSD-ul
# și Schematron-ul o acceptă acolo.
from tests.test_d212_generator import _identitate, _activitate  # noqa: E402


def _xml(rezultat, an=2025):
    return d212.genereaza_d212(
        an_venituri=an, identitate=_identitate(),
        activitate=_activitate(), rezultat=rezultat,
    )


def _atribute(xml: str, tag: str) -> dict:
    m = re.search(rf"<{tag}\b([^>]*)/?>", xml)
    return dict(re.findall(r'([\w\-]+)="([^"]*)"', m.group(1))) if m else {}


def test_xml_nu_contine_oblimpozit_real_bonif_nici_sub_injectare():
    """XSD îl dă use='optional' → absența e validă. Absent trebuie să fie."""
    xml = _xml(RezultatCuBonificatie())
    assert "oblimpozit_real_bonif" not in xml, (
        "câmpul de bonificație a reintrat în XML — vezi NOTA-BONIFICATIE")


def test_xml_are_bifa18_pe_zero_nici_sub_injectare():
    """XSD o dă use='required' → atributul rămâne, dar pe 0, nu pe 1."""
    radacina = _atribute(_xml(RezultatCuBonificatie()), "d212")
    assert radacina["bifa18"] == "0", (
        f"bifa18={radacina['bifa18']} — declarația cere o secțiune fără temei legal")


def test_xml_pe_calcul_real_e_curat_de_bonificatie():
    """Nu doar sub injectare: și pe drumul normal, cu cifre reale."""
    r = calculeaza_d212(venit_brut=120000, cheltuieli_deductibile=45000, an=2025)
    xml = _xml(r)
    assert "oblimpozit_real_bonif" not in xml
    assert _atribute(xml, "d212")["bifa18"] == "0"
    assert 'bifa18="1"' not in xml


def test_ghidul_xml_nu_promite_bonificatie():
    r = calculeaza_d212(venit_brut=120000, cheltuieli_deductibile=45000, an=2025)
    for plain in (True, False):
        text = d212.genereaza_ghid_d212(2025, r, plain=plain)
        assert "bonific" not in text.lower(), text


# ════════════════════════════════════════════════════════════
#   2. TOTALUL DE PLATĂ — nediminuat, pe orice an
# ════════════════════════════════════════════════════════════

@pytest.mark.parametrize("an", [2025, 2026, 2027])
def test_total_plata_e_suma_curata_pe_orice_an(an):
    """total_plata == CAS + CASS + impozit. Fără scădere, fără excepție de an.

    Bug-ul original nu era pe un an anume: `impozit * 0.03` se aplica pentru
    orice `an` primit, deci și pe estimările 2026 de pe dashboard.
    """
    r = calculeaza_d212(venit_brut=120000, cheltuieli_deductibile=45000, an=an)
    assert r.total_plata == round(r.cas + r.cass + r.impozit, 2)
    assert r.total_plata > r.impozit


@pytest.mark.parametrize("an", [2025, 2026, 2027])
def test_rezultatul_nu_mai_expune_campuri_de_bonificatie(an):
    r = calculeaza_d212(venit_brut=120000, cheltuieli_deductibile=45000, an=an)
    assert not hasattr(r, "bonificatie")
    assert not hasattr(r, "total_cu_bonificatie")


def test_ghidul_de_estimare_nu_promite_bonificatie():
    from app.integrations.anaf.d212_calc import genereaza_ghid_d212
    r = calculeaza_d212(venit_brut=120000, cheltuieli_deductibile=45000, an=2026)
    for plain in (True, False):
        text = genereaza_ghid_d212(r, plain=plain)
        assert "bonific" not in text.lower()
        assert "15 aprilie" not in text


# ════════════════════════════════════════════════════════════
#   3. VOCABULAR — gardian repo-wide
# ════════════════════════════════════════════════════════════

def _linii_in_afara_notei(cale: Path):
    """Liniile fișierului, fără blocul NOTA-BONIFICATIE (marcaje incluse)."""
    in_nota = False
    for i, linie in enumerate(cale.read_text(encoding="utf-8").splitlines(), 1):
        if MARCAJ_START in linie:
            in_nota = True
        if in_nota:
            if MARCAJ_STOP in linie:
                in_nota = False
            continue
        yield i, linie


def test_bonificatia_nu_mai_apare_in_cod_de_productie():
    """Excepție motivată, în stilul TEMEI-NEVERIFICAT: un singur loc unde
    cuvântul are voie să existe — nota explicativă din d212_calc.py — plus
    trimiterile la ea prin marcajul `NOTA-BONIFICATIE`. Orice altă apariție
    e o suprafață care a reînviat cifra."""
    aparitii = []
    for cale in sorted(list(APP.rglob("*.py")) + list(APP.rglob("*.html"))):
        for nr, linie in _linii_in_afara_notei(cale):
            if "bonific" not in linie.lower():
                continue
            # trimiterea la notă e permisă: marcajul e chiar mecanismul de urmărire
            if "bonific" not in linie.replace("NOTA-BONIFICATIE", "").lower():
                continue
            aparitii.append(f"{cale.relative_to(RADACINA)}:{nr}: {linie.strip()}")
    assert aparitii == [], (
        "bonificatia a reaparut in cod de productie:\n" + "\n".join(aparitii))


def test_nota_explicativa_exista_si_e_completa():
    """Nota e singura excepție — deci ștergerea ei ar deschide gardianul de mai
    sus fără să pice nimic. Îl legăm de existența notei."""
    text = FISIER_NOTA.read_text(encoding="utf-8")
    assert MARCAJ_START in text and MARCAJ_STOP in text
    nota = text.split(MARCAJ_START)[1].split(MARCAJ_STOP)[0]
    for reper in ("art. 121", "OUG 8/2026", "15 aprilie 2026",
                  "PROIECTIE CONDITIONATA", "CAS"):
        assert reper in nota, f"nota a pierdut reperul: {reper}"


def test_constanta_de_bonificatie_nu_mai_exista():
    from app.integrations.anaf import d212_calc
    assert not hasattr(d212_calc, "COTA_BONIFICATIE")
