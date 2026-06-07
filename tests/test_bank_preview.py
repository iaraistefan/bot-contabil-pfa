"""
Teste pentru afișajul preview al importului de extras (felia 1 PAS 2).

Funcții pure (fără Telegram): _fmt_ron + _format_bank_preview.
Handler-ul async (download + parse) e acoperit indirect de parserul testat în
test_bt_parser.py; aici testăm formatarea (numere RO + conținut preview).
"""
from datetime import date

from app.integrations.imports.bank_statement import BankTxn
import bot_contabil as b


def test_fmt_ron_format_romanesc():
    assert b._fmt_ron(1019.45) == "1.019,45"
    assert b._fmt_ron(769.77) == "769,77"
    assert b._fmt_ron(5.0) == "5,00"
    assert b._fmt_ron(0.51) == "0,51"


def _sample():
    return [
        BankTxn(date(2026, 4, 14), 248.33, "IN", "Incasare OP BOLT"),
        BankTxn(date(2026, 4, 2), 31.81, "OUT", "Plata POS card"),
        BankTxn(date(2026, 4, 30), 7.00, "IN", "Returnare plata"),
    ]


def test_preview_totaluri_si_count():
    msg = b._format_bank_preview(_sample())
    assert "3 tranzacții" in msg
    assert "2 încasări" in msg and "255,33 lei" in msg   # 248.33 + 7.00
    assert "1 plăți" in msg and "31,81 lei" in msg
    assert "RULAJ TOTAL CONT" in msg                      # mențiune checksum


def test_preview_nu_scrie_in_registru():
    msg = b._format_bank_preview(_sample())
    assert "nu am adăugat nimic în registru" in msg.lower()


def test_preview_trunchiaza_descriere_lunga():
    lung = "x" * 100
    msg = b._format_bank_preview([BankTxn(date(2026, 4, 1), 10.0, "OUT", lung)])
    assert "…" in msg
    assert ("x" * 100) not in msg                         # descrierea e trunchiată
