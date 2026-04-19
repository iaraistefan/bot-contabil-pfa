"""
Integrare Google Sheets — singurul loc unde scriem în spreadsheet.

Responsabilități:
- Determină tab-ul lunii corecte (crează dacă nu există).
- Scrie un rând nou pentru document.
- Loghează tentativa în export_logs (ok sau failed).

Nu face commit — sesiunea DB e la apelant.
"""

import logging
from typing import List, Optional

import gspread
from oauth2client.service_account import ServiceAccountCredentials
from sqlalchemy.orm import Session

from app.models import ExportLog

logger = logging.getLogger(__name__)

LUNI_RO = {
    "01": "Ianuarie", "02": "Februarie", "03": "Martie", "04": "Aprilie",
    "05": "Mai", "06": "Iunie", "07": "Iulie", "08": "August",
    "09": "Septembrie", "10": "Octombrie", "11": "Noiembrie", "12": "Decembrie"
}

SHEET_HEADER = [
    "Data", "Platforma", "Tip", "Brut", "Comision",
    "TVA (21%)", "Net", "Cash", "Banca", "Detalii"
]


def _get_or_create_worksheet(spreadsheet, tab_name: str):
    """Returnează worksheet-ul cu numele dat, îl crează dacă nu există."""
    try:
        return spreadsheet.worksheet(tab_name)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=500, cols=10)
        ws.append_row(SHEET_HEADER)
        logger.info(f"Created new worksheet: {tab_name}")
        return ws


def _tab_name_from_date(date_str: Optional[str]) -> str:
    """
    Derivă numele tab-ului din data documentului (DD.MM.YYYY).
    Fallback: 'General'.
    """
    if not date_str:
        return "General"
    try:
        parts = date_str.split('.')
        luna_cifra = parts[1]
        anul = parts[2]
        nume_luna = LUNI_RO.get(luna_cifra, "General")
        return f"{nume_luna} {anul}"
    except (IndexError, AttributeError):
        return "General"


def upsert_document(
    session: Session,
    *,
    doc_id: int,
    row_data: List,
    date_str: Optional[str],
    sheet_name: str,
    credentials_file: str,
) -> Optional[str]:
    """
    Adaugă un rând pentru doc_id în tab-ul lunii corecte.

    Întoarce numele tab-ului dacă a reușit, None dacă a eșuat.
    Loghează rezultatul în export_logs (fără commit — la apelant).

    Design note: "upsert" din nume — în viitor vom putea face
    find-by-doc_id + update în loc de append, pentru re-sync.
    Momentan e append simplu (suficient până la pasul 13+).
    """
    tab_name = _tab_name_from_date(date_str)
    status = "ok"
    response_msg = None

    try:
        scope = [
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive',
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_file, scope)
        client = gspread.authorize(creds)
        spreadsheet = client.open(sheet_name)
        ws = _get_or_create_worksheet(spreadsheet, tab_name)
        ws.append_row(row_data)
        logger.info(f"Sheets: appended doc_id={doc_id} to tab '{tab_name}'")

    except Exception as e:
        status = "failed"
        response_msg = str(e)[:500]
        tab_name = None
        logger.error(f"Sheets write failed for doc_id={doc_id}: {e}")

    # Log tentativa în DB (nu blocăm dacă și asta crapă)
    try:
        log_entry = ExportLog(
            target="sheets",
            entity_type="document",
            entity_id=doc_id,
            document_id=doc_id,
            external_ref=tab_name,
            status=status,
            response_msg=response_msg,
        )
        session.add(log_entry)
        session.flush()
    except Exception as e:
        logger.error(f"ExportLog insert failed for doc_id={doc_id}: {e}")

    return tab_name
