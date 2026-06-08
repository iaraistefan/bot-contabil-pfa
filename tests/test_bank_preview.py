"""
Teste pentru afișajul preview al importului de extras (felia 2 PAS 2).

Funcții pure (fără Telegram): _fmt_ron + _format_bank_preview.
_format_bank_preview primește deja `list[BankTxnClasificat]` (handler-ul
orchestrează activity + clasificare); aici testăm DOAR formatarea grupată
(numere RO + grupuri pe buckete + linia net 0 + disclaimer).
"""
from datetime import date

from app.integrations.imports.bank_statement import BankTxn
from app.integrations.imports.classify import (
    BankTxnClasificat,
    VENIT_BOLT, PLATA_TAXA, RETURNARE_TAXA, COMISION_BANCAR, DE_VERIFICAT,
)
import bot_contabil as b


def test_fmt_ron_format_romanesc():
    assert b._fmt_ron(1019.45) == "1.019,45"
    assert b._fmt_ron(769.77) == "769,77"
    assert b._fmt_ron(5.0) == "5,00"
    assert b._fmt_ron(0.51) == "0,51"


def _cl(bucket, directie, suma, eticheta, descriere="x", d=date(2026, 4, 1)):
    return BankTxnClasificat(BankTxn(d, suma, directie, descriere), bucket, eticheta)


def _sample():
    # 2 Bolt (699,45) + 1 plată (40) + 1 returnare (40, anulează plata) +
    # 1 comision + 1 de verificat = 6 tranzacții, 5 clasificate, 1 de verificat.
    return [
        _cl(DE_VERIFICAT, "OUT", 31.81, "De verificat", d=date(2026, 4, 2)),
        _cl(VENIT_BOLT, "IN", 248.33, "Venit Bolt", d=date(2026, 4, 14)),
        _cl(VENIT_BOLT, "IN", 451.12, "Venit Bolt", d=date(2026, 4, 20)),
        _cl(PLATA_TAXA, "OUT", 40.0, "Plată obligație fiscală", d=date(2026, 4, 5)),
        _cl(RETURNARE_TAXA, "IN", 40.0, "Returnare taxă respinsă", d=date(2026, 4, 6)),
        _cl(COMISION_BANCAR, "OUT", 0.51, "Comision bancar", d=date(2026, 4, 27)),
    ]


def test_preview_header_clasificate_vs_verificat():
    msg = b._format_bank_preview(_sample())
    assert "6 tranzacții" in msg
    assert "5 clasificate, 1 de verificat" in msg
    assert "RULAJ TOTAL CONT" in msg


def test_preview_grupuri_sume():
    msg = b._format_bank_preview(_sample())
    # Bolt agregat: 248,33 + 451,12 = 699,45
    assert "Venituri Bolt:" in msg and "699,45 lei" in msg
    assert "Comisioane bancare:" in msg and "deductibile" in msg
    assert "De verificat:" in msg and "tu decizi la confirmare" in msg


def test_preview_venit_bolt_separat_de_returnari():
    # Veniturile Bolt NU se adună cu returnările; sunt grupuri distincte.
    msg = b._format_bank_preview(_sample())
    assert "Venituri Bolt:" in msg
    assert "Returnări (plăți respinse):" in msg
    # returnarea (40) nu apare ca venit Bolt (699,45 rămâne doar Bolt)
    assert "699,45 lei" in msg


def test_preview_net_zero_plati_returnari():
    # Plată 40 == Returnare 40 → linia explicită „net 0".
    msg = b._format_bank_preview(_sample())
    assert "net 0" in msg
    assert "respinse" in msg.lower()


def test_preview_returnari_fara_egalitate_linie_neutra():
    # Sume diferite → NU afirmăm „net 0" (pe bani: nu mințim), dar marcăm că
    # returnările nu sunt venit nou.
    sample = [
        _cl(PLATA_TAXA, "OUT", 100.0, "Plată obligație fiscală"),
        _cl(RETURNARE_TAXA, "IN", 40.0, "Returnare taxă respinsă"),
    ]
    msg = b._format_bank_preview(sample)
    assert "net 0" not in msg
    assert "nu venit nou" in msg


def test_preview_nu_scrie_in_registru():
    msg = b._format_bank_preview(_sample())
    assert "nu am adăugat nimic în registru" in msg.lower()


def test_preview_grup_gol_nu_apare():
    # Doar Bolt → grupurile fără tranzacții nu sunt afișate.
    msg = b._format_bank_preview([_cl(VENIT_BOLT, "IN", 100.0, "Venit Bolt")])
    assert "Venituri Bolt:" in msg
    assert "Comisioane bancare:" not in msg
    assert "De verificat:" not in msg


def test_preview_trunchiaza_eticheta_lunga():
    lung = "y" * 100
    msg = b._format_bank_preview([_cl(DE_VERIFICAT, "OUT", 10.0, lung)])
    assert "…" in msg
    assert ("y" * 100) not in msg
