"""
Teste pentru sursa unica de etichete RO (Faza 1, #1).

Verifica: traduceri coduri transversale, fallback orfan (reverse_charge_vat),
fallback final pe cod necunoscut (nu crapa), si — important — ca o categorie
care exista in activitate intoarce label-ul ACTIVITATII, NU fallback-ul
(dovada ca NU duplicam sursa).
"""

import pytest

from app.domain import labels_ro
from app.activities.ridesharing import RidesharingActivity


# ────────────────────────────────────────────────────────────
# category_label — sursa activitate are prioritate
# ────────────────────────────────────────────────────────────

def test_categorie_din_activitate_nu_fallback():
    # "fuel" exista in activitate -> intoarce label-ul activitatii, NU _humanize
    out = labels_ro.category_label("fuel", RidesharingActivity)
    assert out == "Combustibil auto"
    assert out != "Fuel"  # NU fallback-ul humanize


def test_categorie_venit_din_activitate():
    assert labels_ro.category_label("ride_revenue", RidesharingActivity) == "Venituri brute curse"
    assert labels_ro.category_label("tip_revenue", RidesharingActivity) == "Bacșișuri"


def test_categorie_orfana_reverse_charge_vat():
    # nu exista in nicio activitate -> fallback dict
    assert labels_ro.category_label("reverse_charge_vat", RidesharingActivity) == "TVA taxare inversă"
    # si fara activitate
    assert labels_ro.category_label("reverse_charge_vat") == "TVA taxare inversă"


def test_categorie_necunoscuta_humanize():
    assert labels_ro.category_label("cod_nou_necunoscut") == "Cod nou necunoscut"


def test_categorie_goala_sau_none():
    assert labels_ro.category_label("") == "—"
    assert labels_ro.category_label(None) == "—"


def test_categorie_fara_activitate_dar_orfana():
    # fuel fara activitate -> nu e in fallback -> humanize
    assert labels_ro.category_label("fuel") == "Fuel"


# ────────────────────────────────────────────────────────────
# tx_type_label
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code, asteptat", [
    ("INCOME", "Venit"),
    ("EXPENSE", "Cheltuială"),
    ("VAT_OUT", "TVA colectat"),
    ("VAT_IN", "TVA deductibil"),
])
def test_tx_type_label(code, asteptat):
    assert labels_ro.tx_type_label(code) == asteptat


def test_tx_type_necunoscut_si_gol():
    assert labels_ro.tx_type_label("CEVA_NOU") == "Ceva nou"
    assert labels_ro.tx_type_label(None) == "—"


# ────────────────────────────────────────────────────────────
# vat_treatment_label — None -> "" (gol)
# ────────────────────────────────────────────────────────────

def test_vat_treatment_label():
    assert labels_ro.vat_treatment_label("REVERSE_CHARGE") == "TVA taxare inversă"
    assert labels_ro.vat_treatment_label("STANDARD_21") == "TVA standard 21%"
    assert labels_ro.vat_treatment_label("EXEMPT_ART_292") == "Scutit fără drept de deducere"


def test_vat_treatment_none_e_gol():
    assert labels_ro.vat_treatment_label(None) == ""
    assert labels_ro.vat_treatment_label("") == ""


def test_vat_treatment_necunoscut_humanize():
    assert labels_ro.vat_treatment_label("CEVA") == "Ceva"


# ────────────────────────────────────────────────────────────
# payment_label / doc_status_label
# ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("code, asteptat", [
    ("CASH", "Numerar"),
    ("CARD", "Card"),
    ("BANK", "Transfer bancar"),
    ("APP", "Plată în aplicație"),
    ("UNKNOWN", "Necunoscut"),
])
def test_payment_label(code, asteptat):
    assert labels_ro.payment_label(code) == asteptat


@pytest.mark.parametrize("code, asteptat", [
    ("draft", "Ciornă"),
    ("needs_review", "De verificat"),
    ("confirmed", "Confirmat"),
    ("posted", "Înregistrat"),
    ("exported", "Exportat"),
    ("rejected", "Respins"),
])
def test_doc_status_label(code, asteptat):
    assert labels_ro.doc_status_label(code) == asteptat


def test_payment_status_fallback_nu_crapa():
    assert labels_ro.payment_label("CEVA") == "Ceva"
    assert labels_ro.payment_label(None) == "—"
    assert labels_ro.doc_status_label("ceva_nou") == "Ceva nou"
    assert labels_ro.doc_status_label(None) == "—"
