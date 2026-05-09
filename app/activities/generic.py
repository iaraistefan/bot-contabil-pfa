"""
Activitate generică — fallback pentru utilizatori care nu au ales o activitate
specifică sau pentru cheltuieli care nu se încadrează în categoriile activității lor.
"""

from app.activities.base import (
    BaseActivity, ExpenseCategory, IncomeCategory,
    VATTreatment, DeductibilityRule,
)


class GenericActivity(BaseActivity):
    code = "generic"
    name = "Generic / Alte servicii"
    icon = "📌"
    description = "Activitate generică, categorii standard"
    caen_codes = []

    income_categories = [
        IncomeCategory(
            code="services_revenue",
            label="Venituri din servicii",
            icon="💰",
            keywords=["servicii", "prestari", "factura"],
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="704",
        ),
    ]

    expense_categories = [
        ExpenseCategory(
            code="materials",
            label="Materiale",
            icon="📦",
            keywords=["materiale", "consumabile", "papetarie"],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="6028",
        ),
        ExpenseCategory(
            code="services",
            label="Servicii (utilități, abonamente)",
            icon="🔧",
            keywords=["enel", "electrica", "engie", "apa", "salubritate"],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="605",
        ),
        ExpenseCategory(
            code="professional_fees",
            label="Onorarii notar/contabil/avocat",
            icon="📑",
            keywords=["notar", "contabil", "avocat", "consultanta"],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="622",
        ),
        ExpenseCategory(
            code="telecom",
            label="Telefon / Internet",
            icon="📱",
            keywords=["orange", "vodafone", "digi", "telekom", "telefon"],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (uz mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="626",
        ),
        ExpenseCategory(
            code="other_expense",
            label="Alte cheltuieli",
            icon="📌",
            keywords=[],
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="628",
        ),
    ]
