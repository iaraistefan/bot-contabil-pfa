"""
UI confirmare plăți de taxe achitate (felia 5c-c) — LOGICĂ PURĂ + sync.

Userul vede plățile de taxe REALE din extras (după compensare, felia 5a) și
confirmă marcarea lor ca achitate în obligații (felia 5b/5c-a). Mirror al
`bank_import_ui` (felia 3 PAS 4a/4b): aici partea PURĂ + `finalize_tax_recording`
sync; glue-ul async (handlere callback `banktax|*`) vine în 5c-c-2.

Plățile reale = `compensate` — respinsele deja excluse. Confirmare PE GRUP
(confirmă-tot), fără excludere per-item (plățile-s deja filtrate de compensare).
"""
import logging
from typing import List, Optional, Set

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.integrations.imports.dedup import compute_fingerprints
from app.integrations.imports.tax_payments import compensate, real_payment_indices
from app.services import bank_import_ui

logger = logging.getLogger(__name__)

_TAX_STATE_KEY = "bank_tax_pending"

_LUNI_NUME = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


def _ron(x: float) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


# ============================================================
#                    STATE / HELPERS (pure)
# ============================================================

def real_tax_payments(clasificate: List) -> List:
    """Plățile de taxe REALE (după compensarea respinselor) — de propus userului."""
    return compensate(clasificate)


def has_real_tax(clasificate: List) -> bool:
    """True dacă există plăți de taxe reale → butonul „Marchează taxele" apare."""
    return bool(compensate(clasificate))


def real_tax_fingerprints(clasificate: List) -> Set[str]:
    """Amprentele plăților reale (confirmă-tot = tot setul). FINGERPRINT (stabil),
    NU index — peste tot extrasul (`compute_fingerprints` aliniat pe index, intern).
    """
    fps = compute_fingerprints([r.txn for r in clasificate])
    return {fps[i] for i in real_payment_indices(clasificate)}


# ============================================================
#                    TEXT BUILDERS (pure)
# ============================================================

def format_tax_propose(real_payments: List) -> str:
    """Ecranul de propunere: plățile reale (tip · perioadă — sumă)."""
    lines = [
        "✅ *Plăți de taxe găsite în extras*",
        "_Acestea apar achitate (au trecut, nu au fost respinse):_",
        "",
    ]
    for r in real_payments:
        o = r.oblig
        luna = _LUNI_NUME.get(o.luna, str(o.luna))
        lines.append(f"  • {o.declaratie} · {luna} {o.an} — *{_ron(r.txn.suma)} lei*")
    lines.append("")
    lines.append("Le marchez ca *achitate* în obligații?")
    return "\n".join(lines)


def format_tax_result(outcome: dict) -> str:
    """Rezultatul: succes / re-import / eroare (tot-sau-nimic transparent)."""
    if not outcome.get("ok"):
        return (
            "⚠️ A apărut o eroare. *Nimic nu a fost marcat* în obligații.\n"
            "Reîncearcă — extrasul e încă valid."
        )
    res = outcome.get("result", {})
    recorded = res.get("recorded", 0)
    if recorded == 1:
        lines = ["✅ *Gata.*", "Am marcat *1 obligație* ca achitată din extras."]
    else:
        lines = ["✅ *Gata.*",
                 f"Am marcat *{recorded} obligații* ca achitate din extras."]
    if res.get("skipped_dup"):
        lines.append(
            f"♻️ {res['skipped_dup']} erau deja marcate (ai mai încărcat extrasul)."
        )
    return "\n".join(lines)


# ============================================================
#       COMMIT TOT-SAU-NIMIC (sync, testabil — money-critical)
# ============================================================

def finalize_tax_recording(
    session, *, user_id, source_file_id, clasificate, confirmed_fingerprints
) -> dict:
    """Înregistrează plățile confirmate + commit TOT-SAU-NIMIC.

    `record_tax_payments` (5c-a) NU comite; aici un singur commit la final / rollback
    pe orice excepție = zero înregistrare parțială. Mirror `finalize_bank_post`.
    Întoarce {ok, result|error}.
    """
    from app.integrations.imports.tax_recording import record_tax_payments
    try:
        res = record_tax_payments(
            session, user_id=user_id, source_file_id=source_file_id,
            clasificate=clasificate, confirmed_fingerprints=confirmed_fingerprints,
        )
        session.commit()
        return {"ok": True, "result": res}
    except Exception as e:
        session.rollback()
        logger.error(f"finalize_tax_recording user={user_id}: {e}")
        return {"ok": False, "error": str(e)}


# ============================================================
#                    STARE (context.user_data)
# ============================================================
# Cheie SEPARATĂ de `bank_pending` (cheltuieli, felia 3) → fluxuri independente.

def store_tax_state(context, clasificate, source_file_id, user_id) -> None:
    context.user_data[_TAX_STATE_KEY] = {
        "clasificate": clasificate,
        "source_file_id": source_file_id,
        "user_id": user_id,
    }


def get_tax_state(context):
    return context.user_data.get(_TAX_STATE_KEY)


def clear_tax_state(context) -> None:
    context.user_data.pop(_TAX_STATE_KEY, None)


# ============================================================
#                    TASTATURI (inline)
# ============================================================

def preview_button(n_tax: int) -> InlineKeyboardButton:
    """Butonul de sub preview pentru marcarea taxelor achitate (5c-c)."""
    return InlineKeyboardButton(
        f"✅ Marchează taxele achitate ({n_tax})", callback_data="banktax|start"
    )


def build_preview_keyboard(
    has_postable: bool, has_real_tax: bool, n_tax: int
) -> Optional[InlineKeyboardMarkup]:
    """Keyboard-ul de sub preview: cheltuieli (felia 3) + taxe (5c-c), condiționat.

    🔑 Când DOAR cheltuieli (has_real_tax=False) → IDENTIC cu `kb_preview_button()`
    (refolosește `bank_import_ui.preview_button`) → adăugarea 5c-c e invizibilă pe
    extrasele fără plăți de taxe reale. None dacă niciun buton.
    """
    rows = []
    if has_postable:
        rows.append([bank_import_ui.preview_button()])
    if has_real_tax:
        rows.append([preview_button(n_tax)])
    return InlineKeyboardMarkup(rows) if rows else None


def _kb_propose() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Da, marchează toate", callback_data="banktax|confirm")],
        [InlineKeyboardButton("❌ Nu", callback_data="banktax|cancel")],
    ])


# ============================================================
#       HANDLERE ASYNC (glue subțire peste logica pură/sync)
# ============================================================

async def _finalize(query, context, state) -> None:
    from db import get_session
    confirmed = real_tax_fingerprints(state["clasificate"])   # confirmă-tot, recalculat
    session = get_session()
    try:
        outcome = finalize_tax_recording(
            session,
            user_id=state["user_id"],
            source_file_id=state["source_file_id"],
            clasificate=state["clasificate"],
            confirmed_fingerprints=confirmed,
        )
    finally:
        session.close()

    await query.edit_message_text(format_tax_result(outcome), parse_mode="Markdown")
    if outcome["ok"]:
        clear_tax_state(context)          # succes → curăță; eroare → păstrat (retry=re-upload)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Gestionează callback-urile `banktax|*` (rutat din `handle_callback_query`,
    care a făcut deja `query.answer()`)."""
    query = update.callback_query
    parts = query.data.split("|")
    action = parts[1] if len(parts) > 1 else ""

    state = get_tax_state(context)
    if not state:
        await query.edit_message_text(
            "⏳ Sesiunea a expirat. Încarcă extrasul din nou."
        )
        return

    if action == "cancel":
        clear_tax_state(context)
        await query.edit_message_text("❌ Anulat. Nicio taxă marcată.")
        return

    if action == "start":
        reale = real_tax_payments(state["clasificate"])
        await query.edit_message_text(
            format_tax_propose(reale),
            parse_mode="Markdown",
            reply_markup=_kb_propose(),
        )
        return

    if action == "confirm":
        await _finalize(query, context, state)
        return
