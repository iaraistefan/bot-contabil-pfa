"""
Activitate: Ridesharing (Bolt, Uber)

Specific contabil:
- Venit BRUT = card + cash + bacșișuri (cifra de afaceri reală)
- Comision platformă = cheltuială deductibilă 100%
- Combustibil auto = deductibil 50% (auto mixt — uz personal+business)
- Service auto = deductibil 50% (auto mixt)
- Autorizații, ecusoane, taxe = deductibile 100%
- TVA reverse charge pe factura comision Bolt (intracomunitar)
"""

from app.activities.base import (
    BaseActivity, ExpenseCategory, IncomeCategory,
    VATTreatment, DeductibilityRule,
)


class RidesharingActivity(BaseActivity):
    code = "ridesharing"
    name = "Ridesharing (Bolt/Uber)"
    icon = "🚗"
    description = "Transport de persoane prin platforme digitale"
    caen_codes = ["4932", "4931", "4939"]

    # ============================================================
    #                       VENITURI
    # ============================================================
    income_categories = [
        IncomeCategory(
            code="ride_revenue",
            label="Venituri brute curse",
            icon="🚕",
            keywords=["bolt", "uber", "curse", "ridesharing"],
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="704",
        ),
        IncomeCategory(
            code="tip_revenue",
            label="Bacșișuri",
            icon="💵",
            keywords=["bacsis", "tip", "tips"],
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="704",
        ),
    ]

    # ============================================================
    #                       CHELTUIELI
    # ============================================================
    expense_categories = [
        # ── Combustibil — DEDUCTIBIL 50% (auto mixt) ──
        ExpenseCategory(
            code="fuel",
            label="Combustibil auto",
            icon="⛽",
            keywords=[
                "lukoil", "omv", "petrom", "mol", "rompetrol",
                "socar", "shell", "benzina", "motorina", "carburant",
                "combustibil", "petrol", "diesel",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note=(
                "50% deductibil (auto mixt, art. 25 alin. (3) lit. l) Cod Fiscal). "
                "Pentru deductibilitate 100% e nevoie de foaie de parcurs."
            ),
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="6022",
        ),

        # ── Comision platformă — DEDUCTIBIL 100% + reverse charge ──
        ExpenseCategory(
            code="platform_commission",
            label="Comision platformă (Bolt/Uber)",
            icon="💼",
            keywords=[
                "comision", "commission", "service fee",
                "bolt operations", "uber bv", "uber eats",
            ],
            deductibility=DeductibilityRule.FULL,
            deductibility_note=(
                "100% deductibil. Atenție: factura intracomunitară "
                "se declară prin TVA reverse charge (D301 + D390)."
            ),
            default_vat_treatment=VATTreatment.REVERSE_CHARGE,
            vat_note="Reverse charge intracomunitar (servicii electronice UE)",
            accounting_code="628",
        ),

        # ── Service auto — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="car_service",
            label="Service / Reparații auto",
            icon="🔧",
            keywords=[
                "service auto", "reparatii", "anvelope", "ulei motor",
                "filtru", "schimb ulei", "vulcanizare", "mecanic",
                "vidanj", "diagnostic auto",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (auto mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="611",
        ),

        # ── Autorizații / Înregistrare — DEDUCTIBIL 100% ──
        ExpenseCategory(
            code="registration",
            label="Autorizații / Înregistrare",
            icon="📋",
            keywords=[
                "autorizatie", "ecusoane", "transport alternativ",
                "primaria", "rar", "atestat", "categoria",
                "permis", "viza", "consultanta autorizatie",
            ],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="635",
        ),

        # ── Asigurări auto — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="car_insurance",
            label="Asigurări auto (RCA, CASCO)",
            icon="🛡️",
            keywords=[
                "rca", "casco", "asigurare", "asigurari auto",
                "polita", "allianz", "groupama", "city insurance",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (auto mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="613",
        ),

        # ── Spălătorie auto — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="car_wash",
            label="Spălătorie auto",
            icon="🧽",
            keywords=["spalatorie", "car wash", "spalat masina"],
            deductibility=DeductibilityRule.HALF,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="611",
        ),

        # ── Onorariu notarial / contabil — DEDUCTIBIL 100% ──
        ExpenseCategory(
            code="professional_fees",
            label="Onorarii notar/contabil/avocat",
            icon="📑",
            keywords=[
                "notar", "notarial", "contabil", "avocat",
                "consultanta juridica", "legalizare",
            ],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="622",
        ),

        # ── Telefonie / Internet — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="telecom",
            label="Telefon / Internet",
            icon="📱",
            keywords=[
                "orange", "vodafone", "digi", "telekom",
                "telefon", "internet", "abonament telefon",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (uz mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="626",
        ),

        # ── Materiale / Accesorii auto ──
        ExpenseCategory(
            code="car_supplies",
            label="Accesorii auto / Consumabile",
            icon="🔩",
            keywords=[
                "suport telefon", "incarcator masina",
                "stergator", "antigel", "lichid parbriz",
            ],
            deductibility=DeductibilityRule.HALF,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="6028",
        ),

        # ── Alte cheltuieli ──
        ExpenseCategory(
            code="other_expense",
            label="Alte cheltuieli",
            icon="📦",
            keywords=[],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="628",
        ),
    ]

    @classmethod
    def ai_prompt_hints(cls) -> str:
        """Hint-uri specifice ridesharing pentru promptul AI."""
        return """
## Categorii specifice Ridesharing (Bolt/Uber):

### Venituri:
- **Curse** — screenshot raport Bolt/Uber: cash + card brut, comisionul platformei
- Atenție: venitul BRUT include card+cash+tips. Comisionul Bolt e cheltuială separată.

### Cheltuieli (mapează la code):
- `fuel` (Combustibil auto) — keywords: lukoil, omv, mol, petrom, shell, rompetrol, motorina, benzina
- `platform_commission` (Comision Bolt/Uber) — facturi de la Bolt Operations OU sau Uber B.V.
- `car_service` (Service auto) — anvelope, ulei, reparații, schimb piese
- `registration` (Autorizații) — autorizație transport, ecusoane, RAR, atestate
- `car_insurance` (RCA/CASCO) — Allianz, Groupama, City Insurance
- `car_wash` (Spălătorie) — spălătorie auto, car wash
- `professional_fees` (Notar/contabil) — onorariu notarial, contabil, avocat
- `telecom` (Telefon/internet) — Orange, Vodafone, Digi, Telekom
- `car_supplies` (Accesorii auto) — suporturi telefon, încărcătoare auto
- `other_expense` (Alte cheltuieli) — fallback pentru categorii ne-identificate
"""
