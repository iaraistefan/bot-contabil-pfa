"""
Flask HTTP API pentru Bot Contabil PFA.

Rulează în thread separat, în paralel cu bot-ul Telegram.
Scopuri:
  1. Health check pentru Render (keep-alive + monitoring).
  2. API read-only pentru viitoare UI web sau integrări externe.
  3. Endpoint de metrici sumar (fără date sensibile).

PORT: setat prin env var PORT (Render îl setează automat).
Toate endpoint-urile /api/v1/* returnează JSON.
Endpoint-urile de date sunt read-only — nu acceptă POST/PUT/DELETE.
"""

import logging
from datetime import datetime
from threading import Thread

from flask import Flask, jsonify

from config import settings
from db import get_session
from app.repositories import transactions as tx_repo
from app.services import tax_engine

logger = logging.getLogger(__name__)

flask_app = Flask("bot_contabil_api")

# Dezactivăm log-urile verbose Flask în producție
if settings.env == "production":
    log = logging.getLogger("werkzeug")
    log.setLevel(logging.WARNING)


# --- Health & status ---

@flask_app.route("/")
@flask_app.route("/healthz")
def healthz():
    """
    Health check pentru Render.
    Render bate acest endpoint la fiecare ~30 secunde.
    Răspuns rapid — nu atinge DB.
    """
    return jsonify({
        "status": "ok",
        "service": "bot-contabil-pfa",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })


@flask_app.route("/metrics")
def metrics():
    """
    Metrici sumare — fără date financiare, doar conturi.
    Util pentru monitoring rapid fără a intra în pgAdmin.
    """
    session = get_session()
    try:
        from app.models import Document, Transaction, SourceFile, User
        user_count = session.query(User).count()
        doc_count = session.query(Document).count()
        tx_count = session.query(Transaction).count()
        sf_count = session.query(SourceFile).count()

        return jsonify({
            "status": "ok",
            "users": user_count,
            "documents": doc_count,
            "transactions": tx_count,
            "source_files": sf_count,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })
    except Exception as e:
        logger.error(f"Metrics error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        session.close()


# --- API v1 ---

@flask_app.route("/api/v1/period/<int:year>/<int:month>")
def period_totals(year: int, month: int):
    """
    Totalurile fiscale pentru o perioadă.

    GET /api/v1/period/2026/4
    → returnează același dict ca tax_engine.compute_period()
    → user_id hardcodat la 1 (single-user pentru acum)

    Când adăugăm autentificare, user_id vine din JWT/session.
    """
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    session = get_session()
    try:
        # Single-user: user_id=1. La multi-user, vine din auth header.
        totals = tax_engine.compute_period(
            session, user_id=1, year=year, month=month,
        )
        return jsonify(totals)
    except Exception as e:
        logger.error(f"API period error {year}/{month}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/transactions/<int:year>/<int:month>")
def transactions_list(year: int, month: int):
    """
    Lista tranzacțiilor pentru o perioadă.

    GET /api/v1/transactions/2026/4
    → returnează lista de tranzacții ca JSON
    """
    if not (1 <= month <= 12 and 2020 <= year <= 2099):
        return jsonify({"error": "invalid period"}), 400

    session = get_session()
    try:
        txs = tx_repo.list_for_period(session, user_id=1, year=year, month=month)
        data = []
        for tx in txs:
            data.append({
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
            })
        return jsonify({
            "year": year,
            "month": month,
            "count": len(data),
            "transactions": data,
        })
    except Exception as e:
        logger.error(f"API transactions error {year}/{month}: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


@flask_app.route("/api/v1/documents")
def documents_recent():
    """
    Ultimele 20 documente.

    GET /api/v1/documents
    → returnează lista de documente recente
    """
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
        data = []
        for doc in docs:
            data.append({
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
            })
        return jsonify({"count": len(data), "documents": data})
    except Exception as e:
        logger.error(f"API documents error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        session.close()


# --- Runner ---

def run_flask():
    """Pornește Flask în thread separat."""
    flask_app.run(
        host="0.0.0.0",
        port=settings.port,
        debug=False,
        use_reloader=False,   # CRITIC: reloader-ul Flask crează procese noi → conflict cu bot
    )


def start_http_server():
    """Lansează Flask în background thread. Apelat din main."""
    t = Thread(target=run_flask, daemon=True, name="flask-api")
    t.start()
    logger.info(f"✅ HTTP API started on port {settings.port}")
