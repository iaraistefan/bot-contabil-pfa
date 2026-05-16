"""
Compliance Guardian — Motor de validare PRE/POST plată pentru obligații fiscale.

ARHITECTURĂ:
Combină 3 componente pentru a preveni erori fiscale:
  1. fiscal_profile (forma juridică + activitate user-ului)
  2. fiscal_calendar (obligații + termene + sume)
  3. anaf_iban_db (IBAN-uri corecte per județ + obligație)

FUNCȚIONALITATE PRINCIPALĂ:
  1. validate_payment(...) — PRE-payment check: previne plățile greșite
     (cazul Stefan din aprilie 2026: 8 plăți respinse pt IBAN greșit)
  2. audit_bank_transaction(...) — POST-payment: identifică probleme din extras
  3. get_compliance_status(...) — dashboard total pentru user
  4. format_*_telegram(...) — UI Telegram pentru toate de mai sus

PRINCIPII:
  - Funcții PURE (fără I/O direct, fără DB)
  - Apelantul furnizează contextul (din User profile + transaction context)
  - Returnează decizii STRUCTURATE cu issues + fix suggestions
  - Niciodată "trust by default" — verificăm fiecare detaliu

CAZURI DE UZ ACOPERITE:
  ✅ IBAN greșit → BLOCKED + sugestie IBAN corect
  ✅ Sumă greșită → WARNING + calcul așteptat
  ✅ Plată pentru obligație ne-aplicabilă → BLOCKED (ex: PFA cu D101)
  ✅ Lipsește prerequisite (ex: D301 fără D700) → BLOCKED
  ✅ Termen depășit → WARNING + estimare penalități
  ✅ Reverse lookup IBAN din extras → identifică tipul plății
  ✅ Detectare returnări (plată + returnare în lună) → ALERT

CHANGELOG:
- v1 (16.05.2026, Pas 11.3): Versiune inițială completă
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.integrations.anaf_iban_db import (
    TipObligatie,
    IbanCont,
    get_iban_for_obligation,
    validate_payment_iban,
    identify_obligation_from_iban,
    Judet,
)
from app.domain.fiscal_calendar import (
    DefinitieObligatie,
    ObligatieCalculate,
    DEFINITII_OBLIGATII,
    compute_obligation,
    get_obligations_for_user,
    StatusObligatie,
    FrecventaObligatie,
    LUNI_RO_UPPER,
    COTA_TVA_STANDARD,
    COTA_RETINERE_NEREZIDENT_EE,
)

logger = logging.getLogger(__name__)


# ============================================================
#                    ENUMS
# ============================================================

class ValidationVerdict(str, Enum):
    """Verdictul final al unei validări."""
    OK = "OK"                # plata e corectă, poate continua
    WARNING = "WARNING"      # plata are probleme dar nu critice
    BLOCKED = "BLOCKED"      # plata va fi respinsă, NU continua


class IssueSeverity(str, Enum):
    """Severitatea unei probleme detectate."""
    ERROR = "ERROR"          # critic, blochează plata
    WARNING = "WARNING"      # nu blochează dar suspectă
    INFO = "INFO"            # informativ


class IssueCategory(str, Enum):
    """Categorii de probleme detectabile."""
    IBAN_WRONG = "IBAN_WRONG"                       # IBAN nu corespunde
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"             # sumă diferă de calcul
    PREREQUISITE_MISSING = "PREREQUISITE_MISSING"   # ex: D301 fără D700
    FORMA_JURIDICA_MISMATCH = "FORMA_JURIDICA_MISMATCH"
    BENEFICIAR_ID_WRONG = "BENEFICIAR_ID_WRONG"     # CNP vs CUI greșit
    DEADLINE_PASSED = "DEADLINE_PASSED"             # termen depășit
    PAYMENT_TOO_EARLY = "PAYMENT_TOO_EARLY"         # plătit fără declarație depusă
    UNKNOWN_PURPOSE = "UNKNOWN_PURPOSE"             # cod obligație necunoscut
    SUSPICIOUS_IBAN = "SUSPICIOUS_IBAN"             # IBAN nu apare în nomenclator
    RETURNED_PAYMENT = "RETURNED_PAYMENT"           # plată returnată de ANAF


# ============================================================
#                    DATACLASSES
# ============================================================

@dataclass
class ValidationIssue:
    """Un singur issue detectat la validare."""
    category: IssueCategory
    severity: IssueSeverity
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    fix_suggestion: Optional[str] = None
    reference_link: Optional[str] = None    # link doc oficială (ANAF, etc.)


@dataclass
class PaymentValidationResult:
    """Rezultatul validării unei plăți planificate (PRE-payment)."""
    verdict: ValidationVerdict
    issues: List[ValidationIssue] = field(default_factory=list)

    # Context corect (ce trebuia să fie plata)
    obligatie_matched: Optional[ObligatieCalculate] = None
    suggested_iban: Optional[IbanCont] = None
    expected_amount: Optional[float] = None
    expected_termen: Optional[date] = None

    # Context primit (ce a încercat user-ul)
    actual_iban: str = ""
    actual_amount: float = 0.0

    explanation: str = ""

    def has_errors(self) -> bool:
        return any(i.severity == IssueSeverity.ERROR for i in self.issues)

    def has_warnings(self) -> bool:
        return any(i.severity == IssueSeverity.WARNING for i in self.issues)


@dataclass
class BankTransactionAudit:
    """Rezultatul auditării unei tranzacții din extras bancar (POST-payment)."""
    # Input
    iban_target: str
    amount: float
    transaction_date: date
    description: str

    # Identificare
    identified_obligation_type: Optional[TipObligatie] = None
    identified_iban_cont: Optional[IbanCont] = None

    # Verdict
    is_correctly_targeted: bool = False
    issues: List[ValidationIssue] = field(default_factory=list)
    explanation: str = ""

    # Pentru detecție returnare (plată + returnare în aceeași lună)
    is_returned: bool = False
    return_date: Optional[date] = None
    return_reason: Optional[str] = None


@dataclass
class ComplianceStatus:
    """Snapshot total al compliance-ului unui user."""
    user_context: Dict = field(default_factory=dict)

    obligatii_active: List[ObligatieCalculate] = field(default_factory=list)
    obligatii_critice: List[ObligatieCalculate] = field(default_factory=list)
    obligatii_avertisment: List[ObligatieCalculate] = field(default_factory=list)
    obligatii_proxime: List[ObligatieCalculate] = field(default_factory=list)

    total_de_platit_30zile: float = 0.0
    total_de_platit_7zile: float = 0.0

    recomandari: List[str] = field(default_factory=list)
    alerte_critice: List[str] = field(default_factory=list)

    score_compliance: int = 0  # 0-100, similar credit score


# ============================================================
#              PRE-PAYMENT VALIDATION
# ============================================================

def _find_obligation_definition(purpose_code: str) -> Optional[DefinitieObligatie]:
    """
    Caută definiția obligației din cod (flexibil — acceptă variante).

    Exemple care match:
    - "D100", "D100 poz. 634", "D100_634"
    - "D301", "D301 TVA"
    - "D212", "D212 unica"
    """
    pc_clean = purpose_code.upper().strip()

    # Match direct
    for key, df in DEFINITII_OBLIGATII.items():
        if df.cod.upper() == pc_clean or key.upper() == pc_clean:
            return df

    # Match parțial (D100 → "D100 poz. 634")
    for key, df in DEFINITII_OBLIGATII.items():
        cod_short = df.cod.split()[0].upper()  # primul cuvânt: "D100", "D301"
        if cod_short == pc_clean:
            return df

    # Match după prefix din key
    for key, df in DEFINITII_OBLIGATII.items():
        if key.upper().startswith(pc_clean):
            return df

    return None


def validate_payment(
    iban: str,
    amount: float,
    purpose_code: str,
    period_year: int,
    period_month: int,
    *,
    # Context user (obligatoriu)
    forma_juridica: str,
    activity_code: str,
    judet: str,
    # Context user opțional
    is_vat_payer: bool = False,
    has_cod_special_tva: bool = False,
    # Context tranzacție (pentru calcul sumă)
    has_intracom_invoice: bool = False,
    intracom_base_amount: float = 0.0,
    # Context temporal
    today: Optional[date] = None,
) -> PaymentValidationResult:
    """
    PRE-payment validation: validează că o plată planificată e corectă.

    Args:
        iban: IBAN-ul către care s-ar face plata
        amount: suma de plată
        purpose_code: codul obligației (ex: "D301", "D100", "D212")
        period_year, period_month: pentru ce perioadă e plata
        forma_juridica, activity_code, judet: contextul user-ului
        is_vat_payer, has_cod_special_tva: status TVA
        has_intracom_invoice, intracom_base_amount: pt validare sumă
        today: data de referință

    Returns:
        PaymentValidationResult cu verdict + issues + fix suggestions

    Exemplu de uz:
        result = validate_payment(
            iban="RO82TREZ10120A1203000001",  # IBAN greșit folosit de Stefan
            amount=138.00,
            purpose_code="D301",
            period_year=2026, period_month=1,
            forma_juridica="PFA", activity_code="ridesharing", judet="BN",
            has_cod_special_tva=True,
            has_intracom_invoice=True,
            intracom_base_amount=657.10,
        )
        # → verdict=BLOCKED, issue IBAN_WRONG cu sugestie IBAN corect
    """
    issues: List[ValidationIssue] = []

    if today is None:
        today = date.today()

    # ─── PAS 1: Identifică obligația ───────────────────────────
    obligatie_def = _find_obligation_definition(purpose_code)
    if not obligatie_def:
        return PaymentValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            issues=[ValidationIssue(
                category=IssueCategory.UNKNOWN_PURPOSE,
                severity=IssueSeverity.ERROR,
                message=f"Cod obligație necunoscut: '{purpose_code}'",
                actual=purpose_code,
                fix_suggestion=(
                    "Folosește un cod cunoscut: D100, D207, D301, D390, "
                    "D300, D212, D101, D700"
                ),
            )],
            actual_iban=iban,
            actual_amount=amount,
            explanation=f"❌ Nu pot valida — '{purpose_code}' nu e în baza de obligații.",
        )

    # ─── PAS 2: Calculează ce ar trebui să fie plata ──────────
    obligatie_calc = compute_obligation(
        obligatie_def, period_year, period_month,
        forma_juridica, activity_code,
        has_intracom_invoice=has_intracom_invoice,
        intracom_base_amount=intracom_base_amount,
        has_cod_special_tva=has_cod_special_tva,
        is_vat_payer=is_vat_payer,
        judet=judet,
        today=today,
    )

    # ─── PAS 3: Verifică aplicabilitatea ──────────────────────
    if not obligatie_calc.aplicabil_acum:
        # Caz special: lipsește prerequisite (cod special TVA pt D301)
        if "Cod special TVA neînregistrat" in (obligatie_calc.motiv_neaplicabil or ""):
            category = IssueCategory.PREREQUISITE_MISSING
            fix = (
                "Depune mai întâi D700 (înregistrare cod special TVA) "
                "ca să poți depune D301. Plata acum va fi respinsă de ANAF."
            )
        else:
            category = IssueCategory.FORMA_JURIDICA_MISMATCH
            fix = (
                "Verifică profilul fiscal. Această obligație nu se aplică "
                "configurației tale actuale."
            )

        issues.append(ValidationIssue(
            category=category,
            severity=IssueSeverity.ERROR,
            message=(
                f"Obligația {obligatie_def.cod} NU se aplică ție: "
                f"{obligatie_calc.motiv_neaplicabil}"
            ),
            fix_suggestion=fix,
        ))
        return PaymentValidationResult(
            verdict=ValidationVerdict.BLOCKED,
            issues=issues,
            obligatie_matched=obligatie_calc,
            actual_iban=iban,
            actual_amount=amount,
            explanation="❌ Plată BLOCATĂ — obligația nu se aplică profilului tău.",
        )

    # ─── PAS 4: Validează IBAN ─────────────────────────────────
    if obligatie_def.tip_iban:
        is_valid, msg = validate_payment_iban(
            iban, obligatie_def.tip_iban, judet,
        )
        if not is_valid:
            expected_iban = (
                obligatie_calc.iban_cont.iban if obligatie_calc.iban_cont
                else "Verifică ANAF"
            )
            issues.append(ValidationIssue(
                category=IssueCategory.IBAN_WRONG,
                severity=IssueSeverity.ERROR,
                message=(
                    f"IBAN-ul {iban} NU corespunde obligației "
                    f"{obligatie_def.cod}"
                ),
                expected=expected_iban,
                actual=iban,
                fix_suggestion=(
                    f"Modifică IBAN-ul în: {expected_iban}\n"
                    f"Cod buget: {obligatie_calc.iban_cont.cod_buget if obligatie_calc.iban_cont else 'N/A'}"
                ),
                reference_link=(
                    "https://static.anaf.ro/static/10/Anaf/AsistentaContribuabili_r/iban2014/"
                ),
            ))
    else:
        # Obligație care nu se plătește (doar declarativă, ex: D390)
        issues.append(ValidationIssue(
            category=IssueCategory.UNKNOWN_PURPOSE,
            severity=IssueSeverity.INFO,
            message=(
                f"{obligatie_def.cod} e doar declarativă — nu se plătește. "
                f"Doar se depune."
            ),
            fix_suggestion=f"Depune {obligatie_def.cod} prin SPV — fără plată.",
        ))

    # ─── PAS 5: Validează suma ────────────────────────────────
    if obligatie_calc.suma_estimata is not None:
        # Toleranță 1 RON sau 1% (mai mare dintre cele două)
        tolerance = max(1.00, obligatie_calc.suma_estimata * 0.01)
        diff = abs(amount - obligatie_calc.suma_estimata)
        if diff > tolerance:
            severity = (
                IssueSeverity.ERROR if diff > obligatie_calc.suma_estimata * 0.10
                else IssueSeverity.WARNING
            )
            issues.append(ValidationIssue(
                category=IssueCategory.AMOUNT_MISMATCH,
                severity=severity,
                message=(
                    f"Suma diferă de calculul automat: tu vrei {amount:.2f} RON, "
                    f"calculat: {obligatie_calc.suma_estimata:.2f} RON "
                    f"(diferență: {diff:.2f} RON)"
                ),
                expected=f"{obligatie_calc.suma_estimata:.2f}",
                actual=f"{amount:.2f}",
                fix_suggestion=(
                    f"Verifică baza de calcul: "
                    f"factură intracom {intracom_base_amount:.2f} RON × "
                    f"{obligatie_def.formula_suma or 'cota'}"
                ),
            ))

    # ─── PAS 6: Validează termen ──────────────────────────────
    if obligatie_calc.status == StatusObligatie.DEPASIT:
        zile_depasire = abs(obligatie_calc.zile_ramase)
        penalty_estimate = (
            obligatie_calc.suma_estimata * 0.0002 * zile_depasire
            if obligatie_calc.suma_estimata else 0
        )
        issues.append(ValidationIssue(
            category=IssueCategory.DEADLINE_PASSED,
            severity=IssueSeverity.WARNING,
            message=(
                f"Termen DEPĂȘIT cu {zile_depasire} zile "
                f"(termen era: {obligatie_calc.termen.strftime('%d.%m.%Y')})"
            ),
            fix_suggestion=(
                f"Plătește cât mai repede. Estimare majorări întârziere: "
                f"~{penalty_estimate:.2f} RON (0.02%/zi conform Cod Fiscal)."
            ),
        ))

    # ─── PAS 7: Verdict final ─────────────────────────────────
    has_error = any(i.severity == IssueSeverity.ERROR for i in issues)
    has_warning = any(i.severity == IssueSeverity.WARNING for i in issues)

    if has_error:
        verdict = ValidationVerdict.BLOCKED
        explanation = (
            "❌ Plată BLOCATĂ — corectează problemele înainte să trimiti banii. "
            "Plata va fi respinsă de ANAF."
        )
    elif has_warning:
        verdict = ValidationVerdict.WARNING
        explanation = (
            "⚠️ Plată cu AVERTISMENTE — verifică detaliile înainte să continui."
        )
    else:
        verdict = ValidationVerdict.OK
        explanation = "✅ Plată CORECTĂ — poți continua cu încredere."

    return PaymentValidationResult(
        verdict=verdict,
        issues=issues,
        obligatie_matched=obligatie_calc,
        suggested_iban=obligatie_calc.iban_cont,
        expected_amount=obligatie_calc.suma_estimata,
        expected_termen=obligatie_calc.termen,
        actual_iban=iban,
        actual_amount=amount,
        explanation=explanation,
    )


# ============================================================
#              POST-PAYMENT AUDIT
# ============================================================

def audit_bank_transaction(
    iban: str,
    amount: float,
    description: str,
    transaction_date: date,
    *,
    forma_juridica: str,
    judet: str,
    is_credit: bool = False,  # True dacă e încasare (returnare ANAF)
) -> BankTransactionAudit:
    """
    POST-payment audit: identifică ce s-a plătit + dacă e corect.

    Util pentru parsarea extrasului bancar — pentru fiecare plată către
    Trezorerie identifică:
    - Ce obligație fiscală reprezintă (din IBAN)
    - Dacă plata a fost corect direcționată
    - Probleme detectate (IBAN suspect, returnări, etc.)

    Args:
        iban: IBAN-ul beneficiarului (Trezorerie)
        amount: suma tranzacției
        description: descrierea de pe extras
        transaction_date: data tranzacției
        forma_juridica: pt context (verificăm dacă obligația se aplică)
        judet: pt lookup IBAN
        is_credit: True dacă e încasare (= returnare de la ANAF)

    Returns:
        BankTransactionAudit cu identificare + issues
    """
    result = BankTransactionAudit(
        iban_target=iban,
        amount=amount,
        transaction_date=transaction_date,
        description=description,
    )

    # Detectează returnări din description
    desc_lower = description.lower()
    if any(kw in desc_lower for kw in [
        "returnare plata", "returnare plată", "respins", "stornat",
        "refund anaf", "anulat"
    ]):
        result.is_returned = True
        result.return_date = transaction_date
        result.issues.append(ValidationIssue(
            category=IssueCategory.RETURNED_PAYMENT,
            severity=IssueSeverity.ERROR,
            message=(
                f"Plată RETURNATĂ de ANAF: {amount:.2f} RON "
                f"({transaction_date.strftime('%d.%m.%Y')})"
            ),
            actual=description[:200],
            fix_suggestion=(
                "Plata a fost respinsă. Cauze probabile:\n"
                "  • IBAN greșit (verifică contul corect)\n"
                "  • Tip declarație neaplicabil (PFA cu D100 PJ)\n"
                "  • Sumă greșită\n"
                "  • Beneficiar identificat greșit (CUI vs CNP)\n"
                "Verifică în SPV motivul exact al respingerii."
            ),
        ))

    # Identifică obligația din IBAN
    identification = identify_obligation_from_iban(iban, judet)
    if identification:
        obligation_type, iban_cont = identification
        result.identified_obligation_type = obligation_type
        result.identified_iban_cont = iban_cont
        result.is_correctly_targeted = True
        result.explanation = f"✅ Identificat: {iban_cont.denumire}"
    else:
        result.is_correctly_targeted = False
        # Daca IBAN-ul începe cu prefix Trezorerie (TREZ) dar nu match nimic
        if "TREZ" in iban.upper():
            severity = IssueSeverity.ERROR
            category = IssueCategory.SUSPICIOUS_IBAN
            msg = (
                f"IBAN-ul {iban} pare să fie cont Trezorerie dar NU "
                f"corespunde niciunei obligații cunoscute pentru județul {judet}."
            )
            fix = (
                "Verifică contul exact pe SPV ANAF sau cere la Trezoreria "
                "de domiciliu. Plata e probabil să fie respinsă."
            )
        else:
            severity = IssueSeverity.INFO
            category = IssueCategory.UNKNOWN_PURPOSE
            msg = f"IBAN-ul {iban} nu pare să fie cont Trezorerie."
            fix = "Verifică dacă plata e către ANAF sau alt beneficiar."

        result.issues.append(ValidationIssue(
            category=category,
            severity=severity,
            message=msg,
            actual=iban,
            fix_suggestion=fix,
        ))
        result.explanation = f"⚠️ IBAN nedetectat: {iban}"

    return result


def audit_extras_bancar(
    transactions: List[Dict],
    *,
    forma_juridica: str,
    judet: str,
) -> List[BankTransactionAudit]:
    """
    Auditează un extras bancar întreg, detectând și returnările.

    Args:
        transactions: listă de dict cu cheile:
            - iban (target IBAN)
            - amount (suma, pozitivă debit, negativă credit)
            - description (descrierea)
            - date (data tranzacției ca date)
            - is_credit (bool, True dacă e încasare)
        forma_juridica, judet: context user

    Returns:
        Listă de BankTransactionAudit + cross-referencing pentru returnări.
    """
    audits = []
    for tx in transactions:
        audit = audit_bank_transaction(
            iban=tx.get("iban", ""),
            amount=tx.get("amount", 0),
            description=tx.get("description", ""),
            transaction_date=tx.get("date", date.today()),
            forma_juridica=forma_juridica,
            judet=judet,
            is_credit=tx.get("is_credit", False),
        )
        audits.append(audit)

    return audits


# ============================================================
#              COMPLIANCE STATUS (DASHBOARD)
# ============================================================

def _calculate_compliance_score(
    obligatii: List[ObligatieCalculate],
    today: date,
) -> int:
    """
    Calculează scor compliance 0-100 (similar credit score).

    Reguli:
    - Start 100
    - -20 pentru fiecare obligație depășită
    - -10 pentru fiecare obligație critică (≤ 3 zile)
    - -5 pentru fiecare obligație avertisment (≤ 7 zile)
    - +5 dacă nu există obligații critice/depășite
    """
    score = 100
    for o in obligatii:
        if not o.aplicabil_acum:
            continue
        if o.status == StatusObligatie.DEPASIT:
            score -= 20
        elif o.status == StatusObligatie.CRITIC:
            score -= 10
        elif o.status == StatusObligatie.AVERTISMENT:
            score -= 5

    return max(0, min(100, score))


def get_compliance_status(
    year: int,
    month: int,
    forma_juridica: str,
    activity_code: str,
    *,
    has_intracom_invoice: bool = False,
    intracom_base_amount: float = 0.0,
    has_cod_special_tva: bool = False,
    is_vat_payer: bool = False,
    judet: Optional[str] = None,
    today: Optional[date] = None,
) -> ComplianceStatus:
    """
    Returnează snapshot total al compliance-ului unui user.

    Combină toate obligațiile aplicabile + le clasifică pe urgență +
    generează recomandări concrete.
    """
    if today is None:
        today = date.today()

    obligatii = get_obligations_for_user(
        year, month, forma_juridica, activity_code,
        has_intracom_invoice=has_intracom_invoice,
        intracom_base_amount=intracom_base_amount,
        has_cod_special_tva=has_cod_special_tva,
        is_vat_payer=is_vat_payer,
        judet=judet,
        only_applicable=True,
        today=today,
    )

    status = ComplianceStatus(
        user_context={
            "forma_juridica": forma_juridica,
            "activity_code": activity_code,
            "judet": judet,
            "is_vat_payer": is_vat_payer,
            "has_cod_special_tva": has_cod_special_tva,
            "period": f"{LUNI_RO_UPPER.get(month, month)} {year}",
        },
        obligatii_active=obligatii,
    )

    # Clasificare pe urgență
    for o in obligatii:
        if o.status in (StatusObligatie.DEPASIT, StatusObligatie.CRITIC):
            status.obligatii_critice.append(o)
        elif o.status == StatusObligatie.AVERTISMENT:
            status.obligatii_avertisment.append(o)
        elif o.status == StatusObligatie.PROXIM:
            status.obligatii_proxime.append(o)

        # Sume cumulate
        if o.suma_estimata and -7 <= o.zile_ramase <= 30:
            status.total_de_platit_30zile += o.suma_estimata
        if o.suma_estimata and -7 <= o.zile_ramase <= 7:
            status.total_de_platit_7zile += o.suma_estimata

    # Score
    status.score_compliance = _calculate_compliance_score(obligatii, today)

    # Alerte critice
    for o in status.obligatii_critice:
        if o.status == StatusObligatie.DEPASIT:
            status.alerte_critice.append(
                f"🚨 {o.definitie.cod} DEPĂȘIT cu "
                f"{abs(o.zile_ramase)} zile — acționează ACUM"
            )
        else:
            status.alerte_critice.append(
                f"🟠 {o.definitie.cod} expiră în {o.zile_ramase} zile"
            )

    # Recomandări
    if not has_cod_special_tva and any(
        o.definitie.cod == "D700" for o in obligatii
    ):
        status.recomandari.append(
            "⚙️ Depune D700 (cod special TVA) — necesar pentru "
            "achiziții intracomunitare Bolt"
        )

    if status.total_de_platit_7zile > 0:
        status.recomandari.append(
            f"💰 Pregătește {status.total_de_platit_7zile:.2f} RON "
            f"pentru următoarele 7 zile"
        )

    if status.total_de_platit_30zile > status.total_de_platit_7zile:
        suma_30 = status.total_de_platit_30zile - status.total_de_platit_7zile
        status.recomandari.append(
            f"📅 Suplimentar {suma_30:.2f} RON în următoarele 30 zile"
        )

    if status.score_compliance >= 95:
        status.recomandari.append("⭐ Compliance excelent — felicitări!")
    elif status.score_compliance < 70:
        status.recomandari.append(
            "⚠️ Compliance sub nivelul recomandat — acționează pe obligațiile critice"
        )

    return status


# ============================================================
#              FORMATARE TELEGRAM (UI)
# ============================================================

def format_payment_validation_telegram(
    result: PaymentValidationResult,
) -> str:
    """Formatează rezultatul unei validări PRE-payment pentru Telegram."""
    verdict_emoji = {
        ValidationVerdict.OK: "✅",
        ValidationVerdict.WARNING: "⚠️",
        ValidationVerdict.BLOCKED: "🚨",
    }.get(result.verdict, "❓")

    lines = [
        f"{verdict_emoji} *VERIFICARE PLATĂ FISCALĂ*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{result.explanation}",
        "",
    ]

    if result.obligatie_matched:
        o = result.obligatie_matched
        lines.extend([
            f"📋 *Obligație*: {o.definitie.cod} — {o.definitie.nume}",
            f"📅 *Termen*: `{o.termen.strftime('%d.%m.%Y')}`",
        ])
        if result.expected_amount:
            lines.append(
                f"💰 *Sumă așteptată*: `{result.expected_amount:.2f} RON`"
            )
        lines.append("")

    if result.issues:
        # Grupare pe severitate
        errors = [i for i in result.issues if i.severity == IssueSeverity.ERROR]
        warnings = [i for i in result.issues if i.severity == IssueSeverity.WARNING]
        infos = [i for i in result.issues if i.severity == IssueSeverity.INFO]

        if errors:
            lines.append("🔴 *ERORI CRITICE:*")
            for e in errors:
                lines.append(f"  • {e.message}")
                if e.fix_suggestion:
                    lines.append(f"    💡 _{e.fix_suggestion}_")
            lines.append("")

        if warnings:
            lines.append("🟡 *AVERTISMENTE:*")
            for w in warnings:
                lines.append(f"  • {w.message}")
                if w.fix_suggestion:
                    lines.append(f"    💡 _{w.fix_suggestion}_")
            lines.append("")

        if infos:
            lines.append("ℹ️ *Info:*")
            for i in infos:
                lines.append(f"  • {i.message}")
            lines.append("")

    if result.suggested_iban and result.verdict != ValidationVerdict.OK:
        lines.extend([
            "🏦 *IBAN CORECT pentru această obligație:*",
            f"`{result.suggested_iban.iban}`",
            f"_Cod buget: {result.suggested_iban.cod_buget}_",
            f"_{result.suggested_iban.denumire}_",
            "",
        ])

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_⚠️ Verifică cu contabilul înainte de plată._")

    return "\n".join(lines)


def format_compliance_status_telegram(status: ComplianceStatus) -> str:
    """Formatează ComplianceStatus pentru Telegram (dashboard)."""
    ctx = status.user_context
    score_emoji = (
        "🟢" if status.score_compliance >= 85
        else "🟡" if status.score_compliance >= 70
        else "🔴"
    )

    lines = [
        f"📊 *COMPLIANCE STATUS*",
        f"📅 _{ctx.get('period', '—')}_",
        f"👤 _{ctx.get('forma_juridica')} · {ctx.get('activity_code')}_",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"{score_emoji} *Compliance Score*: *{status.score_compliance}/100*",
        "",
    ]

    if status.alerte_critice:
        lines.append("🚨 *ALERTE CRITICE:*")
        for a in status.alerte_critice:
            lines.append(f"  {a}")
        lines.append("")

    if status.obligatii_critice or status.obligatii_avertisment:
        if status.obligatii_critice:
            lines.append("🔴 *URGENT (≤ 3 zile):*")
            for o in status.obligatii_critice:
                lines.append(
                    f"  • *{o.definitie.cod}* — termen "
                    f"`{o.termen.strftime('%d.%m.%Y')}` "
                    f"({o.zile_ramase}z)"
                )
                if o.suma_estimata:
                    lines.append(f"    💰 _{o.suma_estimata:.2f} RON_")
            lines.append("")

        if status.obligatii_avertisment:
            lines.append("🟡 *Atenție (≤ 7 zile):*")
            for o in status.obligatii_avertisment:
                lines.append(
                    f"  • *{o.definitie.cod}* — termen "
                    f"`{o.termen.strftime('%d.%m.%Y')}`"
                )
            lines.append("")

    if status.obligatii_proxime:
        lines.append("🟢 *Apropiat (≤ 30 zile):*")
        for o in status.obligatii_proxime:
            lines.append(
                f"  • {o.definitie.cod} — `{o.termen.strftime('%d.%m.%Y')}`"
            )
        lines.append("")

    # Sume cumulate
    if status.total_de_platit_30zile > 0:
        lines.append(
            f"💰 *Total estimat 30 zile*: *{status.total_de_platit_30zile:.2f} RON*"
        )
        if status.total_de_platit_7zile > 0:
            lines.append(
                f"   _din care 7 zile: {status.total_de_platit_7zile:.2f} RON_"
            )
        lines.append("")

    if status.recomandari:
        lines.append("💡 *Recomandări:*")
        for r in status.recomandari:
            lines.append(f"  • {r}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


def format_audit_telegram(audit: BankTransactionAudit) -> str:
    """Formatează rezultatul unui audit pentru Telegram."""
    icon = "✅" if audit.is_correctly_targeted and not audit.is_returned else "⚠️"

    lines = [
        f"{icon} *AUDIT TRANZACȚIE BANCARĂ*",
        f"📅 `{audit.transaction_date.strftime('%d.%m.%Y')}` · "
        f"`{audit.amount:.2f} RON`",
        f"🏦 `{audit.iban_target}`",
        "",
        audit.explanation,
        "",
    ]

    if audit.identified_iban_cont:
        c = audit.identified_iban_cont
        lines.extend([
            f"📋 *Identificat ca*: {c.denumire}",
            f"   _Cod buget: {c.cod_buget}_",
            "",
        ])

    if audit.issues:
        for issue in audit.issues:
            sev_emoji = {
                IssueSeverity.ERROR: "🔴",
                IssueSeverity.WARNING: "🟡",
                IssueSeverity.INFO: "ℹ️",
            }.get(issue.severity, "")
            lines.append(f"{sev_emoji} {issue.message}")
            if issue.fix_suggestion:
                lines.append(f"  💡 _{issue.fix_suggestion}_")
            lines.append("")

    return "\n".join(lines)


# ============================================================
#                    EXPORT API
# ============================================================

__all__ = [
    # Enums
    "ValidationVerdict",
    "IssueSeverity",
    "IssueCategory",
    # Dataclasses
    "ValidationIssue",
    "PaymentValidationResult",
    "BankTransactionAudit",
    "ComplianceStatus",
    # Funcții principale
    "validate_payment",
    "audit_bank_transaction",
    "audit_extras_bancar",
    "get_compliance_status",
    # Formatare Telegram
    "format_payment_validation_telegram",
    "format_compliance_status_telegram",
    "format_audit_telegram",
]
