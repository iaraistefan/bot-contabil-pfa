"""
Repository pentru Document — operații DB centrale pe documente.
"""

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models import Document


def create(
    session: Session,
    *,
    user_id: Optional[int],
    source_file_id: Optional[int],
    data_doc: Optional[str],
    platforma: Optional[str],
    tip: str,
    brut: float = 0.0,
    comision: float = 0.0,
    tva: float = 0.0,
    net: float = 0.0,
    cash: float = 0.0,
    banca: float = 0.0,
    detalii: str = "",
    raw_json: str = "",
    prompt_version: Optional[str] = None,
    status: str = "posted",
    confidence: float = 1.0,
) -> Document:
    """
    Inserează un Document nou. Commit-ul rămâne la apelant.
    Câmpurile au aceeași semantică cu cele trimise spre Google Sheets.
    """
    doc = Document(
        user_id=user_id,
        source_file_id=source_file_id,
        data_doc=data_doc,
        platforma=platforma,
        tip=tip,
        brut=brut,
        comision=comision,
        tva=tva,
        net=net,
        cash=cash,
        banca=banca,
        detalii=detalii,
        raw_json=raw_json,
        prompt_version=prompt_version,
        status=status,
        confidence=confidence,
    )
    session.add(doc)
    session.flush()  # ca să avem doc.id înainte de commit (pentru audit)
    return doc


def to_dict(doc: Document) -> Dict[str, Any]:
    """
    Serializare pentru audit_log.after_json.
    Apelat înainte de session.close() — citim atributele cât încă sunt legate.
    """
    return {
        "id": doc.id,
        "user_id": doc.user_id,
        "source_file_id": doc.source_file_id,
        "data_doc": doc.data_doc,
        "platforma": doc.platforma,
        "tip": doc.tip,
        "brut": doc.brut,
        "comision": doc.comision,
        "tva": doc.tva,
        "net": doc.net,
        "cash": doc.cash,
        "banca": doc.banca,
        "detalii": doc.detalii,
        "status": doc.status,
        "prompt_version": doc.prompt_version,
    }
