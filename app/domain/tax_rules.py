"""
Reguli fiscale pure pentru PFA Ridesharing România 2026.

PRINCIPII:
- Fără I/O, fără DB, fără imports din aplicație.
- Toate funcțiile returnează valori simple (float, bool, str).
- Toate valorile procentuale sunt parametrizabile — legea se poate schimba.
- Documentat cu referințe la codul fiscal / ANAF unde e relevant.

CONTEXT LEGAL (2026):
- Cota TVA standard: 21% în vigoare din 01.08.2025; 19% până la 31.07.2025.
  Sursa unică de adevăr pentru cotă în funcție de dată: cota_tva(data).
- Comisioane Bolt/Uber: servicii intracomunitare → taxare inversă (art. 307 alin. 2 Cod Fiscal).
  Beneficiarul (șoferul PFA) aplică TVA → VAT_OUT în D301, VAT_IN dacă e plătitor TVA.
- Cheltuieli auto: 50% deductibile pentru vehicule folosite mixt (art. 25 alin. 3 lit. l Cod Fiscal).
  Dacă vehiculul e exclusiv profesional + dovadă → 100%. Presupunem mixt ca default sigur.
- Impozit nerezidenți (withholding): 2% din comision (convenție fiscală România-Estonia).
  Informativ — nu generăm tranzacție separată acum, va fi la D390.
"""

from datetime import date
from typing import Optional

# --- Constante fiscale 2026 ---
VAT_STANDARD_PCT = 21          # Cota TVA standard curentă (%) — din 01.08.2025
VAT_STANDARD_PCT_PRE_2025_08 = 19  # Cota TVA standard până la 31.07.2025 (%)
VAT_REVERSE_CHARGE_PCT = 21    # Taxare inversă — aceeași cotă ca standard
FUEL_DEDUCTIBLE_PCT = 50       # Deductibilitate auto mixtă (%)
WITHHOLDING_TAX_PCT = 2        # Impozit nerezidenți (informativ)

# Pragul de la care se aplică 21% (înainte: 19%). OUG aplicabilă din 01.08.2025.
PRAG_TVA_21 = date(2025, 8, 1)

# --- Cod TVA Bolt — SURSĂ UNICĂ (golden rule) ---
# Confirmat la sursă: registrul eston e-Äriregister + pagina oficială Bolt pentru
# șoferi (declararea comisionului în declarația TVA UE / D390). Entitate: Bolt
# Operations OÜ (Estonia). Toate suprafețele (vat_engine, declaratii_spv, D390)
# referențiază aceste constante → fizic imposibil să mai divergă.
BOLT_VAT_ID = "EE102090374"                # forma completă (cu prefix țară EE)
BOLT_VAT_ID_NUMERIC = BOLT_VAT_ID[2:]      # "102090374" — fără prefix (D390 codO)


def cota_tva(data: date) -> float:
    """
    Cota TVA standard ca fracție (0.19 sau 0.21), în funcție de data facturii.

    Sursă unică de adevăr — folosește-o în loc de orice 0.21 hardcodat.
    - data >= 01.08.2025  → 0.21 (21%)
    - data <  01.08.2025  → 0.19 (19%)

    >>> cota_tva(date(2025, 7, 31))
    0.19
    >>> cota_tva(date(2025, 8, 1))
    0.21
    """
    return VAT_STANDARD_PCT / 100.0 if data >= PRAG_TVA_21 \
        else VAT_STANDARD_PCT_PRE_2025_08 / 100.0

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
    vat_pct: Optional[int] = None,
    data: Optional[date] = None,
) -> float:
    """
    Calculează TVA-ul de aplicat prin taxare inversă pe o sumă netă.

    Utilizare: comisioane Bolt/Uber (servicii intracomunitare).
    PFA-ul e obligat să declare și să plătească acest TVA la ANAF (D301).

    Cota se determină astfel (în această ordine de prioritate):
      1. vat_pct dat explicit  → override direct (compatibilitate).
      2. data dată             → cotă derivată prin cota_tva(data).
      3. niciunul              → cota standard curentă (VAT_REVERSE_CHARGE_PCT).

    Args:
        amount_net: Suma fără TVA (ex: 346.81 RON).
        vat_pct: Override explicit al cotei (%). Default None.
        data: Data facturii — derivă cota corectă pe dată (19% / 21%).

    Returns:
        Suma TVA (ex: 72.83 RON).

    >>> apply_reverse_charge(346.81)
    72.83
    >>> apply_reverse_charge(346.81, data=date(2025, 7, 31))
    65.89
    """
    if vat_pct is not None:
        cota = vat_pct / 100.0
    elif data is not None:
        cota = cota_tva(data)
    else:
        cota = VAT_REVERSE_CHARGE_PCT / 100.0
    return round(amount_net * cota, 2)


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
    Ex: "EE102090374" → "EE" → Estonia → UE → True (Bolt Operations OÜ).
    Ex: "RO12345678"  → "RO" → România → False.
    Ex: None          → False (nu știm, tratăm conservator).

    Args:
        vendor_vat_id: VAT ID-ul furnizorului (cu sau fără spații).

    Returns:
        bool

    >>> is_intra_eu_commission("EE102090374")
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
