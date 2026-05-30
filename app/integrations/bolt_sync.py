"""
app/integrations/bolt_sync.py
=============================
Integrare Bolt Fleet API → venituri lunare in Registru.

PASUL 1 (on-demand, cu confirmare):
  Comanda /bolt <luna> trage cursele din API, agrega venitul lunii si,
  dupa confirmarea userului, creeaza UN document VENIT (Bolt) care trece
  prin acelasi posting.post_document ca un screenshot manual.

  Mapare (validata cu factura + statementul oficial Bolt):
    brut     = Σ ride_price (toate)          -> venit brut
    cash     = Σ ride_price pe curse cash     -> income cash
    comision = Σ commission                   -> cheltuiala deductibila 100%
  D301 NU se atinge — vine din factura Bolt fotografiata (alt flux).

Credentiale din variabile de mediu (Render):
    BOLT_CLIENT_ID, BOLT_CLIENT_SECRET
    (optional BOLT_API_BASE — default node.bolt.eu/fleet-integration-gateway)

Inregistrare in bot (in fisierul principal, dupa ce ai app_bot):
    from app.integrations import bolt_sync
    bolt_sync.register(app_bot)
"""

import os
import time
import calendar
import logging
from datetime import datetime, timezone

import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler, ApplicationHandlerStop,
)

from db import get_session
from app.models import Document, Transaction
from app.repositories import users as users_repo
from app.repositories import transactions as tx_repo
from app.services import posting

logger = logging.getLogger("bolt_sync")

BOLT_TOKEN_URL = "https://oidc.bolt.eu/token"
BOLT_SCOPE = "fleet-integration:api"
BOLT_API_BASE = os.getenv("BOLT_API_BASE", "https://node.bolt.eu/fleet-integration-gateway")
CHUNK = 14 * 24 * 3600  # bucati de 14 zile (limita interval Bolt)

LUNI_LONG = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}


# ============================================================
#                    CLIENT BOLT
# ============================================================

class BoltClient:
    def __init__(self, timeout=30):
        self.client_id = (os.getenv("BOLT_CLIENT_ID") or "").strip()
        self.client_secret = (os.getenv("BOLT_CLIENT_SECRET") or "").strip()
        self.timeout = timeout
        self._token = None
        self._token_exp = 0

    def available(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _get_token(self):
        if self._token and time.time() < self._token_exp:
            return self._token
        resp = requests.post(
            BOLT_TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": BOLT_SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = time.time() + int(data.get("expires_in", 600)) - 30
        return self._token

    def _post(self, path, body):
        url = f"{BOLT_API_BASE.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._get_token()}",
                   "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        if resp.status_code == 401:
            self._token = None
            headers["Authorization"] = f"Bearer {self._get_token()}"
            resp = requests.post(url, headers=headers, json=body, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _get(self, path):
        url = f"{BOLT_API_BASE.rstrip('/')}/{path.lstrip('/')}"
        headers = {"Authorization": f"Bearer {self._get_token()}"}
        resp = requests.get(url, headers=headers, timeout=self.timeout)
        if resp.status_code == 401:
            self._token = None
            headers["Authorization"] = f"Bearer {self._get_token()}"
            resp = requests.get(url, headers=headers, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def get_company_ids(self):
        data = self._get("/fleetIntegration/v1/getCompanies").get("data", {})
        return data.get("company_ids", [])

    def get_fleet_orders(self, company_ids, start_ts, end_ts, offset=0, limit=100):
        return self._post("/fleetIntegration/v1/getFleetOrders", {
            "offset": offset, "limit": limit, "company_ids": company_ids,
            "start_ts": int(start_ts), "end_ts": int(end_ts),
        })


# ============================================================
#                    AGREGARE LUNARA
# ============================================================

def _extract_orders(data):
    for v in (data or {}).values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "order_reference" in v[0]:
            return v
    return []


def _num(x):
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _fetch_range(client, company_ids, start_ts, end_ts):
    seen, a = {}, int(start_ts)
    end_ts = int(end_ts)
    while a < end_ts:
        b = min(a + CHUNK, end_ts)
        offset, limit = 0, 100
        while True:
            res = client.get_fleet_orders(company_ids, a, b, offset, limit)
            if res.get("code") != 0:
                raise RuntimeError(f"Bolt code={res.get('code')}: {res.get('message')}")
            page = _extract_orders(res.get("data", {}))
            for o in page:
                seen[o.get("order_reference")] = o
            if len(page) < limit:
                break
            offset += limit
            if offset > 20000:
                break
        a = b
    return list(seen.values())


def get_month_summary(year: int, month: int) -> dict:
    """Agrega venitul lunii din API. Returneaza dict cu cifrele necesare postarii."""
    client = BoltClient()
    if not client.available():
        raise RuntimeError("Lipsesc BOLT_CLIENT_ID / BOLT_CLIENT_SECRET pe server.")

    company_ids = client.get_company_ids()
    last_day = calendar.monthrange(year, month)[1]
    m_start = int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp())
    m_end = int(datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).timestamp())
    q_start = m_start - 2 * 24 * 3600
    q_end = min(m_end + 2 * 24 * 3600, int(time.time()))

    orders = _fetch_range(client, company_ids, q_start, q_end)

    def fin_ts(o):
        return o.get("order_finished_timestamp") or o.get("order_drop_off_timestamp") or 0

    fin = [o for o in orders if o.get("order_status") == "finished"
           and m_start <= _num(fin_ts(o)) <= m_end]

    brut = cash = comision = net = tip = cash_discount = 0.0
    for o in fin:
        p = o.get("order_price", {}) or {}
        rp = _num(p.get("ride_price"))
        brut += rp
        comision += _num(p.get("commission"))
        net += _num(p.get("net_earnings"))
        tip += _num(p.get("tip"))
        if o.get("payment_method") == "cash":
            cash += rp
            cash_discount += _num(p.get("cash_discount"))

    R = lambda x: round(x, 2)
    return {
        "year": year, "month": month, "n": len(fin),
        "brut": R(brut), "cash": R(cash), "card": R(brut - cash),
        "comision": R(comision), "net": R(net), "tip": R(tip),
        "cash_in_hand": R(cash - cash_discount),
        "last_day": last_day,
    }


# ============================================================
#              POSTARE IN REGISTRU (refoloseste posting)
# ============================================================

def _remove_existing_bolt_income(session, user_id, year, month):
    """Sterge un eventual document VENIT Bolt deja postat pentru luna (idempotent)."""
    data_suffix = f".{month:02d}.{year}"
    docs = (
        session.query(Document)
        .filter(
            Document.user_id == user_id,
            Document.tip == "VENIT",
            Document.platforma == "Bolt",
            Document.status != "rejected",
            Document.data_doc.like(f"%{data_suffix}"),
        )
        .all()
    )
    removed = 0
    for d in docs:
        tx_repo.delete_for_document(session, document_id=d.id)
        d.status = "rejected"
        removed += 1
    if removed:
        session.flush()
    return removed


def post_month(user_id: int, summary: dict) -> dict:
    """Creeaza documentul VENIT Bolt si tranzactiile, prin posting.post_document."""
    year, month = summary["year"], summary["month"]
    data_doc = f"{summary['last_day']:02d}.{month:02d}.{year}"

    session = get_session()
    try:
        replaced = _remove_existing_bolt_income(session, user_id, year, month)

        doc = Document(
            user_id=user_id, source_file_id=None,
            data_doc=data_doc, platforma="Bolt", tip="VENIT",
            brut=summary["brut"], comision=summary["comision"], tva=0.0,
            net=summary["net"], cash=summary["cash"],
            banca=round(summary["brut"] - summary["cash"], 2),
            detalii=f"Venituri Bolt {LUNI_LONG[month]} {year} (API, {summary['n']} curse)",
            raw_json="", prompt_version="bolt_api_v1",
            status="posted", confidence=1.0,
        )
        session.add(doc)
        session.flush()

        tx_ids = posting.post_document(
            session, user_id=user_id, document_id=doc.id,
            tip="VENIT", platforma="Bolt",
            detalii=doc.detalii,
            brut=summary["brut"], comision=summary["comision"], tva=0.0,
            net=summary["net"], cash=summary["cash"],
            banca=doc.banca, data_doc=data_doc,
        )
        session.commit()
        return {"doc_id": doc.id, "tx_count": len(tx_ids), "replaced": replaced}
    except Exception as e:
        session.rollback()
        logger.error(f"post_month error: {e}")
        raise
    finally:
        session.close()


# ============================================================
#                    HANDLERS TELEGRAM
# ============================================================

def _resolve_user_id(tg_id):
    session = get_session()
    try:
        u = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        return u.id if u else None
    finally:
        session.close()


def _parse_args(args):
    """/bolt -> luna trecuta; /bolt 4 -> luna 4 anul curent; /bolt 2026 4."""
    now = datetime.now()
    if len(args) >= 2:
        return int(args[0]), int(args[1])
    if len(args) == 1:
        return now.year, int(args[0])
    # default: luna trecuta
    y, m = now.year, now.month - 1
    if m == 0:
        m, y = 12, y - 1
    return y, m


async def handle_bolt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    user_id = _resolve_user_id(tg_id)
    if not user_id:
        await update.message.reply_text("⚠️ Foloseste mai intai /start.")
        return
    try:
        year, month = _parse_args(context.args or [])
    except (ValueError, IndexError):
        await update.message.reply_text("Foloseste: `/bolt 2026 4` sau `/bolt 4`.", parse_mode="Markdown")
        return

    await update.message.reply_text(f"🔄 Trag veniturile Bolt pentru {LUNI_LONG.get(month, month)} {year}...")

    try:
        s = get_month_summary(year, month)
    except Exception as e:
        await update.message.reply_text(f"❌ Eroare Bolt: {str(e)[:300]}")
        return

    if s["n"] == 0:
        await update.message.reply_text(
            f"📭 Nicio cursa finalizata in {LUNI_LONG[month]} {year} "
            f"(sau luna nu mai e disponibila in API)."
        )
        return

    context.user_data["bolt_pending"] = s

    msg = (
        f"🚗 *Venituri Bolt — {LUNI_LONG[month]} {year}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Curse finalizate: *{s['n']}*\n\n"
        f"💰 *Venit brut (Σ tarif): {s['brut']:.2f} lei*\n"
        f"   💵 cash: {s['cash']:.2f}  (în mână ≈ {s['cash_in_hand']:.2f})\n"
        f"   💳 card/app: {s['card']:.2f}\n"
        f"➖ Comision Bolt (cheltuială 100%): {s['comision']:.2f}\n"
        f"= Net: {s['net']:.2f} lei\n"
        f"ℹ️ bacșiș (info): {s['tip']:.2f}\n\n"
        f"_Compară cu ecranul „Defalcarea câștigurilor / Lunar" din Bolt._\n"
        f"_D301 rămâne din factura Bolt — nu se atinge aici._"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Adaugă în Registru", callback_data="boltsync|confirm")],
        [InlineKeyboardButton("❌ Anulează", callback_data="boltsync|cancel")],
    ])
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=kb)


async def handle_bolt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.split("|")[1]

    if action == "cancel":
        context.user_data.pop("bolt_pending", None)
        await query.edit_message_text("❌ Anulat. Nu am adăugat nimic.")
        raise ApplicationHandlerStop

    s = context.user_data.get("bolt_pending")
    if not s:
        await query.edit_message_text("⏳ Sesiune expirată. Rulează din nou `/bolt`.")
        raise ApplicationHandlerStop

    user_id = _resolve_user_id(query.from_user.id)
    try:
        res = post_month(user_id, s)
        repl = f"\n♻️ Am înlocuit înregistrarea Bolt anterioară a lunii." if res["replaced"] else ""
        await query.edit_message_text(
            f"✅ *Adăugat în Registru — {LUNI_LONG[s['month']]} {s['year']}*\n"
            f"Venit brut: {s['brut']:.2f} lei · Comision: {s['comision']:.2f} lei\n"
            f"({res['tx_count']} tranzacții, doc #{res['doc_id']}){repl}\n\n"
            f"Verifică din 📂 Registru sau 📊 Raport.",
            parse_mode="Markdown",
        )
    except Exception as e:
        await query.edit_message_text(f"❌ Eroare la salvare: {str(e)[:300]}")
    finally:
        context.user_data.pop("bolt_pending", None)
    raise ApplicationHandlerStop


def register(app_bot):
    """Inregistreaza comanda /bolt si callback-ul de confirmare."""
    app_bot.add_handler(CommandHandler("bolt", handle_bolt_command))
    app_bot.add_handler(
        CallbackQueryHandler(handle_bolt_callback, pattern=r"^boltsync\|"),
        group=-1,
    )
    logger.info("Bolt sync inregistrat (/bolt)")
