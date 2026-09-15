"""
Repository pentru Document.
"""

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.enums import DocStatus
from app.models import Document


def count_by_tip(session, user_id: int, tip, status: str = DocStatus.POSTED.value) -> int:
    """
    Numarul de documente de un tip dat ale userului (pentru detectia 'prima cheltuiala').

    `status` e PARAMETRU, nu valoare cablata inauntru, si asta tine de NUMELE functiei:
    ea promite „numara dupa TIP". Daca ar filtra tacut si pe status, numele ar minti —
    apelantul ar primi alt numar decat cere, fara sa i se spuna. Asa, implicitul e
    vizibil in semnatura si se poate schimba la apel.

    Implicit „posted", fiindca apelantul de azi intreaba „e prima ta cheltuiala
    INREGISTRATA?" ca sa trimita un mesaj de intampinare o singura data. Un document
    neconfirmat n-a inregistrat nimic; daca l-ar numara, mesajul s-ar consuma pe ceva
    ce omul n-a confirmat si n-ar mai aparea la cheltuiala adevarata.

    ALLOWLIST prin constructie: filtrul spune ce valoare vrea, nu ce valoare respinge.
    `status=None` cere EXPLICIT toate starile — pentru cine chiar vrea asta.
    Vezi app/enums.py (DOC_STATUSES_SCRISE) si tests/test_status_allowlist.py.
    """
    q = session.query(Document).filter(Document.user_id == user_id, Document.tip == tip)
    if status is not None:
        q = q.filter(Document.status == status)
    return q.count()


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
    """Inserează un Document nou. Commit la apelant."""
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
    session.flush()
    return doc


def get_by_id(
    session: Session,
    doc_id: int,
    user_id: int,
) -> Optional[Document]:
    """
    Returnează documentul cu doc_id DOAR dacă aparține user-ului, altfel None.

    SECURITATE: user_id e OBLIGATORIU (nu opțional) — scope-ul multi-tenant e impus
    prin construcție, nu prin disciplina apelantului. Un apelant nu poate „uita"
    user_id (ar fi TypeError) → footgun-ul (citirea documentului altui user) e
    fizic imposibil. Vezi tests/test_isolation_boundary.py.
    """
    return (
        session.query(Document)
        .filter(Document.id == doc_id, Document.user_id == user_id)
        .one_or_none()
    )


def set_status(
    session: Session,
    doc: Document,
    new_status: str,
) -> None:
    """Schimbă status-ul unui document. Commit la apelant."""
    doc.status = new_status


def to_dict(doc: Document) -> Dict[str, Any]:
    """Serializare pentru audit_log.after_json."""
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


# ============================================================
#   LOTURI NECONFIRMATE (status "needs_review")
# ============================================================
#
# Un lot = documentele extrase dintr-O SINGURĂ sursă (o poză, un PDF), grupate pe
# `source_file_id`. Cheia exista deja; nu inventăm alta.
#
# ⚠️ NU EXISTĂ RETENȚIE AUTOMATĂ, și e o DECIZIE, nu o omisiune.
# Un lot neconfirmat nu e gunoi — e un document neterminat, iar extracția rămâne
# validă oricât ar trece, fiindcă documentul în sine nu se schimbă. O expirare
# tăcută ar fi exact pierderea pe care persistarea asta o repară.
# Loturile se închid DOAR prin acțiunea omului: confirmă (→ "posted") sau renunță
# (→ "rejected"). Se văd în /neterminate și, marcate, în lista de documente.
# Dacă lista devine vreodată o problemă reală, curățenia se decide ATUNCI, pe
# măsurătoare — nu se ghicește acum printr-un TTL scos din burtă.

def get_lot_pending(session, user_id: int, source_file_id: int):
    """Documentele neconfirmate ale unei surse, în ordinea creării."""
    return (
        session.query(Document)
        .filter(
            Document.user_id == user_id,
            Document.source_file_id == source_file_id,
            Document.status == DocStatus.NEEDS_REVIEW.value,
        )
        .order_by(Document.id.asc())
        .all()
    )


def list_loturi_pending(session, user_id: int, limit: int = 20):
    """
    Loturile neconfirmate ale userului, cel mai recent primul.
    Întoarce [(source_file_id, [documente])] — gruparea se face pe cheia existentă.
    """
    docs = (
        session.query(Document)
        .filter(
            Document.user_id == user_id,
            Document.status == DocStatus.NEEDS_REVIEW.value,
            Document.source_file_id.isnot(None),
        )
        .order_by(Document.id.desc())
        .all()
    )
    loturi = {}
    for d in docs:
        loturi.setdefault(d.source_file_id, []).append(d)
    # dict-urile Python păstrează ordinea inserării → deja „cel mai recent primul"
    iesire = [(sfid, list(reversed(items))) for sfid, items in loturi.items()]
    return iesire[:limit]


def set_status_lot(session, docs, new_status: str) -> int:
    """
    Schimbă starea TUTUROR documentelor unui lot. Commit la apelant.
    Lotul se mișcă întreg — aceeași regulă ca la salvare (ori toate, ori niciuna).
    """
    for d in docs:
        d.status = new_status
    return len(docs)
