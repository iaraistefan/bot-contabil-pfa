"""
Flask HTTP API pentru Bot Contabil PFA.

AUTH (Bug #6 fix):
- Endpoint-urile API care întorc date specifice user-ului folosesc Telegram
  WebApp init_data pentru identificare.
- Validare HMAC cu bot token (Telegram standard) — niciun spoofing posibil.
- Fallback DEV_USER_ID din env pentru testare în browser direct (numai dev/owner).
"""

import os as _os
import hmac
import hashlib
import logging
from datetime import datetime
from threading import Thread
from typing import Optional
from urllib.parse import parse_qsl

from flask import Flask, jsonify, render_template, Response, request

from config import settings
from db import get_session
from app.repositories import transactions as tx_repo
from app.repositories import users as users_repo
from app.services import tax_engine
from app.integrations.exports import csv_export
from app.integrations.exports.registru import (
    generate_registru_xlsx, filename_registru
)

logger = logging.getLogger(__name__)

flask_app = Flask(
    "bot_contabil_api",
    template_folder=_os.path.join(_os.path.dirname(__file__), "templates"),
    static_folder=_os.path.join(_os.path.dirname(__file__), "static"),
)

if settings.env == "production":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# ============================================================
#                    AUTH HELPERS
# ============================================================

def _validate_telegram_init_data(init_data: str, bot_token: str) -> Optional[dict]:
    """
    Valideaza semnatura HMAC a Telegram WebApp init_data.

    IMPORTANT (fix HMAC mismatch):
    - NU folosim parse_qsl, pentru ca acela aplica unquote_plus si transforma
      orice '+' in spatiu, stricand data_check_string (campuri base64 ca
      query_id pot contine '+'). Spargem manual si folosim unquote.
    - Excludem 'hash' SI 'signature' din data_check_string (conform spec).
    """
    if not init_data or not bot_token:
        logger.warning(
            f"init_data validate: init_data_present={bool(init_data)}, "
            f"bot_token_present={bool(bot_token)}"
        )
        return None

    try:
        from urllib.parse import unquote

        received_hash = None
        pairs = []
        for chunk in init_data.split("&"):
            if not chunk:
                continue
            key, _, value = chunk.partition("=")
            if key == "hash":
                received_hash = value
                continue
            if key == "signature":
                # Exclus din data_check_string pentru validarea cu hash.
                continue
            # unquote (NU unquote_plus) - pastreaza '+' asa cum e
            pairs.append((key, unquote(value)))

        if not received_hash:
            logger.warning("init_data: campul 'hash' lipseste")
            return None

        pairs.sort(key=lambda kv: kv[0])
        data_check_string = "\n".join(f"{k}={v}" for k, v in pairs)

        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()
        expected_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected_hash, received_hash):
            logger.warning(
                f"init_data hash mismatch. Campuri folosite: "
                f"{[k for k, _ in pairs]}. Verifica TELEGRAM_TOKEN."
            )
            return None

        # Reconstruim dict + parse user JSON
        parsed = {k: v for k, v in pairs}
        import json
        user_json = parsed.get("user")
        if user_json:
            try:
                parsed["user_obj"] = json.loads(user_json)
            except json.JSONDecodeError:
                pass

        return parsed

    except Exception as e:
        logger.error(f"init_data validation error: {e}")
        return None


def _resolve_user_id() -> Optional[int]:
    """
    Rezolvă user_id-ul DB-intern din request curent.

    Strategia:
    1. Verifică header X-Telegram-Init-Data (set de WebApp frontend)
       → validează HMAC → caută user în DB după telegram_id
    2. Fallback: env var DEV_USER_ID (pentru debug owner-only)

    Returnează None dacă nu poate identifica user-ul.
    """
    # Strategy 1: Telegram WebApp init_data
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    logger.info(
        f"_resolve_user_id: init_data header present={bool(init_data)}, "
        f"len={len(init_data)}"
    )
    if init_data:
        validated = _validate_telegram_init_data(init_data, settings.telegram_token)
        if validated:
            user_obj = validated.get("user_obj") or {}
            telegram_id = user_obj.get("id")
            if telegram_id:
                session = get_session()
                try:
                    user = users_repo.get_by_telegram_id(
                        session, telegram_id=int(telegram_id)
                    )
                    if user:
                        logger.info(
                            f"_resolve_user_id: OK, telegram_id={telegram_id} "
                            f"-> user_id={user.id}"
                        )
                        return user.id
                    logger.warning(
                        f"_resolve_user_id: telegram_id={telegram_id} "
                        f"validat dar NU exista in DB"
                    )
                except Exception as e:
                    logger.error(f"_resolve_user_id DB error: {e}")
                finally:
                    session.close()

    # Strategy 2: DEV fallback (env var) — DOAR in development.
    # SECURITATE (fix Bug izolare dashboard): in productie aceasta cale
    # este COMPLET dezactivata. Altfel DEV_USER_ID ar functiona ca o
    # cheie universala — orice request fara init_data valid ar primi
    # datele acelui user, expunand datele unui cont tuturor.
    if settings.env != "production":
        dev_user_id = _os.environ.get("DEV_USER_ID")
        if dev_user_id:
            try:
                logger.warning(
                    f"_resolve_user_id: folosesc fallback DEV_USER_ID="
                    f"{dev_user_id} (permis DOAR in env={settings.env})"
                )
                return int(dev_user_id)
            except ValueError:
                pass

    return None


def _require_user():
    """
    Returnează (user_id, error_response).
    Dacă user_id e None → error_response e setat și apelantul trebuie să-l returneze.
    """
    user_id = _resolve_user_id()
    if user_id is None:
        return None, (jsonify({
            "error": "unauthorized",
            "message": (
                "Acces din browser interzis. Deschide Dashboard-ul prin "
                "butonul din botul de Telegram."
            ),
        }), 401)
    return user_id, None


# ============================================================
#                    HEALTH & STATUS
# ============================================================

@flask_app.route("/")
@flask_app.route("/healthz")
def healthz():
    return jsonify({
        "status": "ok",
        "service": "bot-contabil-pfa",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@flask_app.route("/metrics")
def metrics():
    """Metrice publice agregate (fără date specifice unui user)."""
    session = get_session()
    try:
        from app.models import Document, Transaction, SourceFile, User
        return jsonify({
            "status": "ok",
            "users": session.query(User).count(),
            "documents": session.query(Document).count(),
            "transactions": session.query(Transaction).count(),
            "source_files": session.query(SourceFile).count(),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# ============================================================
#                    DEBUG — whoami (temporar)
# ============================================================

@flask_app.route("/api/v1/whoami")
def whoami():
    """
    Diagnostic temporar: arata DE CE validarea init_data reuseste sau esueaza.
    Nu expune secrete (doar lungimi si flag-uri). De sters dupa ce dashboard-ul
    functioneaza.
    """
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    out = {
        "init_data_present": bool(init_data),
        "init_data_len": len(init_data),
        "token_present": bool(settings.telegram_token),
        "token_len": len(settings.telegram_token or ""),
    }
    if not init_data:
        out["verdict"] = "NU ajunge init_data la server"
        return jsonify(out)

    from urllib.parse import parse_qsl
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        out["fields"] = sorted(list(parsed.keys()))
        out["has_hash"] = "hash" in parsed
        out["has_signature"] = "signature" in parsed
    except Exception as e:
        out["parse_error"] = str(e)[:120]

    validated = _validate_telegram_init_data(init_data, settings.telegram_token)
    out["hmac_valid"] = validated is not None

    if validated:
        user_obj = validated.get("user_obj") or {}
        tid = user_obj.get("id")
        out["telegram_id"] = tid
        session = get_session()
        try:
            user = None
            if tid:
                user = users_repo.get_by_telegram_id(session, telegram_id=int(tid))
            out["user_found_in_db"] = user is not None
            out["db_user_id"] = user.id if user else None
            out["verdict"] = (
                "OK - ar trebui sa mearga" if user
                else "HMAC valid DAR user negasit in DB"
            )
        finally:
            session.close()
    else:
        out["verdict"] = "HMAC INVALID - semnatura nu se potriveste"

    return jsonify(out)


# ============================================================
#                    DASHBOARD
# ============================================================

@flask_app.route("/dashboard")
def dashboard():
    """Dashboard HTML — autentificarea se face în frontend prin Telegram WebApp."""
    return render_template("dashboard.html")


# ============================================================
#                    API v1 — Date specifice user
# ============================================================

@flask_app.route("/api/v1/period/<int:year>/<int:month>")
def period_totals(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        return jsonify(totals)
    except Exception as e:
        logger.error(f"API period error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/transactions/<int:year>/<int:month>")
def transactions_list(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        txs = tx_repo.list_for_period(
            session, user_id=user_id, year=year, month=month
        )
        data = [{
            "id": tx.id,
            "tx_type": tx.tx_type,
            "category": tx.category,
            "amount_brut": tx.amount_brut,
            "amount_vat": tx.amount_vat,
            "amount_net": tx.amount_net,
            "currency": tx.currency,
            "deductibility_pct": tx.deductibility_pct,
            "payment_method": tx.payment_method,
            "counterparty": tx.counterparty,
            "vat_treatment": tx.vat_treatment,
            "occurred_on": tx.occurred_on.isoformat() if tx.occurred_on else None,
            "period_year": tx.period_year,
            "period_month": tx.period_month,
            "document_id": tx.document_id,
        } for tx in txs]
        return jsonify({
            "year": year, "month": month,
            "count": len(data), "transactions": data,
        })
    except Exception as e:
        logger.error(f"API transactions error {year}/{month} user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/documents")
def documents_recent():
    user_id, err = _require_user()
    if err:
        return err

    session = get_session()
    try:
        from app.models import Document
        docs = (
            session.query(Document)
            .filter(Document.user_id == user_id)
            .order_by(Document.id.desc())
            .limit(20)
            .all()
        )
        data = [{
            "id": doc.id,
            "data_doc": doc.data_doc,
            "platforma": doc.platforma,
            "tip": doc.tip,
            "brut": doc.brut,
            "tva": doc.tva,
            "net": doc.net,
            "status": doc.status,
            "detalii": doc.detalii,
            "prompt_version": doc.prompt_version,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        } for doc in docs]
        return jsonify({"count": len(data), "documents": data})
    except Exception as e:
        logger.error(f"API documents error user={user_id}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


# ============================================================
#                    API v1 — Export CSV
# ============================================================

@flask_app.route("/api/v1/transactions/export/<int:year>/<int:month>")
def export_transactions_csv(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        txs = tx_repo.list_for_period(
            session, user_id=user_id, year=year, month=month
        )
        csv_bytes = csv_export.generate_transactions_csv(txs, year, month)
        fname = csv_export.filename_transactions(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"CSV export error {year}/{month} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


@flask_app.route("/api/v1/period/export/<int:year>/<int:month>")
def export_period_csv(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        totals = tax_engine.compute_period(
            session, user_id=user_id, year=year, month=month
        )
        csv_bytes = csv_export.generate_rezumat_csv(totals)
        fname = csv_export.filename_rezumat(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"Period CSV export error {year}/{month} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


# ============================================================
#                    API v1 — Registru Încasări și Plăți
# ============================================================

@flask_app.route("/api/v1/registru/export/<int:year>")
def export_registru(year: int):
    """Generează Registrul de Încasări și Plăți pentru un an întreg."""
    if not 2020 <= year <= 2099:
        return "Invalid year", 400

    user_id, err = _require_user()
    if err:
        return "Unauthorized", 401

    session = get_session()
    try:
        # Folosim numele firmei din profilul user-ului
        profile = users_repo.get_profile_dict(session, user_id) or {}
        pfa_name = profile.get("firma_nume") or "PFA"
        pfa_cui = profile.get("firma_cui") or ""

        from app.models import Transaction
        txs = (
            session.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.period_year == year,
                Transaction.locked == False,
            )
            .order_by(Transaction.occurred_on)
            .all()
        )
        xlsx_bytes = generate_registru_xlsx(
            txs, year, pfa_name=pfa_name, pfa_cui=pfa_cui,
        )
        fname = filename_registru(year)
        return Response(
            xlsx_bytes,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"Registru export error {year} user={user_id}: {e}")
        return "Export error", 500
    finally:
        session.close()


# ============================================================
#                    Runner
# ============================================================

def run_flask():
    flask_app.run(
        host="0.0.0.0",
        port=settings.port,
        debug=False,
        use_reloader=False,
    )


def start_http_server():
    t = Thread(target=run_flask, daemon=True, name="flask-api")
    t.start()
    logger.info(f"✅ HTTP API started on port {settings.port}")
