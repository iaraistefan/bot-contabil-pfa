"""
Tax Calculator — Motor de calcul fiscal pentru PFA/SRL/II/IF.

Calculează corect impozit + CAS + CASS în funcție de FiscalProfile.

ARHITECTURĂ:
- Funcții pure (fără I/O, fără DB)
- Input: FiscalProfile + dicționar de totaluri
- Output: TaxEstimate cu toate componentele + explicații

CONTEXT LEGAL (2026):
- Cod Fiscal Legea 227/2015 (republicat)
- OUG 31/2024 — modificări PFA / Micro
- Plafoane CAS/CASS bazate pe salariu minim brut anual
- Cota CAS = 25% (PFA), Cota CASS = 10% (PFA)
- Cota impozit profit = 16% (SRL Normal)
- Cote micro = 1% (cu salariat) / 3% (fără salariat)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from app.domain.fiscal_profile import (
    FiscalProfile,
    FormaJuridica,
    RegimImpunere,
    TaxBase,
    SALARIU_MINIM_BRUT_2026,
    CAS_THRESHOLD_MULTIPLIER,
    CASS_THRESHOLD_MULTIPLIER,
    CAS_MAX_BASE_MULTIPLIER,
    CASS_MAX_BASE_MULTIPLIER,
    CAS_PCT,
    CASS_PCT,
)

logger = logging.getLogger(__name__)


# ============================================================
#                    DATACLASS-URI REZULTAT
# ============================================================

@dataclass
class IncomeTaxResult:
    """Rezultatul calculului impozitului pe venit/profit."""
    amount: float = 0.0           # suma de plată
    rate_pct: int = 0             # cota %
    base: float = 0.0             # baza pe care s-a calculat
    base_method: str = ""         # "venit_net" / "profit" / "cifra_afaceri" / "norma"
    explanation: str = ""         # text uman


@dataclass
class ContributionResult:
    """Rezultatul calculului CAS sau CASS (PFA)."""
    amount: float = 0.0           # suma anuală
    rate_pct: int = 0             # cota %
    base: float = 0.0             # baza de calcul
    threshold_ron: float = 0.0    # plafon de declanșare
    applicable: bool = False      # se aplică sau nu
    explanation: str = ""


@dataclass
class TaxEstimate:
    """Estimarea totală a obligațiilor fiscale pentru o perioadă."""
    # Componente individuale
    income_tax: IncomeTaxResult = field(default_factory=IncomeTaxResult)
    cas: ContributionResult = field(default_factory=ContributionResult)
    cass: ContributionResult = field(default_factory=ContributionResult)

    # Totaluri agregate
    total_tax: float = 0.0
    annualized: bool = False      # True dacă input-ul a fost anualizat

    # Comunicare cu user-ul
    explanations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Context
    period_label: str = ""        # "Luna 4/2026" / "Anul 2026"
    profile_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> dict:
        """Serializare pentru API/JSON."""
        return {
            "income_tax": {
                "amount": self.income_tax.amount,
                "rate_pct": self.income_tax.rate_pct,
                "base": self.income_tax.base,
                "base_method": self.income_tax.base_method,
                "explanation": self.income_tax.explanation,
            },
            "cas": {
                "amount": self.cas.amount,
                "rate_pct": self.cas.rate_pct,
                "base": self.cas.base,
                "threshold_ron": self.cas.threshold_ron,
                "applicable": self.cas.applicable,
                "explanation": self.cas.explanation,
            },
            "cass": {
                "amount": self.cass.amount,
                "rate_pct": self.cass.rate_pct,
                "base": self.cass.base,
                "threshold_ron": self.cass.threshold_ron,
                "applicable": self.cass.applicable,
                "explanation": self.cass.explanation,
            },
            "total_tax": self.total_tax,
            "annualized": self.annualized,
            "explanations": self.explanations,
            "warnings": self.warnings,
            "period_label": self.period_label,
            "profile_summary": self.profile_summary,
        }


# ============================================================
#                  IMPOZIT PE VENIT/PROFIT
# ============================================================

def compute_income_tax(
    profile: FiscalProfile,
    totals: Dict[str, float],
    *,
    norma_venit_anuala: Optional[float] = None,
) -> IncomeTaxResult:
    """
    Calculează impozitul pe venit/profit conform profilului.

    Args:
        profile: FiscalProfile al user-ului
        totals: dict cu chei posibile:
            - "income_brut": venituri brute totale
            - "expenses_deductible": cheltuieli deductibile (dacă aplicabil)
            - "venit_net": venit net (calculat exterior, opțional)
        norma_venit_anuala: pentru PFA Normă, suma din nomenclator

    Returns:
        IncomeTaxResult
    """
    income = float(totals.get("income_brut", 0.0))
    expenses_ded = float(totals.get("expenses_deductible", 0.0))
    venit_net_input = totals.get("venit_net")

    base_method = profile.income_tax_base
    rate = profile.income_tax_rate

    # ─── Calculează BAZA în funcție de metoda profilului ───
    if base_method == TaxBase.VENIT_NET:
        # PFA / II / IF / Profesie liberală — Sistem Real
        base = (
            float(venit_net_input) if venit_net_input is not None
            else max(0.0, income - expenses_ded)
        )
        method_str = "venit_net"
        explanation = (
            f"Impozit {rate}% × venit net ({base:.2f} RON) "
            f"= venituri ({income:.2f}) − cheltuieli deductibile ({expenses_ded:.2f})"
        )

    elif base_method == TaxBase.NORMA_VENIT:
        # PFA cu Normă fixă
        base = float(norma_venit_anuala or 0.0)
        method_str = "norma"
        explanation = (
            f"Impozit {rate}% × normă anuală ({base:.2f} RON din nomenclator)"
        )
        if base == 0:
            explanation += " — ⚠️ normă necompletată în profil"

    elif base_method == TaxBase.PROFIT:
        # SRL Normal — 16% × profit
        base = max(0.0, income - expenses_ded)
        method_str = "profit"
        explanation = (
            f"Impozit profit {rate}% × profit ({base:.2f} RON) "
            f"= venituri ({income:.2f}) − cheltuieli ({expenses_ded:.2f})"
        )

    elif base_method == TaxBase.CIFRA_AFACERI:
        # SRL Micro — 1% sau 3% × cifra de afaceri
        base = income
        method_str = "cifra_afaceri"
        explanation = (
            f"Impozit micro {rate}% × cifra afaceri ({base:.2f} RON)"
        )

    else:
        # Fallback
        base = max(0.0, income - expenses_ded)
        method_str = "venit_net"
        explanation = f"Impozit {rate}% × bază default ({base:.2f} RON)"

    amount = round(base * rate / 100, 2)

    return IncomeTaxResult(
        amount=amount,
        rate_pct=rate,
        base=base,
        base_method=method_str,
        explanation=explanation,
    )


# ============================================================
#                       CAS (PFA)
# ============================================================

def compute_cas(
    profile: FiscalProfile,
    venit_net_anual: float,
    *,
    salariu_minim: float = SALARIU_MINIM_BRUT_2026,
    base_choice_multiplier: int = CAS_THRESHOLD_MULTIPLIER,
) -> ContributionResult:
    """
    Calculează CAS (25%) pentru PFA / II / IF.

    Reguli (Cod Fiscal art. 148-151):
    - SRL: nu se aplică la nivel de firmă → returnează 0
    - PFA cu venit_net < 12 × salar minim → 0 (sub plafon)
    - PFA cu venit_net ≥ 12 × salar minim → 25% × bază aleasă
      Baza aleasă: între 12× și 24× salar minim
      Default: 12× (minim)

    Args:
        profile: FiscalProfile
        venit_net_anual: venit net total anual (estimat sau real)
        salariu_minim: salariu minim brut 2026
        base_choice_multiplier: cât multiplicat de salar minim alege user-ul

    Returns:
        ContributionResult
    """
    if not profile.requires_cas:
        return ContributionResult(
            applicable=False,
            explanation="CAS nu se aplică pentru forma juridică SRL",
        )

    threshold = profile.cas_threshold_ron or (CAS_THRESHOLD_MULTIPLIER * salariu_minim)

    if venit_net_anual < threshold:
        return ContributionResult(
            applicable=False,
            threshold_ron=threshold,
            explanation=(
                f"CAS NU se aplică — venit net anual ({venit_net_anual:.2f} RON) "
                f"sub plafonul de {threshold:.2f} RON ({CAS_THRESHOLD_MULTIPLIER}× salar minim)"
            ),
        )

    # Aplicabil — calculează baza
    # Baza aleasă: între 12× și 24× salar minim (default = 12× = minim)
    multiplier = max(CAS_THRESHOLD_MULTIPLIER, min(base_choice_multiplier, CAS_MAX_BASE_MULTIPLIER))
    base = multiplier * salariu_minim
    amount = round(base * CAS_PCT / 100, 2)

    return ContributionResult(
        amount=amount,
        rate_pct=CAS_PCT,
        base=base,
        threshold_ron=threshold,
        applicable=True,
        explanation=(
            f"CAS {CAS_PCT}% × {multiplier}× salariu minim "
            f"({base:.2f} RON) = {amount:.2f} RON anual"
        ),
    )


# ============================================================
#                       CASS (PFA)
# ============================================================

def compute_cass(
    profile: FiscalProfile,
    venit_net_anual: float,
    *,
    salariu_minim: float = SALARIU_MINIM_BRUT_2026,
) -> ContributionResult:
    """
    Calculează CASS (10%) pentru PFA / II / IF.

    Reguli (Cod Fiscal art. 153-170, modificat OUG 31/2024):
    - SRL: nu se aplică la nivel de firmă → returnează 0
    - PFA cu venit_net < 6 × salar minim → 0 (sub plafon)
    - PFA cu 6× ≤ venit_net < 60× → 10% × venit_net (real)
    - PFA cu venit_net ≥ 60× → 10% × 60× salar minim (plafonat)

    Args:
        profile: FiscalProfile
        venit_net_anual: venit net total anual
        salariu_minim: salariu minim brut 2026

    Returns:
        ContributionResult
    """
    if not profile.requires_cass:
        return ContributionResult(
            applicable=False,
            explanation="CASS nu se aplică pentru forma juridică SRL",
        )

    threshold = profile.cass_threshold_ron or (CASS_THRESHOLD_MULTIPLIER * salariu_minim)
    max_base = CASS_MAX_BASE_MULTIPLIER * salariu_minim

    if venit_net_anual < threshold:
        return ContributionResult(
            applicable=False,
            threshold_ron=threshold,
            explanation=(
                f"CASS NU se aplică — venit net anual ({venit_net_anual:.2f} RON) "
                f"sub plafonul de {threshold:.2f} RON ({CASS_THRESHOLD_MULTIPLIER}× salar minim)"
            ),
        )

    # Aplicabil — baza = min(venit_net, plafon maxim)
    base = min(venit_net_anual, max_base)
    amount = round(base * CASS_PCT / 100, 2)

    base_note = (
        f"plafonat la {CASS_MAX_BASE_MULTIPLIER}× salar minim"
        if venit_net_anual >= max_base
        else "venit net real"
    )

    return ContributionResult(
        amount=amount,
        rate_pct=CASS_PCT,
        base=base,
        threshold_ron=threshold,
        applicable=True,
        explanation=(
            f"CASS {CASS_PCT}% × {base:.2f} RON ({base_note}) = {amount:.2f} RON anual"
        ),
    )


# ============================================================
#              ESTIMARE COMPLETĂ (totul împreună)
# ============================================================

def compute_full_estimate(
    profile: FiscalProfile,
    totals: Dict[str, float],
    *,
    period_label: str = "",
    annualize_factor: float = 1.0,
    norma_venit_anuala: Optional[float] = None,
    cas_base_choice_multiplier: int = CAS_THRESHOLD_MULTIPLIER,
) -> TaxEstimate:
    """
    Calculează estimarea fiscală COMPLETĂ (impozit + CAS + CASS).

    Args:
        profile: FiscalProfile
        totals: dict cu venituri/cheltuieli
        period_label: "Luna 4/2026" / "Anul 2026" pentru afișare
        annualize_factor: factor de anualizare pentru CAS/CASS
                          - 1.0 = totals e deja anual
                          - 12.0 = totals e lunar (multiplicăm × 12)
        norma_venit_anuala: pentru PFA Normă (opțional)
        cas_base_choice_multiplier: 12-24, default 12 (minim)

    Returns:
        TaxEstimate cu toate componentele
    """
    estimate = TaxEstimate(
        period_label=period_label,
        annualized=(annualize_factor != 1.0),
        profile_summary=profile.to_summary(),
    )

    # ─── Impozit pe venit/profit ────────────────────────────
    estimate.income_tax = compute_income_tax(
        profile, totals, norma_venit_anuala=norma_venit_anuala
    )
    estimate.explanations.append(estimate.income_tax.explanation)

    # ─── CAS / CASS — doar pentru PFA, pe bază anuală ───────
    if profile.requires_cas or profile.requires_cass:
        # Calculăm venit net anual pentru baza CAS/CASS
        if "venit_net" in totals:
            venit_net = float(totals["venit_net"]) * annualize_factor
        else:
            income_anual = float(totals.get("income_brut", 0.0)) * annualize_factor
            expenses_anual = float(totals.get("expenses_deductible", 0.0)) * annualize_factor
            venit_net = max(0.0, income_anual - expenses_anual)

        estimate.cas = compute_cas(
            profile, venit_net,
            base_choice_multiplier=cas_base_choice_multiplier,
        )
        estimate.cass = compute_cass(profile, venit_net)

        if estimate.cas.applicable:
            estimate.explanations.append(estimate.cas.explanation)
        if estimate.cass.applicable:
            estimate.explanations.append(estimate.cass.explanation)

        # Avertismente apropiere de plafon (pentru previziune)
        if (not estimate.cas.applicable
                and venit_net > 0.8 * estimate.cas.threshold_ron):
            estimate.warnings.append(
                f"🟡 Aproape de plafonul CAS — la {(venit_net/estimate.cas.threshold_ron*100):.0f}% "
                f"din {estimate.cas.threshold_ron:.0f} RON"
            )
        if (not estimate.cass.applicable
                and venit_net > 0.8 * estimate.cass.threshold_ron):
            estimate.warnings.append(
                f"🟡 Aproape de plafonul CASS — la {(venit_net/estimate.cass.threshold_ron*100):.0f}% "
                f"din {estimate.cass.threshold_ron:.0f} RON"
            )

    # ─── Total ──────────────────────────────────────────────
    estimate.total_tax = round(
        estimate.income_tax.amount + estimate.cas.amount + estimate.cass.amount,
        2
    )

    return estimate


# ============================================================
#              FORMAT TEXT pentru Telegram
# ============================================================

def format_estimate_text(estimate: TaxEstimate) -> str:
    """Formatează un TaxEstimate ca text pentru Telegram."""
    lines = []

    if estimate.period_label:
        lines.append(f"📊 *Estimare fiscală — {estimate.period_label}*\n")

    # Impozit
    if estimate.income_tax.amount > 0:
        lines.append(
            f"💰 Impozit: *{estimate.income_tax.amount:.2f} RON* "
            f"({estimate.income_tax.rate_pct}% × {estimate.income_tax.base:.2f})"
        )
    else:
        lines.append("💰 Impozit: 0 RON (fără bază impozabilă)")

    # CAS
    if estimate.cas.applicable:
        lines.append(f"🏥 CAS: *{estimate.cas.amount:.2f} RON* anual")
    elif estimate.cas.threshold_ron > 0:
        lines.append("🏥 CAS: nu se aplică (sub plafon)")

    # CASS
    if estimate.cass.applicable:
        lines.append(f"⚕️ CASS: *{estimate.cass.amount:.2f} RON* anual")
    elif estimate.cass.threshold_ron > 0:
        lines.append("⚕️ CASS: nu se aplică (sub plafon)")

    # Total
    lines.append(f"\n💼 *TOTAL: {estimate.total_tax:.2f} RON*")

    # Avertismente
    if estimate.warnings:
        lines.append("\n⚠️ Atenție:")
        for w in estimate.warnings:
            lines.append(f"  • {w}")

    return "\n".join(lines)
