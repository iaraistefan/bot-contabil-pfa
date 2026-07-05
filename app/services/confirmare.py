"""
Pas R1 - Confirmare date extrase de AI inainte de salvare.
Pas R1.2 - Detectare duplicate pe continut (data + suma).

PROBLEMA rezolvata:
- Datele extrase de AI se salveau DIRECT in contabilitate (risc amenda).
- Dedup-ul exista doar pe POZA (SHA256). Acelasi document introdus de
  doua ori (text + poza, sau doua poze) intra de doua ori.

SOLUTIA:
- Dupa extractie, bot-ul afiseaza ce a citit si cere confirmare umana.
- Daca un document cu aceeasi data + suma exista deja, afiseaza
  un AVERTISMENT de posibil duplicat (nu blocheaza - user-ul decide).

ARHITECTURA:
Datele "pending" traiesc in context.user_data intre extractie si confirmare.
Modulul gestioneaza DOAR UI-ul. Salvarea efectiva si detectarea
duplicatelor (query DB) raman in bot_contabil.py.

Callback namespace: "confirm"
  confirm|save              -> gestionat de bot_contabil (salvare efectiva)
  confirm|cancel            -> anuleaza, sterge pending
  confirm|edit              -> meniu corectare
  confirm|item|<idx>        -> alege documentul de corectat (multi-item)
  confirm|field|<idx>|<f>   -> alege campul de corectat
  confirm|tip|<idx>|<TIP>   -> seteaza tipul (buton)
  confirm|back              -> inapoi la ecranul de confirmare
"""

import logging
from datetime import date, datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from app.ai.schemas import ExtractionItem
from app.domain.tax_rules import cota_tva

logger = logging.getLogger(__name__)


def _data_item(item: dict) -> date:
    """Data facturii din item (format DD.MM.YYYY) ca `date`; fallback la azi."""
    raw = item.get("data")
    if raw:
        try:
            return datetime.strptime(raw, "%d.%m.%Y").date()
        except (ValueError, TypeError):
            pass
    return date.today()


_PENDING_KEY = "confirm_pending"
_EDIT_KEY = "confirm_edit"

TIP_LABELS = {
    "VENIT": "Venit",
    "CHELTUIALA": "Cheltuială",
    "FACTURA_COMISION": "Factură comision",
}
TIP_ICONS = {
    "VENIT": "💰",
    "CHELTUIALA": "🛒",
    "FACTURA_COMISION": "📄",
}


def _editable_fields(tip):
    """Returneaza lista (field_key, label, is_numeric) editabila pentru un tip."""
    if tip == "VENIT":
        return [
            ("data", "📅 Data", False),
            ("platforma", "🏢 Platformă", False),
            ("net", "💵 Venit net", True),
            ("cash", "💵 Cash", True),
            ("tip", "🏷️ Tip", False),
        ]
    if tip == "FACTURA_COMISION":
        return [
            ("data", "📅 Data", False),
            ("platforma", "🏢 Furnizor", False),
            ("comision", "💵 Bază comision", True),
            ("tip", "🏷️ Tip", False),
        ]
    # CHELTUIALA (default)
    return [
        ("data", "📅 Data", False),
        ("platforma", "🏢 Furnizor", False),
        ("brut", "💵 Sumă", True),
        ("detalii", "📝 Descriere", False),
        ("tip", "🏷️ Tip", False),
    ]


# ============================================================
#                    STARE (user_data)
# ============================================================

def store_pending(context, items_dicts, source_file_id, raw_response,
                  prompt_version, duplicates=None):
    """
    Salveaza datele extrase ca 'pending' in user_data (nu in DB).

    duplicates: dict optional {item_index: {id, data_doc, platforma,
                brut, created_at_str}} - posibile duplicate detectate.
    """
    context.user_data[_PENDING_KEY] = {
        "items": items_dicts,
        "source_file_id": source_file_id,
        "raw_response": (raw_response or "")[:10000],
        "prompt_version": prompt_version,
        "duplicates": duplicates or {},
    }
    context.user_data.pop(_EDIT_KEY, None)


def get_pending(context):
    return context.user_data.get(_PENDING_KEY)


def clear_pending(context):
    context.user_data.pop(_PENDING_KEY, None)
    context.user_data.pop(_EDIT_KEY, None)


def has_pending(context) -> bool:
    return _PENDING_KEY in context.user_data


def is_editing(context) -> bool:
    """True daca user-ul e in wizard-ul de editare a unui camp."""
    return _EDIT_KEY in context.user_data


def cancel_edit(context):
    context.user_data.pop(_EDIT_KEY, None)


# ============================================================
#                    FORMATARE
# ============================================================

def _fmt_num(v) -> str:
    try:
        return f"{float(v or 0):.2f}"
    except (ValueError, TypeError):
        return "0.00"


def _format_item(idx: int, item: dict, dup_info=None) -> str:
    """Formateaza un document extras ca bloc text. dup_info = avertisment duplicat."""
    tip = item.get("tip", "CHELTUIALA")
    tip_label = TIP_LABELS.get(tip, tip)
    icon = TIP_ICONS.get(tip, "📄")
    lines = [f"{icon} *Document #{idx + 1}* — {tip_label}"]
    lines.append(f"📅 Data: {item.get('data') or '— (pun data de azi)'}")

    if tip == "VENIT":
        lines.append(f"🏢 Platformă: {item.get('platforma') or '—'}")
        lines.append(f"💵 Venit net: {_fmt_num(item.get('net'))} RON")
        lines.append(f"💵 Cash: {_fmt_num(item.get('cash'))} RON")
        card = (item.get("net") or 0) - (item.get("cash") or 0)
        lines.append(f"💳 Card: {_fmt_num(card)} RON")
    elif tip == "FACTURA_COMISION":
        lines.append(f"🏢 Furnizor: {item.get('platforma') or '—'}")
        lines.append(f"💵 Bază: {_fmt_num(item.get('comision'))} RON")
        lines.append(f"🏛️ TVA (21%): {_fmt_num(item.get('tva'))} RON")
    else:  # CHELTUIALA
        lines.append(f"🏢 Furnizor: {item.get('platforma') or '—'}")
        lines.append(f"💵 Sumă: {_fmt_num(item.get('brut'))} RON")
        if item.get("detalii"):
            lines.append(f"📝 {item.get('detalii')}")

    # Avertisment duplicat (Pas R1.2)
    if dup_info:
        added = dup_info.get("created_at_str", "")
        added_part = f", adăugat {added}" if added else ""
        doc_id = dup_info.get("id")
        match_type = dup_info.get("match_type", "data_suma")
        if match_type == "numar":
            # Match pe numarul documentului = duplicat SIGUR
            nr = dup_info.get("numar_document") or "?"
            lines.append(
                f"\n🚫 *DUPLICAT* — documentul cu numărul `{nr}` "
                f"e deja înregistrat (#{doc_id}{added_part}).\n"
                f"L-ai mai trimis o dată — nu-l punem de două ori."
            )
        else:
            # Match pe data + suma = doar POSIBIL duplicat
            lines.append(
                f"\n⚠️ *POSIBIL DUPLICAT* — mai am un document "
                f"cu aceeași dată și sumă (#{doc_id}{added_part}).\n"
                f"Dacă e alt bon real, îl salvezi liniștit."
            )

    return "\n".join(lines)


# ============================================================
#                    AFISARE ECRAN CONFIRMARE
# ============================================================

async def show_confirmation(chat_id, context, query=None):
    """
    Afiseaza ecranul de confirmare cu datele pending.
    Daca 'query' e dat, editeaza mesajul existent; altfel trimite unul nou.
    """
    pending = get_pending(context)
    if not pending:
        return

    items = pending["items"]
    duplicates = pending.get("duplicates", {})

    blocks = []
    for i, it in enumerate(items):
        # duplicates pot avea chei int sau str (dupa serializare)
        dup = duplicates.get(i) or duplicates.get(str(i))
        blocks.append(_format_item(i, it, dup_info=dup))

    has_dup = bool(duplicates)
    # Duplicat sigur = cel putin un match pe numarul documentului
    has_sure_dup = any(
        (d or {}).get("match_type") == "numar"
        for d in duplicates.values()
    )

    text = (
        "🔍 *Am citit documentul — verifică, te rog*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        + "\n\n".join(blocks)
        + "\n\n━━━━━━━━━━━━━━━━━━━━\n"
    )
    if has_sure_dup:
        text += (
            "🚫 _Acest document este DEJA în contabilitate. "
            "Salvează doar dacă ești sigur că vrei o a doua înregistrare._"
        )
    elif has_dup:
        text += (
            "⚠️ _Un document similar pare deja înregistrat. "
            "Verifică să nu fie introdus de două ori._"
        )
    else:
        text += (
            "_Aruncă un ochi pe sumă și dată. Dacă ceva nu e bine, corectează "
            "înainte să salvezi._"
        )

    if has_sure_dup:
        save_label = "🚫 Salvează oricum (e duplicat)"
    elif has_dup:
        save_label = "⚠️ Salvează oricum"
    else:
        save_label = "✅ Confirmă și salvează"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(save_label, callback_data="confirm|save")],
        [InlineKeyboardButton("✏️ Corectează", callback_data="confirm|edit")],
        [InlineKeyboardButton("❌ Anulează", callback_data="confirm|cancel")],
    ])

    if query is not None:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    else:
        await context.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=kb
        )


def _kb_edit_fields(idx: int, tip: str):
    """Butoane pentru campurile editabile ale unui document."""
    rows = []
    fields = _editable_fields(tip)
    for i in range(0, len(fields), 2):
        row = []
        for field_key, label, _ in fields[i:i + 2]:
            row.append(InlineKeyboardButton(
                label, callback_data=f"confirm|field|{idx}|{field_key}"
            ))
        rows.append(row)
    rows.append([InlineKeyboardButton("⬅️ Înapoi", callback_data="confirm|back")])
    return InlineKeyboardMarkup(rows)


def _kb_pick_item(items):
    """Butoane pentru a alege ce document se corecteaza (multi-item)."""
    rows = []
    for i, it in enumerate(items):
        tip_label = TIP_LABELS.get(it.get("tip", ""), "?")
        rows.append([InlineKeyboardButton(
            f"📄 Doc #{i + 1} — {tip_label}",
            callback_data=f"confirm|item|{i}"
        )])
    rows.append([InlineKeyboardButton("⬅️ Înapoi", callback_data="confirm|back")])
    return InlineKeyboardMarkup(rows)


def _kb_pick_tip(idx: int):
    """Butoane pentru a alege tipul documentului."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Venit", callback_data=f"confirm|tip|{idx}|VENIT")],
        [InlineKeyboardButton("🛒 Cheltuială", callback_data=f"confirm|tip|{idx}|CHELTUIALA")],
        [InlineKeyboardButton("📄 Factură comision", callback_data=f"confirm|tip|{idx}|FACTURA_COMISION")],
        [InlineKeyboardButton("⬅️ Înapoi", callback_data="confirm|back")],
    ])


# ============================================================
#                    HANDLER CALLBACK
# ============================================================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, parts: list):
    """
    Gestioneaza callback-urile 'confirm|*' EXCEPTAND 'confirm|save'
    (salvarea efectiva e in bot_contabil.execute_confirmed_save).
    """
    query = update.callback_query
    action = parts[1] if len(parts) > 1 else ""

    pending = get_pending(context)
    if not pending:
        await query.edit_message_text(
            "⏳ A trecut prea mult timp și confirmarea a expirat.\n"
            "Trimite-mi documentul din nou și o luăm de la capăt."
        )
        return

    items = pending["items"]

    # === Anuleaza ===
    if action == "cancel":
        clear_pending(context)
        await query.edit_message_text(
            "❌ Am anulat. N-am salvat nimic.\n"
            "Trimite-mi din nou poza sau textul când vrei.",
            parse_mode="Markdown",
        )
        return

    # === Inapoi la ecranul de confirmare ===
    if action == "back":
        context.user_data.pop(_EDIT_KEY, None)
        await show_confirmation(query.message.chat_id, context, query=query)
        return

    # === Meniu corectare ===
    if action == "edit":
        if len(items) == 1:
            tip = items[0].get("tip", "CHELTUIALA")
            await query.edit_message_text(
                "✏️ *Ce vrei să corectezi?*",
                parse_mode="Markdown",
                reply_markup=_kb_edit_fields(0, tip),
            )
        else:
            await query.edit_message_text(
                "✏️ *Ce document vrei să corectezi?*",
                parse_mode="Markdown",
                reply_markup=_kb_pick_item(items),
            )
        return

    # === Alege documentul (multi-item) ===
    if action == "item":
        idx = int(parts[2])
        if idx >= len(items):
            await show_confirmation(query.message.chat_id, context, query=query)
            return
        tip = items[idx].get("tip", "CHELTUIALA")
        await query.edit_message_text(
            f"✏️ *Corectează Document #{idx + 1}*\nAlege câmpul:",
            parse_mode="Markdown",
            reply_markup=_kb_edit_fields(idx, tip),
        )
        return

    # === Alege campul de corectat ===
    if action == "field":
        idx = int(parts[2])
        field = parts[3]
        if idx >= len(items):
            await show_confirmation(query.message.chat_id, context, query=query)
            return

        if field == "tip":
            await query.edit_message_text(
                f"🏷️ *Document #{idx + 1}* — alege tipul:",
                parse_mode="Markdown",
                reply_markup=_kb_pick_tip(idx),
            )
            return

        context.user_data[_EDIT_KEY] = {"item_index": idx, "field": field}
        prompts = {
            "data": "📅 Scrie data corectă (format ZZ.LL.AAAA):",
            "platforma": "🏢 Scrie numele corect al furnizorului/platformei:",
            "brut": "💵 Scrie suma corectă (ex: 300 sau 300.50):",
            "net": "💵 Scrie venitul net corect (ex: 1878.50):",
            "cash": "💵 Scrie suma cash corectă (ex: 1081):",
            "comision": "💵 Scrie baza comisionului corectă (ex: 245.50):",
            "detalii": "📝 Scrie descrierea corectă:",
        }
        await query.edit_message_text(
            prompts.get(field, "Scrie noua valoare:"),
            parse_mode="Markdown",
        )
        return

    # === Seteaza tipul (buton) ===
    if action == "tip":
        idx = int(parts[2])
        new_tip = parts[3]
        if idx < len(items) and new_tip in TIP_LABELS:
            items[idx]["tip"] = new_tip
        await show_confirmation(query.message.chat_id, context, query=query)
        return


# ============================================================
#                    EDITARE TEXT (wizard)
# ============================================================

async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Primeste valoarea noua pentru campul in curs de editare.
    Returneaza True daca a fost procesat.
    """
    edit = context.user_data.get(_EDIT_KEY)
    if not edit:
        return False

    pending = get_pending(context)
    if not pending:
        context.user_data.pop(_EDIT_KEY, None)
        return False

    idx = edit["item_index"]
    field = edit["field"]
    value = (update.message.text or "").strip()
    items = pending["items"]

    if idx >= len(items):
        context.user_data.pop(_EDIT_KEY, None)
        await update.message.reply_text("⚠️ Nu mai găsesc documentul ăsta.")
        return True

    item = items[idx]

    # --- Campuri numerice: valideaza prin ExtractionItem ---
    if field in ("brut", "net", "cash", "comision"):
        test = dict(item)
        test[field] = value
        try:
            validated = ExtractionItem(**test)
        except Exception:
            await update.message.reply_text(
                "⚠️ Aia nu pare un număr. Scrie doar suma.\n"
                "De exemplu: `300`, `300.50`, `1.250,50`",
                parse_mode="Markdown",
            )
            return True
        item[field] = getattr(validated, field)
        if item.get("tip") == "FACTURA_COMISION" and field == "comision":
            # Cotă TVA pe data facturii (19%/21%); fallback la azi dacă lipsește.
            item["tva"] = round(item["comision"] * cota_tva(_data_item(item)), 2)
            item["brut"] = item["comision"]
        if item.get("tip") == "CHELTUIALA" and field == "brut":
            item["net"] = item["brut"]

    # --- Data: valideaza format ---
    elif field == "data":
        test = dict(item)
        test["data"] = value
        try:
            validated = ExtractionItem(**test)
        except Exception:
            validated = None
        if validated is None or validated.data is None:
            await update.message.reply_text(
                "⚠️ Data nu pare în regulă. Scrie-o așa: `ZZ.LL.AAAA`\n"
                "De exemplu: `05.02.2026`",
                parse_mode="Markdown",
            )
            return True
        item["data"] = validated.data

    # --- Text simplu (furnizor, descriere) ---
    else:
        item[field] = value[:200]

    context.user_data.pop(_EDIT_KEY, None)
    await update.message.reply_text("✅ Actualizat.")
    await show_confirmation(update.effective_chat.id, context)
    return True
