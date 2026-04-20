"""
Reguli fiscale pure pentru PFA Ridesharing România 2026.

PRINCIPII:
- Fără I/O, fără DB, fără imports din aplicație.
- Toate funcțiile returnează valori simple (float, bool, str).
- Toate valorile procentuale sunt parametrizabile — legea se poate schimba.
- Documentat cu referințe la codul fiscal / ANAF unde e relevant.

CONTEXT LEGAL (2026):
- Cota TVA standard: 21% (modificată prin OUG nr. 115/2023, aplicabilă din 01.01.2024).
- Comisioane Bolt/Uber: servicii intracomunitare → taxare inversă (art. 307 alin. 2 Cod Fiscal).
  Beneficiarul (șoferul PFA) aplică TVA → VAT_OUT în D301, VAT_IN dacă e plătitor TVA.
- Cheltuieli auto: 50% deductibile pentru vehicule folosite mixt (art. 25 alin. 3 lit. l Cod Fiscal).
  Dacă vehiculul e exclusiv profesional + dovadă → 100%. Presupunem mixt ca default sigur.
- Impozit nerezidenți (withholding): 2% din comision (convenție fiscală România-Estonia).
  Informativ — nu generăm tranzacție separată acum, va fi la D390.
"""

from typing import Optional

# --- Constante fiscale 2026 ---
VAT_STANDARD_PCT = 21          # Cota TVA standard (%)
VAT_REVERSE_CHARGE_PCT = 21    # Taxare inversă — aceeași cotă
FUEL_DEDUCTIBLE_PCT = 50       # Deductibilitate auto mixtă (%)
WITHHOLDING_TAX_PCT = 2        # Impozit nerezidenți (informativ)

# Prefixe de VAT ID ale țărilor UE (fără România).
# Serviciile facturate de entități cu aceste prefixe = servicii intracomunitare.
EU_VAT_PREFIXES = {
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI",
    "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
    "NL", "PL", "PT", "SE", "SI", "SK",
    # Notă: RO = România (nu intracomunitar față de noi)
}


def apply_reverse_charge(
    amount_net: float,
    vat_pct: int = VAT_REVERSE_CHARGE_PCT,
) -> float:
    """
    Calculează TVA-ul de aplicat prin taxare inversă pe o sumă netă.

    Utilizare: comisioane Bolt/Uber (servicii intracomunitare).
    PFA-ul e obligat să declare și să plătească acest TVA la ANAF (D301).

    Args:
        amount_net: Suma fără TVA (ex: 346.81 RON).
        vat_pct: Cota TVA (default 21%).

    Returns:
        Suma TVA (ex: 72.83 RON).

    >>> apply_reverse_charge(346.81)
    72.83
    """
    vat = round(amount_net * vat_pct / 100, 2)
    return vat


def fuel_deductible_share(
    amount_brut: float,
    deductible_pct: int = FUEL_DEDUCTIBLE_PCT,
) -> float:
    """
    Calculează suma efectiv deductibilă dintr-o cheltuială de combustibil/auto.

    Default 50% pentru vehicule cu utilizare mixtă (profesional + personal).
    Poate fi suprascris la 100% dacă există dovezi de utilizare exclusiv profesională.

    Args:
        amount_brut: Suma totală a bonului (ex: 300.57 RON).
        deductible_pct: Procentul deductibil (default 50%).

    Returns:
        Suma deductibilă (ex: 150.29 RON).

    >>> fuel_deductible_share(300.57)
    150.29
    """
    return round(amount_brut * deductible_pct / 100, 2)


def is_intra_eu_commission(vendor_vat_id: Optional[str]) -> bool:
    """
    Returnează True dacă VAT ID-ul furnizorului indică un serviciu intracomunitar.

    Logică: primele 2 caractere ale VAT ID = codul de țară.
    Ex: "EE102094445" → "EE" → Estonia → UE → True (Bolt Operations OÜ).
    Ex: "RO12345678"  → "RO" → România → False.
    Ex: None          → False (nu știm, tratăm conservator).

    Args:
        vendor_vat_id: VAT ID-ul furnizorului (cu sau fără spații).

    Returns:
        bool

    >>> is_intra_eu_commission("EE102094445")
    True
    >>> is_intra_eu_commission("RO12345678")
    False
    >>> is_intra_eu_commission(None)
    False
    """
    if not vendor_vat_id:
        return False
    cleaned = vendor_vat_id.strip().upper().replace(" ", "")
    if len(cleaned) < 2:
        return False
    country_code = cleaned[:2]
    return country_code in EU_VAT_PREFIXES


def withholding_tax(
    amount_net: float,
    pct: int = WITHHOLDING_TAX_PCT,
) -> float:
    """
    Impozit reținut la sursă pe comisioane plătite nerezidenților.

    Conform convenției de evitare a dublei impuneri România-Estonia (2%),
    Bolt reține 2% din comision și îl virează la Trezoreria României.
    Informativ — nu generăm tranzacție, apare în D390.

    Args:
        amount_net: Comisionul net (fără TVA).
        pct: Procentul de reținere (default 2%).

    Returns:
        Suma impozitului reținut.

    >>> withholding_tax(346.81)
    6.94
    """
    return round(amount_net * pct / 100, 2)


def compute_deductible_amount(
    amount_brut: float,
    deductible_pct: int,
) -> float:
    """
    Generic: calculează suma deductibilă din orice cheltuială.

    Args:
        amount_brut: Suma brută a cheltuielii.
        deductible_pct: Procentul de deductibilitate (0-100).

    Returns:
        Suma deductibilă.
    """
    return round(amount_brut * max(0, min(100, deductible_pct)) / 100, 2)
