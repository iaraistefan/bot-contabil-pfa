"""
Flask HTTP API pentru Bot Contabil PFA.
"""

import csv
import io
import logging
from datetime import datetime
from threading import Thread

from flask import Flask, jsonify, render_template, Response

from config import settings
from db import get_session
from app.repositories import transactions as tx_repo
from app.services import tax_engine
from app.integrations.exports import csv_export

logger = logging.getLogger(__name__)

flask_app = Flask(
    "bot_contabil_api",
    template_folder="templates",
)

if settings.env == "production":
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


# --- Health & status ---

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


# --- Dashboard ---

@flask_app.route("/dashboard")
def dashboard():
    """Servește dashboard-ul web."""
    return render_template("dashboard.html")


# --- API v1 — Date ---

@flask_app.route("/api/v1/period/<int:year>/<int:month>")
def period_totals(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400
    session = get_session()
    try:
        totals = tax_engine.compute_period(session, user_id=1, year=year, month=month)
        return jsonify(totals)
    except Exception as e:
        logger.error(f"API period error {year}/{month}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/transactions/<int:year>/<int:month>")
def transactions_list(year: int, month: int):
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400
    session = get_session()
    try:
        txs = tx_repo.list_for_period(session, user_id=1, year=year, month=month)
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
        return jsonify({"year": year, "month": month, "count": len(data), "transactions": data})
    except Exception as e:
        logger.error(f"API transactions error {year}/{month}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/documents")
def documents_recent():
    session = get_session()
    try:
        from app.models import Document
        docs = (
            session.query(Document)
            .filter(Document.user_id == 1)
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
        logger.error(f"API documents error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


# --- API v1 — Export CSV direct din browser ---

@flask_app.route("/api/v1/transactions/export/<int:year>/<int:month>")
def export_transactions_csv(year: int, month: int):
    """Descarcă CSV cu tranzacțiile perioadei direct din browser."""
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400
    session = get_session()
    try:
        txs = tx_repo.list_for_period(session, user_id=1, year=year, month=month)
        csv_bytes = csv_export.generate_transactions_csv(txs, year, month)
        fname = csv_export.filename_transactions(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"CSV export error {year}/{month}: {e}")
        return "Export error", 500
    finally:
        session.close()


@flask_app.route("/api/v1/period/export/<int:year>/<int:month>")
def export_period_csv(year: int, month: int):
    """Descarcă CSV cu rezumatul fiscal al perioadei."""
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return "Invalid period", 400
    session = get_session()
    try:
        totals = tax_engine.compute_period(session, user_id=1, year=year, month=month)
        csv_bytes = csv_export.generate_rezumat_csv(totals)
        fname = csv_export.filename_rezumat(year, month)
        return Response(
            csv_bytes,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={fname}"},
        )
    except Exception as e:
        logger.error(f"Period CSV export error {year}/{month}: {e}")
        return "Export error", 500
    finally:
        session.close()


# --- Runner ---

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
