"""
Reset Service — Șterge datele tranzacționale ale unui user, păstrând profilul.

Folosit pentru:
- Migrare de la testare la producție (după validare)
- Re-start curat înainte de raportare oficială
- Curățare date corupte

PRINCIPIU: Niciodată nu ștergem User-ul sau profilul (firma_*, regim_*, activity).
Doar tranzacții/documente/files/periods/exports/audit (datele tranzacționale).

Securitate:
- Funcția returnează raport detaliat (audit-able)
- Nu face commit automat — apelantul decide
- Loghează în audit_log ce s-a șters
"""

import logging
from datetime import datetime
from typing import Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import text

from app.models import (
    Transaction,
    Document,
    SourceFile,
    TaxPeriod,
    ExportLog,
    AuditLog,
    User,
)

logger = logging.getLogger(__name__)


def count_user_data(session: Session, user_id: int) -> Dict[str, int]:
    """
    Numără înregistrările pe care le-ar șterge reset_user_data.
    Folosit pentru CONFIRMATION înainte de delete.
    """
    counts = {
        "transactions": session.query(Transaction).filter(
            Transaction.user_id == user_id
        ).count(),
        "documents": session.query(Document).filter(
            Document.user_id == user_id
        ).count(),
        "source_files": session.query(SourceFile).filter(
            SourceFile.user_id == user_id
        ).count(),
        "tax_periods": session.query(TaxPeriod).filter(
            TaxPeriod.user_id == user_id
        ).count(),
        "export_logs": 0,  # vor fi numărate prin documentul lor
    }

    # Numără export_logs care fac referire la documentele user-ului
    doc_ids = [
        d.id for d in session.query(Document.id).filter(
            Document.user_id == user_id
        ).all()
    ]
    if doc_ids:
        counts["export_logs"] = session.query(ExportLog).filter(
            ExportLog.document_id.in_(doc_ids)
        ).count()

    return counts


def reset_user_data(
    session: Session,
    user_id: int,
    *,
    keep_audit_log: bool = True,
) -> Dict[str, Any]:
    """
    Șterge datele tranzacționale ale user-ului, PĂSTRÂND profilul.

    Args:
        session: SQLAlchemy session
        user_id: ID-ul user-ului
        keep_audit_log: dacă True, păstrează audit_logs vechi (recomandat)

    Returns:
        dict cu raportul ștergerii: {
            "user_id": ...,
            "deleted": {transactions, documents, source_files, tax_periods, export_logs},
            "kept": {profile fields},
            "timestamp": "ISO datetime",
        }

    NOTE: Apelantul trebuie să facă session.commit() după.
    """
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        raise ValueError(f"User {user_id} not found")

    logger.info(f"🔄 Starting RESET for user_id={user_id}")

    # Contează ÎNAINTE de delete (pentru raport)
    counts_before = count_user_data(session, user_id)

    # ─── PASUL 1: Șterge ExportLogs (cele care fac referire la documentele user) ───
    doc_ids_query = session.query(Document.id).filter(
        Document.user_id == user_id
    )
    doc_ids = [d.id for d in doc_ids_query.all()]

    deleted_export_logs = 0
    if doc_ids:
        deleted_export_logs = session.query(ExportLog).filter(
            ExportLog.document_id.in_(doc_ids)
        ).delete(synchronize_session=False)
        logger.info(f"  Deleted {deleted_export_logs} export_logs")

    # ─── PASUL 2: Șterge Transactions ───
    deleted_transactions = session.query(Transaction).filter(
        Transaction.user_id == user_id
    ).delete(synchronize_session=False)
    logger.info(f"  Deleted {deleted_transactions} transactions")

    # ─── PASUL 3: Șterge Documents ───
    deleted_documents = session.query(Document).filter(
        Document.user_id == user_id
    ).delete(synchronize_session=False)
    logger.info(f"  Deleted {deleted_documents} documents")

    # ─── PASUL 4: Șterge SourceFiles ───
    deleted_source_files = session.query(SourceFile).filter(
        SourceFile.user_id == user_id
    ).delete(synchronize_session=False)
    logger.info(f"  Deleted {deleted_source_files} source_files")

    # ─── PASUL 5: Șterge TaxPeriods ───
    deleted_tax_periods = session.query(TaxPeriod).filter(
        TaxPeriod.user_id == user_id
    ).delete(synchronize_session=False)
    logger.info(f"  Deleted {deleted_tax_periods} tax_periods")

    # ─── PASUL 6: Loghează în audit (dacă păstrăm audit log) ───
    if keep_audit_log:
        audit_entry = AuditLog(
            user_id=user_id,
            entity_type="user_data",
            entity_id=user_id,
            action="reset",
            source="manual",
            note=(
                f"Reset complet: {deleted_transactions} tx, "
                f"{deleted_documents} docs, {deleted_source_files} files, "
                f"{deleted_tax_periods} periods"
            ),
        )
        session.add(audit_entry)

    # Raport final
    report = {
        "user_id": user_id,
        "deleted": {
            "transactions": deleted_transactions,
            "documents": deleted_documents,
            "source_files": deleted_source_files,
            "tax_periods": deleted_tax_periods,
            "export_logs": deleted_export_logs,
        },
        "counts_before": counts_before,
        "kept": {
            "name": user.name,
            "firma_nume": user.firma_nume,
            "firma_cui": user.firma_cui,
            "firma_forma_juridica": user.firma_forma_juridica,
            "regim_tva": user.regim_tva,
            "regim_impunere": user.regim_impunere,
            "activity_code": user.activity_code,
            "onboarding_completed": user.onboarding_completed,
        },
        "timestamp": datetime.utcnow().isoformat(),
    }

    logger.info(f"✅ RESET completed for user_id={user_id}: {report['deleted']}")
    return report
