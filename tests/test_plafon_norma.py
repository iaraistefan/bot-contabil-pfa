"""
Alertă PLAFON NORMĂ (trackere fiscal final) — trecere obligatorie la sistem real.

Sursă: art. 69 Cod Fiscal — venit BRUT încasat peste 25.000 EUR (126.038 lei în 2026,
curs mediu BNR 2025 5,0415) → din anul URMĂTOR sistem real obligatoriu. DOAR pe
regim NORMA_VENIT. Pe venit BRUT (nu net). În pattern-ul `_check_plafon_alerts`
existent (anti-spam fiscal_alert_sent + sender _maybe_send_plafon).
"""

from types import SimpleNamespace
from datetime import date

from app.services import proactive_alerts as pa
from app.services import tax_engine
from app.domain import norma_venit
from app.domain.fiscal_profile import from_user_dict

AN = 2026
PLAFON = 126_038.0


# ════════════════════════════════════════════════════════════
#   prag_norma_status (pur, refolosind contributii.prag_core)
# ════════════════════════════════════════════════════════════

def test_plafon_norma_constanta_pe_an():
    assert norma_venit.plafon_norma_venit(2026) == PLAFON
    assert norma_venit.plafon_norma_venit(2030) is None        # an necunoscut → None


def test_prag_norma_status_ok():
    st = norma_venit.prag_norma_status(50_000, AN)             # 39.7%
    assert st["status"] == "OK"
    assert st["threshold_ron"] == PLAFON
    assert "Sub plafonul" in st["message"]


def test_prag_norma_status_aproape():
    st = norma_venit.prag_norma_status(110_000, AN)            # 87.3% ≥ 80%
    assert st["status"] == "APROAPE_PLAFON"
    assert "Te apropii" in st["message"] and "sistem real" in st["message"]


def test_prag_norma_status_depasit():
    st = norma_venit.prag_norma_status(130_000, AN)            # 103% ≥ 100%
    assert st["status"] == "DEPASIT_PLAFON"
    assert "depășit" in st["message"].lower() and "art. 69" in st["message"]


def test_prag_norma_status_an_necunoscut_none():
    assert norma_venit.prag_norma_status(130_000, 2030) is None  # fără cifră presupusă


# ════════════════════════════════════════════════════════════
#   Cablare în _check_plafon_alerts — gating + brut + anti-spam
# ════════════════════════════════════════════════════════════

def _ctx(regim=None, is_vat_payer=False):
    ctx = {"is_vat_payer": is_vat_payer,
           "fiscal_profile": from_user_dict({"firma_forma_juridica": "PFA"})}
    if regim is not None:
        ctx["profile_dict"] = {"regim_impunere": regim}
    return ctx


def _setup(monkeypatch, ca, venit_brut, venit_net, already=False):
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: ca)
    monkeypatch.setattr(tax_engine, "compute_d212_anual",
                        lambda s, *, user_id, an: SimpleNamespace(
                            venit_brut=venit_brut, venit_net=venit_net, total_plata=0.0))
    monkeypatch.setattr(pa, "_was_alert_sent", lambda *a, **k: already)
    sent, logged = [], []
    monkeypatch.setattr(pa, "_send_telegram_message",
                        lambda tok, chat, msg: (sent.append((chat, msg)) or True))
    monkeypatch.setattr(pa, "_log_alert_sent", lambda *a, **k: logged.append(a))
    return sent, logged


_USER = SimpleNamespace(id=1, telegram_id=10)
_TODAY = date(AN, 6, 7)


def test_gating_norma_aproape_doar_pe_norma(monkeypatch):
    # NORMA_VENIT, brut 110.000 (87% din plafon), TVA OK (28% din 395k), CAS net mic OK
    sent, logged = _setup(monkeypatch, ca=110_000, venit_brut=110_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(regim="NORMA_VENIT"), _TODAY)
    assert n == 1
    assert "plafonul de normă" in sent[0][1] and "sistem real" in sent[0][1]
    assert any("PLAFON_NORMA" in str(a) and "prag_80" in str(a) for a in logged)


def test_gating_sistem_real_fara_alerta_norma(monkeypatch):
    # SISTEM_REAL la același brut → NICIO alertă normă (gating)
    sent, logged = _setup(monkeypatch, ca=110_000, venit_brut=110_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(regim="SISTEM_REAL"), _TODAY)
    assert n == 0
    assert not any("PLAFON_NORMA" in str(a) for a in logged)


def test_gating_fara_profile_dict_fara_alerta(monkeypatch):
    # ctx fără profile_dict (ca testele vechi) → fără alertă normă (regresie sigură)
    sent, logged = _setup(monkeypatch, ca=110_000, venit_brut=110_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert not any("PLAFON_NORMA" in str(a) for a in logged)


def test_pe_brut_nu_pe_net(monkeypatch):
    # brut 130.000 (depășit) DAR net 20.000 (sub orice prag CAS) → alerta normă pe BRUT
    sent, logged = _setup(monkeypatch, ca=130_000, venit_brut=130_000, venit_net=20_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(regim="NORMA_VENIT"), _TODAY)
    assert n == 1
    assert "depășit" in sent[0][1].lower()
    assert any("PLAFON_NORMA" in str(a) and "prag_depasit" in str(a) for a in logged)


def test_anti_spam_norma(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=110_000, venit_brut=110_000,
                          venit_net=30_000, already=True)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(regim="NORMA_VENIT"), _TODAY)
    assert n == 0 and sent == []


def test_norma_sub_plafon_fara_alerta(monkeypatch):
    # brut 50.000 (40% din plafon) pe normă → OK, fără alertă normă
    sent, logged = _setup(monkeypatch, ca=50_000, venit_brut=50_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(regim="NORMA_VENIT"), _TODAY)
    assert not any("PLAFON_NORMA" in str(a) for a in logged)
