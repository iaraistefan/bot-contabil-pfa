"""
UI confirmare import extras bancar — LOGICĂ PURĂ (felia 3 PAS 4a).

Doar funcții pure (zero Telegram, zero DB): state machine peste un dict + text
builders + mapare categorie. Glue-ul async + commit-ul (PAS 4b) le apelează.

Fluxul:
  preview (felia 2) → buton → Ecran 1 (sumar) → pentru fiecare DE_VERIFICAT:
  business (+ categorie) / personală / sari → Ecran 3 (rezultat).

🛡️ UI-ul FILTREAZĂ (garda din post_bank = backup): `build_decisions` emite
categorie DOAR pentru bucketele postabile; restul → None, STRUCTURAL.
"""
from typing import List, Optional

from app.integrations.imports.classify import CHELTUIALA_BUSINESS, DE_VERIFICAT
# Single source pentru bucketele postabile (același set ca garda serviciului).
from app.integrations.imports.post_bank import _POSTABILE as POSTABLE_BUCKETS


# ── Opțiuni categorie pentru un DE_VERIFICAT confirmat business ──
# (key callback, label buton, category_code). Deductibilitatea corectă pe bani:
# combustibil/service 50%, restul 100%.
CATEGORY_CHOICES = [
    ("fuel", "⛽ Combustibil 50%", "fuel"),
    ("service", "🔧 Service 50%", "car_service"),
    ("other", "📦 Altă cheltuială 100%", "other_expense"),
]
_CHOICE_MAP = {key: code for key, _label, code in CATEGORY_CHOICES}


def category_from_choice(key: str) -> Optional[str]:
    """Mapează cheia de buton la category_code (None dacă necunoscută)."""
    return _CHOICE_MAP.get(key)


def _ron(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _short(s: Optional[str], n: int = 44) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[:n] + "…"


# ============================================================
#                    STATE MACHINE (pură)
# ============================================================

def init_state(clasificate: List, source_file_id: Optional[int]) -> dict:
    """Construiește starea de confirmare dintr-o listă clasificată.

    - CHELTUIALA_BUSINESS → decizie AUTO (categoria din clasificare).
    - DE_VERIFICAT        → cere decizie userului (intră în coada de verificat).
    - rest (VENIT_BOLT/PLATA/RETURNARE/COMISION) → None (niciodată postabil).

    Întoarce un dict NOU (apelat la fiecare extras → suprascrie curat starea veche).
    """
    decisions = {}
    deverificat_idx = []
    for i, r in enumerate(clasificate):
        if r.bucket == CHELTUIALA_BUSINESS:
            decisions[i] = r.categorie            # auto business
        elif r.bucket == DE_VERIFICAT:
            deverificat_idx.append(i)
            decisions[i] = None                   # până decide userul
        else:
            decisions[i] = None                   # niciodată postabil
    return {
        "clasificate": clasificate,
        "source_file_id": source_file_id,
        "deverificat_idx": deverificat_idx,
        "pos": 0,
        "decisions": decisions,
    }


def current_deverificat(state: dict):
    """(index, BankTxnClasificat) pentru DE_VERIFICAT-ul curent, sau None dacă gata."""
    idxs = state["deverificat_idx"]
    pos = state["pos"]
    if pos >= len(idxs):
        return None
    i = idxs[pos]
    return i, state["clasificate"][i]


def record_decision(state: dict, idx: int, category_code: Optional[str]) -> bool:
    """Înregistrează decizia pe DE_VERIFICAT-ul `idx` și avansează.

    `category_code`: str (business cu categorie) sau None (personală/sari).
    GARDĂ anti-stale: `idx` trebuie să fie exact DE_VERIFICAT-ul curent; altfel
    (buton vechi după o suprascriere/double-tap) → ignoră, întoarce False.
    """
    cur = current_deverificat(state)
    if cur is None or cur[0] != idx:
        return False
    state["decisions"][idx] = category_code
    state["pos"] += 1
    return True


def is_done(state: dict) -> bool:
    """True dacă toate DE_VERIFICAT au fost decise."""
    return state["pos"] >= len(state["deverificat_idx"])


def build_decisions(state: dict) -> List[Optional[str]]:
    """Listă paralelă cu `clasificate` pentru `post_bank_expenses`.

    🛡️ GARDĂ STRUCTURALĂ: categorie DOAR pentru bucketele postabile; orice
    altceva → None, indiferent de ce e în `decisions`. UI-ul nu poate emite
    o decizie pentru un bucket nepostabil (VENIT_BOLT/PLATA/RETURNARE/COMISION).
    """
    clasificate = state["clasificate"]
    decisions = state["decisions"]
    return [
        (decisions.get(i) if r.bucket in POSTABLE_BUCKETS else None)
        for i, r in enumerate(clasificate)
    ]


# ============================================================
#                    TEXT BUILDERS (pure)
# ============================================================

def format_screen1(clasificate: List) -> str:
    """Ecran 1 — sumar pe grup: business clare + de verificat."""
    business = [r for r in clasificate if r.bucket == CHELTUIALA_BUSINESS]
    deverif = [r for r in clasificate if r.bucket == DE_VERIFICAT]
    s_biz = sum(r.txn.suma for r in business)
    s_dv = sum(r.txn.suma for r in deverif)

    lines = ["📥 *Adaug cheltuieli din extras*", ""]
    if business:
        lines.append(f"✅ Cheltuieli business clare: {len(business)}  ({_ron(s_biz)} lei)")
    else:
        lines.append("✅ Cheltuieli business clare: 0")
    lines.append(f"🟡 De verificat: {len(deverif)}  ({_ron(s_dv)} lei)")
    if deverif:
        lines.append("   Pentru fiecare îmi spui: business sau personală?")
    lines.append("")
    lines.append("♻️ _Verific automat dublurile (ce e deja în registru sar)._")
    return "\n".join(lines)


def format_deverificat_prompt(pos: int, total: int, clasificat) -> str:
    """Ecran 2 — prompt pentru o tranzacție DE_VERIFICAT (1-indexat în text)."""
    t = clasificat.txn
    return (
        f"🟡 *Tranzacția {pos + 1}/{total}*\n"
        f"📤 {t.data.strftime('%d.%m.%Y')} · {_ron(t.suma)} lei\n"
        f"_{_short(t.descriere)}_\n\n"
        f"Ce e?"
    )


def format_result(res: dict) -> str:
    """Ecran 3 — rezultat din sumarul `post_bank_expenses` (transparent)."""
    lines = [
        "✅ *Gata.*",
        f"Am adăugat {res['posted']} cheltuieli — "
        f"{_ron(res.get('deductibil_sum', 0))} lei deductibili.",
    ]
    if res.get("skipped_personal"):
        lines.append(f"🙅 {res['skipped_personal']} sărite ca personale.")
    if res.get("skipped_dup"):
        lines.append(
            f"♻️ {res['skipped_dup']} dubluri ignorate "
            f"_(ai mai încărcat extrasul — erau deja în registru)._"
        )
    if res.get("skipped_blocked"):
        lines.append(f"⚠️ {res['skipped_blocked']} blocate (nepostabile).")
    lines.append("")
    lines.append("_Vezi în Registru / Raport._")
    return "\n".join(lines)
