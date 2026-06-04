"""
Sursa UNICA pentru etichetele RO ale codurilor tehnice (tip tranzactie, tratament
TVA, status document, metoda de plata) + traducere categorie cu fallback.

Modul PUR — fara I/O, fara DB. Primeste `activity` ca parametru (nu-l rezolva).

PRINCIPIU anti-duplicare:
- Categoriile de cheltuieli/venituri au DEJA label RO in activitati
  (app.activities.*). category_label() le citeste de acolo — NU le copiaza aici.
- CATEGORY_RO_FALLBACK contine DOAR coduri orfane (sintetice din posting.py care
  nu exista ca ExpenseCategory/IncomeCategory), ex. reverse_charge_vat.
- Pentru codurile pur transversale (tx_type, vat_treatment, status, plata) acest
  modul e singura sursa.

Nicio functie nu arunca exceptie: cod necunoscut -> _humanize (lizibil).
"""

# ============================================================
#            DICTIONARE — coduri transversale
# ============================================================

TX_TYPE_RO = {
    "INCOME":  "Venit",
    "EXPENSE": "Cheltuială",
    "VAT_OUT": "TVA colectat",
    "VAT_IN":  "TVA deductibil",
}

VAT_TREATMENT_RO = {                    # din VATTreatment (app.activities.base)
    "NA":             "Nu se aplică",
    "STANDARD_21":    "TVA standard 21%",
    "STANDARD_19":    "TVA standard 19%",
    "REDUCED_9":      "TVA redus 9%",
    "REDUCED_5":      "TVA redus 5%",
    "REVERSE_CHARGE": "TVA taxare inversă",
    "EXEMPT_ART_292": "Scutit fără drept de deducere",
    "EXEMPT_ART_294": "Scutit cu drept de deducere",
}

DOC_STATUS_RO = {                       # din DocStatus (app.enums)
    "draft":        "Ciornă",
    "needs_review": "De verificat",
    "confirmed":    "Confirmat",
    "posted":       "Înregistrat",
    "exported":     "Exportat",
    "rejected":     "Respins",
}

PAYMENT_RO = {                          # din PaymentMethod (app.enums)
    "CASH":    "Numerar",
    "CARD":    "Card",
    "BANK":    "Transfer bancar",
    "APP":     "Plată în aplicație",
    "UNKNOWN": "Necunoscut",
}

# DOAR coduri orfane (nu exista ca label in activitati). NU duplica aici
# categoriile de activitate (fuel, car_service, ride_revenue...) — sursa lor
# ramane activitatea.
CATEGORY_RO_FALLBACK = {
    "reverse_charge_vat": "TVA taxare inversă",
}


# ============================================================
#                       HELPERS
# ============================================================

def _humanize(code: str) -> str:
    """Fallback final lizibil: 'some_code' -> 'Some code'."""
    return str(code).replace("_", " ").strip().capitalize()


def category_label(code, activity=None) -> str:
    """
    Eticheta RO a unei categorii de tranzactie, cu fallback in cascada:
      1. activity.get_expense_category(code).label   (sursa existenta)
      2. activity.get_income_category(code).label
      3. CATEGORY_RO_FALLBACK[code]                   (coduri orfane)
      4. _humanize(code)                              (fallback final)

    code gol/None -> "—".
    """
    if not code:
        return "—"

    if activity is not None:
        cat = activity.get_expense_category(code)
        if cat is not None and cat.label:
            return cat.label
        cat = activity.get_income_category(code)
        if cat is not None and cat.label:
            return cat.label

    if code in CATEGORY_RO_FALLBACK:
        return CATEGORY_RO_FALLBACK[code]

    return _humanize(code)


def tx_type_label(code) -> str:
    """Eticheta RO a tipului de tranzactie (INCOME/EXPENSE/VAT_OUT/VAT_IN)."""
    if not code:
        return "—"
    return TX_TYPE_RO.get(code, _humanize(code))


def vat_treatment_label(code) -> str:
    """Eticheta RO a tratamentului TVA. None/gol -> '' (multe tranzactii n-au)."""
    if not code:
        return ""
    return VAT_TREATMENT_RO.get(code, _humanize(code))


def doc_status_label(code) -> str:
    """Eticheta RO a statusului unui document."""
    if not code:
        return "—"
    return DOC_STATUS_RO.get(code, _humanize(code))


def payment_label(code) -> str:
    """Eticheta RO a metodei de plata."""
    if not code:
        return "—"
    return PAYMENT_RO.get(code, _humanize(code))
