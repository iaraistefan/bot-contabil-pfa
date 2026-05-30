"""
app/integrations/bolt_sync.py
=============================
Integrare Bolt Fleet API -> venituri in Registru.

PAS 1 (on-demand): /bolt <luna> trage din API, agrega, si dupa confirmare
creeaza UN document VENIT (Bolt) prin acelasi posting.post_document.

PAS 2 (semiautomat):
  - tabel cache `bolt_orders` (migrarea 008) - istoric curse, dedup pe order_reference
  - job ZILNIC (23:30) - trage ultimele ~4 zile din API si face upsert in cache
    (overlap intentionat ca sa prinda cursele intarziate; nu pierdem istoric vechi)
  - job LUNAR (ziua 1, 09:00) - trimite automat cifrele lunii trecute cu buton
    "Adauga in Registru"; tu verifici si apesi (semiautomat).

Mapare (validata cu factura + statementul oficial Bolt):
  brut     = suma ride_price (toate)        -> venit brut
  cash     = suma ride_price pe curse cash   -> income cash
  comision = suma commission                 -> cheltuiala deductibila 100%
D301 NU se atinge - vine din factura Bolt fotografiata (alt flux).

Variabile de mediu (Render):
  BOLT_CLIENT_ID, BOLT_CLIENT_SECRET    - credentiale API (obligatorii)
  BOLT_OWNER_TELEGRAM_ID                - telegram id pentru joburile automate
  BOLT_API_BASE                         - optional, default node.bolt.eu/...

Inregistrare (in fisierul principal):
  from app.integrations import bolt_sync
  bolt_sync.register(app_bot)
"""

import os
import time
import calendar
import logging
from datetime import datetime, timezone

import requests
from sqlalchemy import text

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler, ApplicationHandlerStop,
)

from db import get_session
from app.models import Document
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
#                    HELPERS DATE / NUMERE
# ============================================================

def _num(x):
    try:
        return float(x) if x is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _R(x):
    return round(x, 2)


def _extract_orders(data):
    for v in (data or {}).values():
        if isinstance(v, list) and v and isinstance(v[0], dict) and "order_reference" in v[0]:
            return v
    return []


def _flat_from_api(o):
    """Normalizeaza o comanda din API intr-un dict plat (acelasi format ca in cache)."""
    p = o.get("order_price", {}) or {}
    fts = o.get("order_finished_timestamp") or o.get("order_drop_off_timestamp") or 0
    return {
        "order_reference": o.get("order_reference"),
        "order_status": o.get("order_status"),
        "payment_method": o.get("payment_method"),
        "ride_price": _num(p.get("ride_price")),
        "commission": _num(p.get("commission")),
        "net_earnings": _num(p.get("net_earnings")),
        "tip": _num(p.get("tip")),
        "cash_discount": _num(p.get("cash_discount")),
        "ride_distance": int(_num(o.get("ride_distance"))),  # metri, cu pasager
        "finished_ts": int(_num(fts)),
    }


def _period_from_ts(ts):
    if not ts:
        return (None, None)
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return d.year, d.month


def _fetch_range(client, company_ids, start_ts, end_ts):
    """Trage toate comenzile din interval, sparte in bucati de 14 zile, cu paginare."""
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


def _aggregate(rows):
    """Agrega o lista de dict-uri plate (din cache sau API). Numara doar 'finished'."""
    brut = cash = comision = net = tip = cash_discount = 0.0
    km_m = 0.0  # metri parcursi cu pasager (ride_distance), doar finished
    n = 0
    for r in rows:
        if r.get("order_status") != "finished":
            continue
        n += 1
        rp = _num(r.get("ride_price"))
        brut += rp
        comision += _num(r.get("commission"))
        net += _num(r.get("net_earnings"))
        tip += _num(r.get("tip"))
        km_m += _num(r.get("ride_distance"))
        if r.get("payment_method") == "cash":
            cash += rp
            cash_discount += _num(r.get("cash_discount"))
    return {
        "n": n,
        "brut": _R(brut), "cash": _R(cash), "card": _R(brut - cash),
        "comision": _R(comision), "net": _R(net), "tip": _R(tip),
        "cash_in_hand": _R(cash - cash_discount),
        "km": _R(km_m / 1000.0),  # km cu pasager (din ride_distance)
    }


# ============================================================
#                    CACHE bolt_orders (raw SQL)
# ============================================================

_UPSERT_SQL = text("""
    INSERT INTO bolt_orders (
        user_id, order_reference, order_status, payment_method,
        ride_price, commission, net_earnings, tip, cash_discount,
        ride_distance, finished_ts, period_year, period_month, updated_at
    ) VALUES (
        :uid, :ref, :status, :pm,
        :rp, :comm, :net, :tip, :cd,
        :rd, :fts, :py, :pmonth, CURRENT_TIMESTAMP
    )
    ON CONFLICT (user_id, order_reference) DO UPDATE SET
        order_status   = EXCLUDED.order_status,
        payment_method = EXCLUDED.payment_method,
        ride_price     = EXCLUDED.ride_price,
        commission     = EXCLUDED.commission,
        net_earnings   = EXCLUDED.net_earnings,
        tip            = EXCLUDED.tip,
        cash_discount  = EXCLUDED.cash_discount,
        ride_distance  = EXCLUDED.ride_distance,
        finished_ts    = EXCLUDED.finished_ts,
        period_year    = EXCLUDED.period_year,
        period_month   = EXCLUDED.period_month,
        updated_at     = CURRENT_TIMESTAMP
""")

_SELECT_PERIOD_SQL = text("""
    SELECT order_status, payment_method, ride_price, commission,
           net_earnings, tip, cash_discount, ride_distance
    FROM bolt_orders
    WHERE user_id = :uid AND period_year = :py AND period_month = :pmonth
""")

_DELETE_PERIOD_SQL = text("""
    DELETE FROM bolt_orders
    WHERE user_id = :uid AND period_year = :py AND period_month = :pmonth
""")


def _cache_clear_period(user_id, year, month):
    """Sterge cache-ul unei luni, ca urmatorul /bolt sa re-traga din API."""
    session = get_session()
    try:
        session.execute(_DELETE_PERIOD_SQL, {
            "uid": user_id, "py": year, "pmonth": month,
        })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"cache clear error: {e}")
    finally:
        session.close()


def _cache_upsert(session, user_id, flat):
    py, pmonth = _period_from_ts(flat.get("finished_ts"))
    session.execute(_UPSERT_SQL, {
        "uid": user_id,
        "ref": flat.get("order_reference"),
        "status": flat.get("order_status"),
        "pm": flat.get("payment_method"),
        "rp": flat.get("ride_price") or 0.0,
        "comm": flat.get("commission") or 0.0,
        "net": flat.get("net_earnings") or 0.0,
        "tip": flat.get("tip") or 0.0,
        "cd": flat.get("cash_discount") or 0.0,
        "rd": flat.get("ride_distance") or 0,
        "fts": flat.get("finished_ts") or None,
        "py": py, "pmonth": pmonth,
    })


def _cache_read_period(session, user_id, year, month):
    res = session.execute(_SELECT_PERIOD_SQL, {
        "uid": user_id, "py": year, "pmonth": month,
    })
    rows = []
    for r in res:
        rows.append({
            "order_status": r[0], "payment_method": r[1],
            "ride_price": r[2], "commission": r[3],
            "net_earnings": r[4], "tip": r[5], "cash_discount": r[6],
            "ride_distance": r[7],
        })
    return rows


# ============================================================
#                    AGREGARE LUNARA (cache-first)
# ============================================================

def get_month_summary(user_id: int, year: int, month: int) -> dict:
    """
    Cifrele lunii. Intai din cache (bolt_orders); daca lipseste, din API.
    Asa merge si pentru luni vechi pe care API-ul Bolt nu le mai tine,
    daca jobul zilnic le-a colectat la timp.
    """
    # 1) incearca din cache
    session = get_session()
    try:
        cached = _cache_read_period(session, user_id, year, month)
    except Exception as e:
        logger.error(f"cache read error: {e}")
        cached = []
    finally:
        session.close()

    finished_cached = [r for r in cached if r.get("order_status") == "finished"]
    if finished_cached:
        s = _aggregate(finished_cached)
        s.update({"year": year, "month": month,
                  "last_day": calendar.monthrange(year, month)[1],
                  "source": "cache"})
        return s

    # 2) fallback API
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
    flat = [_flat_from_api(o) for o in orders]

    # IMPORTANT: salvam in cache TOT ce am tras (nu doar finished, ca sa avem istoric
    # complet), ca a doua oara (ex. la apasarea butonului "Adauga in Registru")
    # sa citim din cache si sa NU mai lovim API-ul Bolt -> evitam 429 Too Many Requests.
    if flat:
        session = get_session()
        try:
            for f in flat:
                if f.get("finished_ts"):
                    _cache_upsert(session, user_id, f)
            session.commit()
            logger.info(f"get_month_summary: {len(flat)} comenzi salvate in cache "
                        f"(fallback API) pentru user {user_id} {year}-{month:02d}")
        except Exception as e:
            session.rollback()
            logger.error(f"cache write (fallback) error: {e}")
        finally:
            session.close()

    in_month = [
        f for f in flat
        if f["order_status"] == "finished" and m_start <= (f["finished_ts"] or 0) <= m_end
    ]
    s = _aggregate(in_month)
    s.update({"year": year, "month": month, "last_day": last_day, "source": "api"})
    return s


def collect_recent(user_id: int, days: int = 4) -> int:
    """Trage ultimele `days` zile din API si face upsert in cache. Returneaza nr comenzi."""
    client = BoltClient()
    if not client.available():
        return 0
    company_ids = client.get_company_ids()
    now = int(time.time())
    start = now - days * 24 * 3600
    orders = _fetch_range(client, company_ids, start, now)

    session = get_session()
    try:
        count = 0
        for o in orders:
            f = _flat_from_api(o)
            if not f.get("order_reference"):
                continue
            _cache_upsert(session, user_id, f)
            count += 1
        session.commit()
        logger.info(f"collect_recent: {count} comenzi upsert pentru user {user_id}")
        return count
    except Exception as e:
        session.rollback()
        logger.error(f"collect_recent error: {e}")
        return 0
    finally:
        session.close()


# ============================================================
#              POSTARE IN REGISTRU (refoloseste posting)
# ============================================================

def _remove_existing_bolt_income(session, user_id, year, month):
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
#                    TEXT MESAJ + HELPERS
# ============================================================

def _format_summary_text(s: dict, auto=False) -> str:
    head = "🚗 *Venituri Bolt (luna trecuta)*" if auto else "🚗 *Venituri Bolt*"
    return (
        f"{head} — {LUNI_LONG[s['month']]} {s['year']}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Curse finalizate: *{s['n']}*\n\n"
        f"💰 *Venit brut (tarif): {s['brut']:.2f} lei*\n"
        f"   💵 cash: {s['cash']:.2f}  (in mana aprox {s['cash_in_hand']:.2f})\n"
        f"   💳 card/app: {s['card']:.2f}\n"
        f"➖ Comision Bolt (cheltuiala 100%): {s['comision']:.2f}\n"
        f"= Net: {s['net']:.2f} lei\n"
        f"ℹ️ bacsis (info): {s['tip']:.2f}\n"
        f"📏 km cu pasageri: {s.get('km', 0):.1f} km  _(din curse)_\n\n"
        f"_Compara cu ecranul Bolt: Defalcarea castigurilor, Lunar._\n"
        f"_D301 ramane din factura Bolt, nu se atinge aici._"
    )


def _confirm_keyboard(year, month):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Adauga in Registru",
                              callback_data=f"boltsync|confirm|{year}|{month}")],
        [InlineKeyboardButton("❌ Anuleaza", callback_data="boltsync|cancel")],
    ])


def _resolve_user_id(tg_id):
    session = get_session()
    try:
        u = users_repo.get_by_telegram_id(session, telegram_id=tg_id)
        return u.id if u else None
    finally:
        session.close()


def _parse_args(args):
    now = datetime.now()
    if len(args) >= 2:
        return int(args[0]), int(args[1])
    if len(args) == 1:
        return now.year, int(args[0])
    y, m = now.year, now.month - 1
    if m == 0:
        m, y = 12, y - 1
    return y, m


# ============================================================
#                    HANDLERS TELEGRAM
# ============================================================

async def handle_bolt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    user_id = _resolve_user_id(tg_id)
    if not user_id:
        await update.message.reply_text("Foloseste mai intai /start.")
        return
    raw_args = context.args or []
    resync = any(a.lower() == "resync" for a in raw_args)
    clean_args = [a for a in raw_args if a.lower() != "resync"]
    try:
        year, month = _parse_args(clean_args)
    except (ValueError, IndexError):
        await update.message.reply_text("Foloseste: /bolt 2026 4 sau /bolt 4")
        return

    if resync:
        _cache_clear_period(user_id, year, month)
        await update.message.reply_text(
            f"♻️ Re-sincronizez {LUNI_LONG.get(month, month)} {year} din API "
            f"(golesc cache-ul lunii)..."
        )

    await update.message.reply_text(
        f"Trag veniturile Bolt pentru {LUNI_LONG.get(month, month)} {year}..."
    )
    try:
        s = get_month_summary(user_id, year, month)
    except Exception as e:
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg:
            await update.message.reply_text(
                "⏳ Bolt a limitat temporar cererile (prea multe într-un minut).\n"
                "Așteaptă ~1-2 minute și încearcă din nou."
            )
        else:
            await update.message.reply_text(f"Eroare Bolt: {msg[:300]}")
        return

    if s["n"] == 0:
        await update.message.reply_text(
            f"Nicio cursa finalizata in {LUNI_LONG[month]} {year} "
            f"(sau luna nu mai e disponibila in API)."
        )
        return

    await update.message.reply_text(
        _format_summary_text(s),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(year, month),
    )


async def handle_bolt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|")
    action = parts[1] if len(parts) > 1 else ""

    if action == "cancel":
        await query.edit_message_text("❌ Anulat. Nu am adaugat nimic.")
        raise ApplicationHandlerStop

    # confirm|YEAR|MONTH  (stateless: recomputam din cache/API)
    if len(parts) < 4:
        await query.edit_message_text("Sesiune invalida. Ruleaza din nou /bolt")
        raise ApplicationHandlerStop
    try:
        year, month = int(parts[2]), int(parts[3])
    except ValueError:
        await query.edit_message_text("Sesiune invalida. Ruleaza din nou /bolt")
        raise ApplicationHandlerStop

    user_id = _resolve_user_id(query.from_user.id)
    if not user_id:
        await query.edit_message_text("Foloseste mai intai /start.")
        raise ApplicationHandlerStop

    try:
        s = get_month_summary(user_id, year, month)
        if s["n"] == 0:
            await query.edit_message_text(
                f"Nu mai gasesc curse pentru {LUNI_LONG[month]} {year}."
            )
            raise ApplicationHandlerStop
        res = post_month(user_id, s)
        repl = "\n♻️ Am inlocuit inregistrarea Bolt anterioara a lunii." if res["replaced"] else ""
        await query.edit_message_text(
            f"✅ *Adaugat in Registru — {LUNI_LONG[month]} {year}*\n"
            f"Venit brut: {s['brut']:.2f} lei, Comision: {s['comision']:.2f} lei\n"
            f"({res['tx_count']} tranzactii, doc #{res['doc_id']}){repl}\n\n"
            f"Verifica din Registru sau Raport.",
            parse_mode="Markdown",
        )
    except ApplicationHandlerStop:
        raise
    except Exception as e:
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg:
            await query.edit_message_text(
                "⏳ Bolt a limitat temporar cererile (prea multe într-un minut).\n"
                "Așteaptă ~1-2 minute și apasă din nou /bolt {} {}, apoi butonul."
                .format(year, month)
            )
        else:
            await query.edit_message_text(f"Eroare la salvare: {msg[:300]}")
    raise ApplicationHandlerStop


# ============================================================
#                    JOBURI AUTOMATE (PAS 2)
# ============================================================

def _send_with_button(bot_token, chat_id, text_msg, year, month):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    kb = {
        "inline_keyboard": [
            [{"text": "✅ Adauga in Registru",
              "callback_data": f"boltsync|confirm|{year}|{month}"}],
            [{"text": "❌ Ignora", "callback_data": "boltsync|cancel"}],
        ]
    }
    try:
        resp = requests.post(url, json={
            "chat_id": chat_id, "text": text_msg,
            "parse_mode": "Markdown", "reply_markup": kb,
            "disable_web_page_preview": True,
        }, timeout=15)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"_send_with_button failed: {e}")
        return False


def run_bolt_daily_sync(bot_token: str):
    """Job zilnic: colecteaza ultimele zile in cache (single-tenant: owner)."""
    owner = os.getenv("BOLT_OWNER_TELEGRAM_ID")
    client = BoltClient()
    if not client.available() or not owner:
        return
    try:
        uid = _resolve_user_id(int(owner))
    except (ValueError, TypeError):
        uid = None
    if not uid:
        logger.info("bolt_daily_sync: owner user negasit")
        return
    n = collect_recent(uid, days=4)
    logger.info(f"bolt_daily_sync: {n} comenzi colectate")


def run_bolt_monthly_suggest(bot_token: str):
    """Job lunar (ziua 1): trimite cifrele lunii trecute cu buton de confirmare."""
    owner = os.getenv("BOLT_OWNER_TELEGRAM_ID")
    if not owner:
        return
    client = BoltClient()
    if not client.available():
        return
    try:
        owner_id = int(owner)
    except (ValueError, TypeError):
        return
    uid = _resolve_user_id(owner_id)
    if not uid:
        logger.info("bolt_monthly_suggest: owner user negasit")
        return

    now = datetime.now()
    y, m = now.year, now.month - 1
    if m == 0:
        m, y = 12, y - 1

    try:
        s = get_month_summary(uid, y, m)
    except Exception as e:
        logger.error(f"bolt_monthly_suggest summary error: {e}")
        return
    if s["n"] == 0:
        logger.info(f"bolt_monthly_suggest: 0 curse pentru {m}/{y}")
        return

    _send_with_button(bot_token, owner_id, _format_summary_text(s, auto=True), y, m)
    logger.info(f"bolt_monthly_suggest: sugestie trimisa pentru {m}/{y}")


_SCHED = None


def _start_bolt_scheduler(bot_token: str):
    """Porneste un mini-scheduler propriu pentru joburile Bolt (autonom)."""
    global _SCHED
    if _SCHED is not None:
        return
    if not BoltClient().available() or not os.getenv("BOLT_OWNER_TELEGRAM_ID"):
        logger.info("Bolt scheduler dezactivat (lipsesc credentialele sau owner id)")
        return
    try:
        import pytz
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        tz = pytz.timezone("Europe/Bucharest")
        sched = BackgroundScheduler(timezone=tz)
        sched.add_job(
            func=lambda: run_bolt_daily_sync(bot_token),
            trigger=CronTrigger(hour=23, minute=30, timezone=tz),
            id="bolt_daily_sync", replace_existing=True,
        )
        sched.add_job(
            func=lambda: run_bolt_monthly_suggest(bot_token),
            trigger=CronTrigger(day=1, hour=9, minute=0, timezone=tz),
            id="bolt_monthly_suggest", replace_existing=True,
        )
        sched.start()
        _SCHED = sched
        logger.info("Bolt scheduler pornit (zilnic 23:30 + lunar ziua 1, 09:00)")
    except Exception as e:
        logger.error(f"Nu am putut porni Bolt scheduler: {e}")


# ============================================================
#                    INREGISTRARE
# ============================================================

def register(app_bot):
    """Inregistreaza /bolt, callback-ul de confirmare si joburile automate."""
    app_bot.add_handler(CommandHandler("bolt", handle_bolt_command))
    app_bot.add_handler(
        CallbackQueryHandler(handle_bolt_callback, pattern=r"^boltsync\|"),
        group=-1,
    )
    try:
        token = app_bot.bot.token
    except Exception:
        token = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN") or ""
    if token:
        _start_bolt_scheduler(token)
    logger.info("Bolt sync inregistrat (/bolt + joburi automate)")
