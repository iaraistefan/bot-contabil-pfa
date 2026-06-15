"""
Fiscal #3 — SUB-PAS D: blocul D100 servit de web (app._d100_block).

Backend CALCULEAZĂ status + sumă; JS doar afișează (regula de aur). Sursa sumei
e aceeași ca botul (calcul_impozit_nerezident). 4 status-uri:
  - de_depus (cota>0) → suma reală (round(baza×cota))
  - scutit (cota 0)   → suma 0.0
  - neconfigurat (None) → suma None (NU o cifră presupusă)
  - fara_baza (vat_out<=0) → suma None
"""

from app.http import app as webapp


def _block(monkeypatch, regim, vat_out, cota_tva=0.21):
    monkeypatch.setattr(
        webapp.users_repo, "get_profile_dict",
        lambda s, uid: {"firma_forma_juridica": "PFA", "regim_nerezident": regim},
    )
    totals = {"vat_out_total": vat_out, "cota_tva": cota_tva}
    return webapp._d100_block(None, 1, 2026, 1, totals)


# vat_out 137.97 @ cotă TVA 0.21 → bază 657 (din care „13 lei" la 2%)
VAT_OUT_657 = 137.97


def test_de_depus_2pct(monkeypatch):
    b = _block(monkeypatch, "BOLT_CU_CRF", VAT_OUT_657)   # Bolt cu certificat → 2%
    assert b["status"] == "de_depus"
    assert b["cota"] == 0.02
    assert b["suma"] == 13.0                      # round(657×0.02), ca botul


def test_de_depus_16pct(monkeypatch):
    b = _block(monkeypatch, "BOLT_FARA_CRF", VAT_OUT_657)  # Bolt fără certificat → 16%
    assert b["status"] == "de_depus"
    assert b["cota"] == 0.16
    assert b["suma"] == 105.0                     # round(657×0.16)


def test_scutit(monkeypatch):
    # 0% = scutit: NU Bolt (Bolt n-are 0%), ci Uber cu certificat (engine).
    b = _block(monkeypatch, "UBER_CU_CRF", VAT_OUT_657)
    assert b["status"] == "scutit"
    assert b["suma"] == 0.0
    assert b["cota"] == 0.0


def test_neconfigurat_fara_suma(monkeypatch):
    b = _block(monkeypatch, None, VAT_OUT_657)
    assert b["status"] == "neconfigurat"
    assert b["suma"] is None                      # NU o cifră presupusă
    assert b["cota"] is None


def test_neconfigurat_si_la_regim_invalid(monkeypatch):
    b = _block(monkeypatch, "CEVA_GRESIT", VAT_OUT_657)
    assert b["status"] == "neconfigurat"
    assert b["suma"] is None


def test_fara_baza_indiferent_de_regim(monkeypatch):
    # nicio factură Bolt → fara_baza chiar dacă regimul ar fi setat
    for regim in ("BOLT_CU_CRF", "BOLT_FARA_CRF", "UBER_CU_CRF", None):
        b = _block(monkeypatch, regim, vat_out=0.0)
        assert b["status"] == "fara_baza"
        assert b["suma"] is None
