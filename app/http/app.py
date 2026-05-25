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
    Validează semnătura HMAC a Telegram WebApp init_data.

    Conform documentației oficiale:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app

    Returnează dict cu fields parsate dacă semnătura e validă, altfel None.
    """
    if not init_data or not bot_token:
        return None

    try:
        # 1. Parse init_data (URL-encoded query string)
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        # 2. Extrage hash-ul transmis de client
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        # 3. Construim data_check_string conform specificației Telegram
        # (sortat alphabetic, fără hash, separate cu \n)
        data_check_arr = [f"{k}={v}" for k, v in sorted(parsed.items())]
        data_check_string = "\n".join(data_check_arr)

        # 4. Calculăm secret key = HMAC-SHA256("WebAppData", bot_token)
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
        ).digest()

        # 5. Calculăm hash-ul așteptat = HMAC-SHA256(secret_key, data_check_string)
        expected_hash = hmac.new(
            secret_key, data_check_string.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # 6. Comparăm constant-time
        if not hmac.compare_digest(expected_hash, received_hash):
            logger.warning("Telegram init_data hash mismatch — possible spoofing")
            return None

        # 7. Parse user JSON dacă există
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
                        return user.id
                    logger.warning(
                        f"Telegram WebApp user {telegram_id} not in DB"
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
