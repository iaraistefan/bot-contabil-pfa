"""
Serviciu de postare în registru a cheltuielilor dintr-un extras bancar (felia 3 PAS 3).

Orchestrare PURĂ (fără Telegram): primește clasificarea (felia 2) + deciziile
(business/personal — din UI, felia 3 PAS 4) și postează DOAR cheltuielile permise,
cu override de categorie (PAS 1) + anti-dublură pe fingerprint (PAS 2).

🛡️ GARDĂ STRUCTURALĂ: doar bucketele CHELTUIALA_BUSINESS + DE_VERIFICAT pot fi
postate. VENIT_BOLT (dublează sync), PLATA_TAXA / RETURNARE_TAXA (decontări de
obligații — felia 5), COMISION_BANCAR (fără categorie-acasă, felia 3 minimă) NU se
postează NICIODATĂ, chiar dacă `decisions` le-ar cere. Pe bani, serviciul refuză
structural — nu ne bazăm doar pe UI să nu trimită greșit.

Nu comite — sesiunea e la apelant (ca `post_document`).
"""
import logging
import re
from typing import List, Optional

from app.integrations.imports.classify import CHELTUIALA_BUSINESS, DE_VERIFICAT
from app.integrations.imports.dedup import compute_fingerprints, exists_fingerprint
from app.repositories import documents as documents_repo
from app.repositories import audit as audit_repo
from app.services import posting

logger = logging.getLogger(__name__)

# Bucketele care POT fi postate ca CHELTUIALA. Restul: niciodată (gardă structurală).
_POSTABILE = frozenset({CHELTUIALA_BUSINESS, DE_VERIFICAT})

_MAX_DETALII = 120
_RE_WS = re.compile(r"\s+")


def _clean_detalii(descriere: Optional[str]) -> str:
    """Descriere lizibilă pentru Registru: whitespace colapsat, trunchiată."""
    s = _RE_WS.sub(" ", descriere or "").strip()
    return s[:_MAX_DETALII]


def post_bank_expenses(
    session,
    *,
    user_id: int,
    source_file_id: Optional[int],
    clasificate: List,
    decisions: List[Optional[str]],
) -> dict:
    """Postează cheltuielile business dintr-un extras clasificat.

    Args:
      clasificate: list[BankTxnClasificat] ÎNTREAGĂ (necesar pentru fingerprint —
        ocurenta se calculează peste tot extrasul).
      decisions: listă paralelă cu `clasificate`. Per index:
        - `category_code` (str)  → postează ca CHELTUIALA cu această categorie;
        - `None`                 → sărit (personal / nedecis).

    Returnează sumar: {posted, deductibil_sum, skipped_personal, skipped_dup,
    skipped_blocked, details}.

    Nu comite — apelantul comite.
    """
    if len(decisions) != len(clasificate):
        raise ValueError("`decisions` trebuie paralel cu `clasificate`")

    # Fingerprint peste TOT extrasul (ocurenta corect pe linii identice).
    fps = compute_fingerprints([r.txn for r in clasificate])

    activity = posting._get_user_activity(session, user_id)

    posted: List[dict] = []
    deductibil_sum = 0.0
    skipped_personal = 0
    skipped_dup = 0
    skipped_blocked = 0

    for i, r in enumerate(clasificate):
        cat = decisions[i]

        if cat is None:
            skipped_personal += 1
            continue

        # 🛡️ Gardă structurală: doar bucketele permise, indiferent de `decisions`.
        if r.bucket not in _POSTABILE:
            skipped_blocked += 1
            logger.warning(
                f"post_bank: refuz postare bucket={r.bucket} idx={i} "
                f"(nepermis — cerut de decisions, blocat structural)"
            )
            continue

        fp = fps[i]
        # Anti-dublură: dacă linia a mai fost importată → skip (zero scriere).
        if exists_fingerprint(session, user_id, fp):
            skipped_dup += 1
            continue

        detalii = _clean_detalii(r.txn.descriere)
        data_doc = r.txn.data.strftime("%d.%m.%Y")

        doc = documents_repo.create(
            session,
            user_id=user_id,
            source_file_id=source_file_id,
            data_doc=data_doc,
            platforma=None,
            tip="CHELTUIALA",
            brut=r.txn.suma,
            comision=0.0,
            tva=0.0,
            net=r.txn.suma,
            cash=0.0,
            banca=0.0,
            detalii=detalii,
            raw_json="",
            prompt_version="bank_bt_v1",
            status="posted",
            confidence=1.0,
        )
        audit_repo.write(
            session,
            entity_type="document",
            entity_id=doc.id,
            action="create",
            user_id=user_id,
            source="bank_import",
            after=documents_repo.to_dict(doc),
            note=f"posted from bank statement source_file_id={source_file_id}",
        )

        tx_ids = posting.post_document(
            session,
            user_id=user_id,
            document_id=doc.id,
            tip="CHELTUIALA",
            platforma=None,
            detalii=detalii,
            brut=r.txn.suma,
            comision=0.0,
            tva=0.0,
            net=r.txn.suma,
            cash=0.0,
            banca=0.0,
            data_doc=data_doc,
            category_override=cat,
            import_fingerprint=fp,
        )

        ded_pct = activity.get_deductibility_pct(cat)
        deductibil_sum += round(r.txn.suma * ded_pct / 100.0, 2)
        posted.append({
            "doc_id": doc.id,
            "tx_ids": tx_ids,
            "category": cat,
            "suma": r.txn.suma,
            "deductibil_pct": ded_pct,
        })

    return {
        "posted": len(posted),
        "deductibil_sum": round(deductibil_sum, 2),
        "skipped_personal": skipped_personal,
        "skipped_dup": skipped_dup,
        "skipped_blocked": skipped_blocked,
        "details": posted,
    }
