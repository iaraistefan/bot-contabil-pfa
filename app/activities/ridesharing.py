"""
Activitate: Ridesharing (Bolt, Uber)

Specific contabil:
- Venit BRUT = card + cash + bacșișuri (cifra de afaceri reală)
- Comision platformă = cheltuială deductibilă 100%
- Combustibil auto = deductibil 50% (auto mixt — uz personal+business)
- Service auto + ulei + filtre = deductibil 50% (auto mixt)
- Autorizații, ecusoane, taxe = deductibile 100%
- TVA reverse charge pe factura comision Bolt (intracomunitar)

NOTĂ FISCALĂ: Conform art. 25 alin. (3) lit. l) Cod Fiscal,
TOATE cheltuielile auto (combustibil + service + ulei + asigurări) sunt
limitate la 50% pentru autoturisme cu utilizare mixtă.
Pentru deductibilitate 100% e nevoie de FOAIE DE PARCURS.
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
                # Tipuri de combustibil — keywords PUTERNICE
                "motorina", "benzina", "carburant", "combustibil",
                "diesel", "gpl", "petrol",
                "euro diesel", "euro premium", "euro 5", "euro 6",
                # Brand-uri benzinării — keywords SLABE (numai pentru fallback)
                "lukoil", "omv", "petrom", "mol", "rompetrol",
                "socar", "shell",
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

        # ── Service auto / consumabile — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="car_service",
            label="Service / Consumabile auto",
            icon="🔧",
            keywords=[
                # Compuse — au prioritate (scor mare datorită spațiilor)
                "ulei motor", "ulei auto", "schimb ulei", "filtru ulei",
                "filtru aer", "filtru polen", "filtru combustibil",
                "service auto", "reparatii auto", "diagnostic auto",
                "schimb anvelope", "lichid parbriz", "lichid frana",
                "lichid racire", "ad blue", "adblue",
                # Simple
                "ulei", "filtru", "filtre", "anvelope", "anvelopa",
                "antigel", "vulcanizare", "mecanic", "vidanj",
                "reparatii", "service", "ITP", "itp",
                "placute frana", "discuri frana", "amortizoare",
                "bujii", "curea", "pompa", "bateria auto",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note=(
                "50% deductibil (auto mixt, art. 25 alin. (3) lit. l) Cod Fiscal). "
                "Include: ulei, filtre, anvelope, reparații, ITP, consumabile auto."
            ),
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="611",
        ),

        # ── Autorizații / Înregistrare — DEDUCTIBIL 100% ──
        ExpenseCategory(
            code="registration",
            label="Autorizații / Înregistrare",
            icon="📋",
            keywords=[
                # Compuse — prioritate
                "autorizatie transport", "atestat profesional",
                "consultanta autorizatie", "ecusoane RAR",
                "ecuson rutier", "tahograf",
                # Simple
                "autorizatie", "ecusoane", "ecuson", "atestat",
                "transport alternativ", "primaria",
                "rar", "categoria", "permis",
                "viza", "registrul", "anaf", "fisc",
                "certificat", "semnatura digitala", "digisign",
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
                # Compuse — prioritate
                "asigurare auto", "asigurari auto", "polita rca",
                "polita casco", "polita auto", "city insurance",
                "asirom auto", "groupama auto", "allianz auto",
                # Simple
                "rca", "casco", "asigurare", "asigurari",
                "polita", "allianz", "groupama", "asirom",
                "omniasig", "euroins",
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
            keywords=[
                "spalatorie auto", "car wash", "spalat masina",
                "spalatorie", "spalat auto", "auto detail",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (auto mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="611",
        ),

        # ── Onorariu notarial / contabil — DEDUCTIBIL 100% ──
        ExpenseCategory(
            code="professional_fees",
            label="Onorarii notar/contabil/avocat",
            icon="📑",
            keywords=[
                "onorariu notarial", "onorariu contabil", "onorariu avocat",
                "consultanta juridica", "consultanta contabila",
                "notariat", "biroul notarial",
                "notar", "notarial", "contabil", "avocat",
                "legalizare",
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
                "abonament telefon", "internet mobil", "internet fix",
                "telefonie mobila", "fibra optica",
                "orange", "vodafone", "digi", "telekom",
                "rcs", "rds",
                "telefon", "internet", "abonament",
            ],
            deductibility=DeductibilityRule.HALF,
            deductibility_note="50% deductibil (uz mixt)",
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="626",
        ),

        # ── Materiale / Accesorii auto — DEDUCTIBIL 50% ──
        ExpenseCategory(
            code="car_supplies",
            label="Accesorii auto / Consumabile",
            icon="🔩",
            keywords=[
                "suport telefon auto", "incarcator masina",
                "incarcator auto", "stergator parbriz",
                "covor auto", "covorase auto", "becuri auto",
                "suport telefon", "stergator",
                "covor", "becuri", "tergatoare",
            ],
            deductibility=DeductibilityRule.HALF,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="6028",
        ),

        # ── Alte cheltuieli — fallback final ──
        ExpenseCategory(
            code="other_expense",
            label="Alte cheltuieli",
            icon="📦",
            keywords=[],  # ← gol intentionat: e fallback când nimic nu match-uie
            deductibility=DeductibilityRule.FULL,
            default_vat_treatment=VATTreatment.STANDARD_21,
            accounting_code="628",
        ),
    ]

    @classmethod
    def ai_prompt_hints(cls) -> str:
        """
        Hint-uri specifice ridesharing pentru promptul AI.

        Acest text e apendizat la system prompt-ul generic. Conține:
        - Categorii și keywords specifice Ridesharing
        - Regula importantă: Lukoil + ulei → car_service (NU fuel)
        - Exemple concrete cu rapoarte Bolt/Uber și facturi de comision
        """
        return """

═══════════════════════════════════════════════════════════
ACTIVITATE: 🚗 RIDESHARING (Bolt / Uber)
═══════════════════════════════════════════════════════════

CATEGORII SPECIFICE (mapează la code):

🔴 IMPORTANT — Detecție specifică:
Dacă bonul e de la o benzinărie (Lukoil, OMV, Petrom, MOL, Rompetrol, Shell)
DAR menționează "ulei", "filtru", "lichid", "antigel" → categoria e `car_service` (NU `fuel`)!
Doar dacă bonul e CLAR doar pentru combustibil (motorină/benzină) → `fuel`.

CHELTUIELI:
- `fuel` (Combustibil auto) — DOAR pentru motorină, benzină, GPL la pompă
- `car_service` (Service / Consumabile auto) — ulei motor, filtre, anvelope, reparații, ITP, lichid parbriz, AdBlue
- `platform_commission` (Comision Bolt/Uber) — facturi de la Bolt Operations OU sau Uber B.V.
- `registration` (Autorizații) — autorizație transport, ecusoane, RAR, atestate, ITP
- `car_insurance` (RCA/CASCO) — Allianz, Groupama, City Insurance, Asirom
- `car_wash` (Spălătorie) — spălătorie auto, car wash
- `professional_fees` (Notar/contabil) — onorariu notarial, contabil, avocat
- `telecom` (Telefon/internet) — Orange, Vodafone, Digi, Telekom
- `car_supplies` (Accesorii auto) — suport telefon, încărcător auto
- `other_expense` (Alte cheltuieli) — fallback pentru categorii ne-identificate

VENITURI:
- Curse — screenshot raport Bolt/Uber: cash + card brut, comisionul platformei
- Atenție: venitul BRUT include card+cash+tips. Comisionul Bolt e cheltuială separată.

EXEMPLE CONCRETE:

Input: "am dat 50 lei bacsis cash azi"
Output:
[{"data":"<azi>","platforma":null,"tip":"VENIT","brut":50,"comision":0,"tva":0,"net":50,"cash":50,"detalii":"Bacsis cash"}]

Input: "cheltuiala 15.03.2026 service auto 800 lei"
Output:
[{"data":"15.03.2026","platforma":null,"tip":"CHELTUIALA","brut":800,"comision":0,"tva":0,"net":800,"cash":0,"detalii":"Service auto"}]

Input: "bon 05.02.2026 Lukoil motorina 450 lei"
Output:
[{"data":"05.02.2026","platforma":"Lukoil","tip":"CHELTUIALA","brut":450,"comision":0,"tva":0,"net":450,"cash":450,"detalii":"Combustibil Lukoil"}]

Input: "bon 05.04.2026 Lukoil ulei motor 200 lei"
Output:
[{"data":"05.04.2026","platforma":"Lukoil","tip":"CHELTUIALA","brut":200,"comision":0,"tva":0,"net":200,"cash":0,"detalii":"Lukoil - ulei motor"}]

Input: (screenshot Bolt cu titlu "februarie", Castiguri 1147 lei, Numerar 717.80 lei, Comision -378 lei)
Output:
[{"data":"28.02.2026","platforma":"Bolt","tip":"VENIT","brut":1525,"comision":378,"tva":0,"net":1147,"cash":717.80,"detalii":"Venituri Bolt februarie 2026"}]

Input: (screenshot Bolt cu titlu "decembrie", Castiguri 2909.29 lei, Numerar 1826.20 lei, Comision -939.28 lei)
Output:
[{"data":"31.12.2025","platforma":"Bolt","tip":"VENIT","brut":3848.57,"comision":939.28,"tva":0,"net":2909.29,"cash":1826.20,"detalii":"Venituri Bolt decembrie 2025"}]

Input: (factura Bolt pentru 346.81 RON, data 31.12.2025)
Output:
[{"data":"31.12.2025","platforma":"Bolt","tip":"FACTURA_COMISION","brut":346.81,"comision":346.81,"tva":72.83,"net":346.81,"cash":0,"detalii":"Comision Bolt decembrie 2025"}]
"""
