"""
Cod TVA Bolt — sursă unică + consistență pe toate suprafețele (fix audit #2).

Valoare CORECTĂ confirmată la sursă (registru eston e-Äriregister + pagina oficială
Bolt pentru șoferi): EE102090374 (Bolt Operations OÜ). EE102094445 era un typo în
motorul VAT (BRAND_DATABASE) care se propaga prin posting în document.vat_id stocat.

Testul de CONSISTENȚĂ e cheia: toate locurile referențiază aceeași sursă unică, deci
nu mai pot diverge (la fel ca pentru cass_sus).
"""

from pathlib import Path

from app.domain.tax_rules import BOLT_VAT_ID, BOLT_VAT_ID_NUMERIC
from app.domain.vat_engine import BRAND_DATABASE
from app.domain import vat_engine
from app.integrations.anaf import d390_generator as d390

COD_CORECT = "EE102090374"
COD_NUMERIC = "102090374"
TYPO = "102094445"


def test_sursa_unica_valoare_corecta():
    assert BOLT_VAT_ID == COD_CORECT
    assert BOLT_VAT_ID_NUMERIC == COD_NUMERIC
    assert BOLT_VAT_ID_NUMERIC == BOLT_VAT_ID[2:]    # derivat → nu pot diverge


def test_toate_suprafetele_consistente():
    # CHEIA: toate locurile care expun codul Bolt → aceeași valoare unică
    assert BRAND_DATABASE["bolt operations"][1] == COD_CORECT
    assert BRAND_DATABASE["bolt technology"][1] == COD_CORECT
    assert d390.operator_bolt(baza_lei=657).cod_operator == COD_NUMERIC


def test_anti_typo_in_tot_codul_sursa():
    # gardian permanent: typo-ul (cod Bolt greșit) NU apare ca VALOARE în niciun .py din app/.
    # Excepție: migrations.py — migrarea de date (021) referențiază INTENȚIONAT typo-ul în
    # clauza WHERE ca să-l ELIMINE din `documents.vat_id` (opusul bug-ului). E o eliminare,
    # nu o folosire ca valoare → permisă.
    root = Path(__file__).resolve().parent.parent / "app"
    vinovate = []
    for py in root.rglob("*.py"):
        if "__pycache__" in str(py):
            continue
        if py.name == "migrations.py":
            continue
        if TYPO in py.read_text(encoding="utf-8"):
            vinovate.append(str(py.relative_to(root.parent)))
    assert not vinovate, f"Typo '{TYPO}' (cod Bolt greșit) reapărut în: {vinovate}"


def test_d390_xml_contine_codul_corect():
    # declarația care PLEACĂ la ANAF — trebuie să conțină codul corect, nu typo-ul
    identitate = d390.IdentitateDeclarant(
        cui="53148882", denumire="TEST PFA", adresa="JUD X",
        nume_declarant="TEST", prenume_declarant="USER",
    )
    xml = d390.genereaza_d390(an=2026, luna=1, identitate=identitate,
                              operatori=[d390.operator_bolt(baza_lei=657)], d_rec=0)
    assert COD_NUMERIC in xml
    assert TYPO not in xml


def test_motor_vat_autocompleteaza_codul_corect():
    # factură Bolt FĂRĂ VAT ID explicit → analyze() auto-completează din BRAND_DATABASE
    # (acest detected_vat_id e cel persistat de posting pe document.vat_id)
    dec = vat_engine.analyze(platforma="Bolt Operations OU")
    assert dec.detected_vat_id == COD_CORECT
