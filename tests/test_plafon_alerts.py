"""
Teste pentru alertele „aproape de plafon" (Faza 3 — PAS 3, cel sensibil).

_check_plafon_alerts: pre-check ieftin → compute_d212_anual → TVA (vat_threshold_status)
+ CAS (prag_cas_status), anti-spam, caveat uniform. Totul mock-uit (zero rețea/DB grea).
"""

from types import SimpleNamespace
from datetime import date

from app.services import proactive_alerts as pa
from app.services import tax_engine
from app.domain.fiscal_profile import from_user_dict


def _ctx(is_vat_payer=False):
    return {"is_vat_payer": is_vat_payer,
            "fiscal_profile": from_user_dict({"firma_forma_juridica": "PFA"})}


def _setup(monkeypatch, ca, venit_brut, venit_net, already=False):
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: ca)
    monkeypatch.setattr(tax_engine, "compute_d212_anual",
                        lambda s, *, user_id, an: SimpleNamespace(
                            venit_brut=venit_brut, venit_net=venit_net,
                            total_plata=0.0))
    monkeypatch.setattr(pa, "_was_alert_sent", lambda *a, **k: already)
    sent, logged = [], []
    monkeypatch.setattr(pa, "_send_telegram_message",
                        lambda tok, chat, msg: (sent.append((chat, msg)) or True))
    monkeypatch.setattr(pa, "_log_alert_sent",
                        lambda *a, **k: logged.append(a))
    return sent, logged


_USER = SimpleNamespace(id=1, telegram_id=10)
_TODAY = date(2026, 6, 7)


# ────────────────────────────────────────────────────────────

def test_precheck_skip_nu_cheama_compute(monkeypatch):
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: 30_000)  # < 38.880
    def _spy(*a, **k):
        raise AssertionError("compute_d212_anual NU trebuie chemat sub pre-check")
    monkeypatch.setattr(tax_engine, "compute_d212_anual", _spy)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 0


def test_tva_aproape(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 1                                        # doar TVA (CAS sub prag)
    msg = sent[0][1]
    assert "TVA" in msg and "Mai ai" in msg
    assert "verifică cu contabilul" in msg              # caveat uniform
    assert any("PLAFON_TVA" in str(a) and "prag_80" in str(a) for a in logged)


def test_tva_depasit(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=310_000, venit_brut=310_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 1
    assert "depășit" in sent[0][1].lower()
    assert any("prag_depasit" in str(a) for a in logged)


def test_cas_aproape(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=45_000, venit_brut=45_000, venit_net=45_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 1                                        # doar CAS (TVA 15% OK)
    assert "CAS" in sent[0][1]
    assert any("PLAFON_CAS" in str(a) for a in logged)


def test_ambele_praguri(monkeypatch):
    # venit mare: TVA aproape + CAS depășit -> 2 alerte
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000, venit_net=60_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 2


def test_anti_spam(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000,
                          venit_net=45_000, already=True)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 0 and sent == []


def test_vat_payer_skip_tva(monkeypatch):
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000, venit_net=30_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(is_vat_payer=True), _TODAY)
    assert n == 0                                        # TVA skip (plătitor), CAS OK
    assert not any("TVA" in m for c, m in sent)


def test_escaladare_prag_80_apoi_depasit(monkeypatch):
    # prag_80 deja marcat; la depășire (alt alert_type prag_depasit) → alertă nouă
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: 310_000)
    monkeypatch.setattr(tax_engine, "compute_d212_anual",
                        lambda s, *, user_id, an: SimpleNamespace(
                            venit_brut=310_000, venit_net=30_000, total_plata=0.0))
    monkeypatch.setattr(pa, "_was_alert_sent",
                        lambda s, uid, code, y, m, at: at == "prag_80")  # doar 80%
    sent, logged = [], []
    monkeypatch.setattr(pa, "_send_telegram_message",
                        lambda tok, chat, msg: (sent.append(msg) or True))
    monkeypatch.setattr(pa, "_log_alert_sent", lambda *a, **k: logged.append(a))

    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 1                                       # escaladare → alertă nouă
    assert "depășit" in sent[0].lower()
    assert any("prag_depasit" in str(a) for a in logged)


def test_send_esuat_nu_marcheaza(monkeypatch):
    sent, logged = [], []
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: 250_000)
    monkeypatch.setattr(tax_engine, "compute_d212_anual",
                        lambda s, *, user_id, an: SimpleNamespace(
                            venit_brut=250_000, venit_net=30_000, total_plata=0.0))
    monkeypatch.setattr(pa, "_was_alert_sent", lambda *a, **k: False)
    monkeypatch.setattr(pa, "_send_telegram_message", lambda *a: False)  # eșuat
    monkeypatch.setattr(pa, "_log_alert_sent", lambda *a, **k: logged.append(a))

    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 0
    assert logged == []                                # garda NU s-a marcat → reîncearcă


def test_cas24_dublare(monkeypatch):
    # venit_net peste 24 SMB (97.200): CAS 12 depășit + CAS 24 depășit (2 evenimente
    # distincte, independente). TVA OK (venit_brut mic). prag_* reale (nemock-uite).
    sent, logged = _setup(monkeypatch, ca=120_000, venit_brut=120_000, venit_net=120_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 2                                        # CAS 12 + CAS 24
    assert any("dublează" in m.lower() for c, m in sent)
    assert any("PLAFON_CAS24" in str(a) and "prag_depasit" in str(a) for a in logged)
    assert any("PLAFON_CAS" in str(a) and "PLAFON_CAS24" not in str(a) for a in logged)


def test_cass60_plafonare(monkeypatch):
    # venit_net peste 60 SMB (243.000): CASS plafonat (informativ). VAT payer →
    # skip TVA, ca să izolăm. CAS 12 + CAS 24 + CASS 60 toate depășite.
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000, venit_net=250_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(is_vat_payer=True), _TODAY)
    assert n == 3                                        # CAS 12 + CAS 24 + CASS 60
    cass_msg = next(m for c, m in sent if "plafon" in m.lower() and "CASS" in m)
    assert "nu mai crește" in cass_msg.lower()
    assert "ℹ️" in cass_msg and "🔴" not in cass_msg     # ton informativ, nu alarmant
    assert any("PLAFON_CASS60" in str(a) for a in logged)


def test_toate_4_pragurile(monkeypatch):
    # high earner: TVA depășit + CAS 12 + CAS 24 + CASS 60 → 4 alerte, coduri distincte.
    sent, logged = _setup(monkeypatch, ca=310_000, venit_brut=310_000, venit_net=250_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 4
    coduri = {c for a in logged for c in
              ("PLAFON_TVA", "PLAFON_CAS24", "PLAFON_CASS60") if c in str(a)}
    assert coduri == {"PLAFON_TVA", "PLAFON_CAS24", "PLAFON_CASS60"}


def test_praguri_noi_nu_afecteaza_cele_vechi(monkeypatch):
    # venit sub pragurile noi (CAS24 80%=77.760, CASS60 80%=194.400): doar TVA+CAS12,
    # noile praguri tac (OK) → comportament identic cu înainte.
    sent, logged = _setup(monkeypatch, ca=250_000, venit_brut=250_000, venit_net=50_000)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 2                                        # TVA aproape + CAS 12 depășit
    assert not any("PLAFON_CAS24" in str(a) for a in logged)
    assert not any("PLAFON_CASS60" in str(a) for a in logged)


def test_robust_compute_crapa(monkeypatch):
    monkeypatch.setattr(pa, "_ytd_income_brut", lambda s, u, y: 250_000)
    def _boom(*a, **k):
        raise RuntimeError("compute down")
    monkeypatch.setattr(tax_engine, "compute_d212_anual", _boom)
    n = pa._check_plafon_alerts(None, "tok", _USER, _ctx(), _TODAY)
    assert n == 0                                        # eroare → 0, fără crash
