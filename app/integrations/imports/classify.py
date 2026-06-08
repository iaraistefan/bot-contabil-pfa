"""
Clasificator DETERMINIST pentru tranzacții de extras bancar (felia 2).

Strat separat peste `BankTxn` (parserul rămâne pur). Pe zona „ce e clar"
folosim reguli deterministe pe keyword + direcție (fără AI, fără halucinație,
gratuit, testabil). Ce e ambiguu (plăți card business vs personal) →
`DE_VERIFICAT` (userul decide; NU ghicim).

Buckete de nivel-EXTRAS (≠ categorii fiscale de registru):
  VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA, COMISION_BANCAR,
  CHELTUIALA_BUSINESS (reutilizează clasificatorul fiscal existent), DE_VERIFICAT.

Precedență (contează — unele descrieri prind mai multe):
  RETURNARE → PLATA → COMISION → BOLT(IN) → BUSINESS(OUT) → DE_VERIFICAT.
Direcția (IN/OUT) dezambiguizează (ex. o returnare poartă textul plății
returnate „Plata TVA D301..." DAR e IN → RETURNARE, nu PLATA).
"""
import re
from dataclasses import dataclass
from typing import Optional, Type

from .bank_statement import BankTxn

# Buckete (nivel extras)
VENIT_BOLT = "VENIT_BOLT"
PLATA_TAXA = "PLATA_TAXA"
RETURNARE_TAXA = "RETURNARE_TAXA"
COMISION_BANCAR = "COMISION_BANCAR"
CHELTUIALA_BUSINESS = "CHELTUIALA_BUSINESS"
DE_VERIFICAT = "DE_VERIFICAT"

SIGUR = "SIGUR"      # incredere: clasificare deterministă fermă
INCERT = "INCERT"    # incredere: ambiguu, userul decide (≠ bucket DE_VERIFICAT)

_SCORE_MIN = 6          # scor minim detect_expense_category pt. a fi „sigur"

# Zgomot din descrierile BT de plată card care ar păcăli detecția fiscală
# (ex. „comision tranzactie 0.00 RON" → fals platform_commission).
_NOISE = [
    re.compile(r"comision tranzactie\s+[\d.,]+\s+ron", re.I),
    re.compile(r"valoare tranzactie:?\s*[\d.,]+\s+eur", re.I),
]

# Hint obligație fiscală pt. etichetă (ex. „TVA D301 Ianuarie 2026")
_OBLIG_RE = re.compile(r"(TVA|Impozit)\s+(D\d{3})\s+([A-Za-zăâîșțĂÂÎȘȚ]+)\s+(\d{4})", re.I)


@dataclass(frozen=True)
class BankTxnClasificat:
    """Rezultatul clasificării unei tranzacții de extras (strat peste BankTxn)."""
    txn: BankTxn
    bucket: str
    eticheta: str
    categorie: Optional[str] = None     # cod fiscal, doar unde e clar (ex. ride_revenue, fuel)
    deductibil: Optional[int] = None    # pct (100/50/0) sau None (n/a)
    incredere: str = SIGUR              # SIGUR | DE_VERIFICAT


def _denoise(text: str) -> str:
    for pat in _NOISE:
        text = pat.sub("", text)
    return text


def _oblig_hint(descriere: str) -> Optional[str]:
    m = _OBLIG_RE.search(descriere or "")
    if not m:
        return None
    tip, decl, luna, an = m.group(1), m.group(2).upper(), m.group(3), m.group(4)
    return f"{tip} {decl} {luna.capitalize()} {an}"


def classify_bt(txn: BankTxn, activity: Type) -> BankTxnClasificat:
    """Clasifică o tranzacție de extras într-un bucket de nivel-extras.

    Pur, determinist. `activity` = clasa de activitate a user-ului (pt.
    reutilizarea `detect_expense_category` pe ramura business).
    """
    d = (txn.descriere or "").lower()
    direction = txn.directie

    # 1. RETURNARE_TAXA — revers de plată (IN); poartă textul plății returnate
    if direction == "IN" and "returnare" in d:
        hint = _oblig_hint(txn.descriere)
        eticheta = (
            f"Returnare taxă respinsă ({hint})" if hint
            else "Returnare taxă (plată respinsă)"
        )
        return BankTxnClasificat(txn, RETURNARE_TAXA, eticheta, incredere=SIGUR)

    # 2. PLATA_TAXA — plată obligație către Trezorerie (OUT)
    if direction == "OUT" and "trezor" in d:
        hint = _oblig_hint(txn.descriere)
        eticheta = (
            f"Plată obligație fiscală ({hint})" if hint
            else "Plată obligație fiscală"
        )
        # deductibil rămâne None: e decontare de obligație, NU cheltuială de activitate
        return BankTxnClasificat(txn, PLATA_TAXA, eticheta, incredere=SIGUR)

    # 3. COMISION_BANCAR — comision/taxă de cont (OUT), deductibil 100%
    if direction == "OUT" and any(
        k in d for k in ("comision plata", "taxa rapoarte", "nota contabila")
    ):
        return BankTxnClasificat(
            txn, COMISION_BANCAR, "Comision bancar",
            deductibil=100, incredere=SIGUR,
        )

    # 4. VENIT_BOLT — încasare din activitate (IN)
    if direction == "IN" and "bolt" in d:
        return BankTxnClasificat(
            txn, VENIT_BOLT, "Venit Bolt",
            categorie="ride_revenue", incredere=SIGUR,
        )

    # 5. CHELTUIALA_BUSINESS — OUT recunoscut de clasificatorul fiscal existent
    #    (combustibil/service/etc.) pe text DEZGOMOTAT (fără „comision tranzactie")
    if direction == "OUT":
        cat, score = activity.detect_expense_category(None, _denoise(txn.descriere or ""))
        if cat is not None and score >= _SCORE_MIN:
            ded = activity.get_deductibility_pct(cat.code)
            return BankTxnClasificat(
                txn, CHELTUIALA_BUSINESS, cat.label,
                categorie=cat.code, deductibil=ded, incredere=SIGUR,
            )

    # 6. fallback — ambiguu/necunoscut (ex. plată card merchant) → userul decide
    return BankTxnClasificat(
        txn, DE_VERIFICAT, "De verificat", incredere=INCERT,
    )
