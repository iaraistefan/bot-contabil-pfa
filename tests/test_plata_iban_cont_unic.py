"""
N1 (audit pre-lansare) — obligația D212 (cont unic 5504) NU mai afișează template-ul
IBAN spart `RO__TREZ____55.04_<CNP>__XXX`. Cade pe mesajul curat SPV/ghișeul.ro
(get_cont_unic_pf_for_cnp, deja scris). Acoperă AMBELE ramuri: BN (template) +
non-BN (iban_cont None). Obligațiile cu IBAN REAL (D301) rămân NEATINSE.

Vehicul de test: User REAL în DB → curge prin from_user_id + compute_obligation.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import User
from app.services import plata_fiscala as pf


def _setup(tmp_path, *, judet="BN", regim_tva="NEPLATITOR"):
    eng = create_engine(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    User.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    s = Session()
    u = User(
        telegram_id=1, firma_forma_juridica="PFA", activity_code="ridesharing",
        regim_tva=regim_tva, judet=judet, cnp="1900101223344",
        firma_nume="PFA Ion Popescu",
    )
    s.add(u)
    s.commit()
    uid = u.id
    s.close()
    return Session, uid


def _detail(Session, uid, cod, an=2026, luna=5):
    s = Session()
    try:
        return pf.build_payment_detail_message(s, uid, cod, an, luna)
    finally:
        s.close()


# ── D212 (BN) → mesaj SPV curat, NU template-ul spart ───────────────
def test_d212_bn_cade_pe_mesaj_spv_nu_template(tmp_path):
    Session, uid = _setup(tmp_path, judet="BN")
    msg = _detail(Session, uid, "D212")
    # template-ul spart NU mai apare
    assert "RO__TREZ" not in msg
    assert "<CNP>" not in msg
    assert "_XXX" not in msg
    # îndrumarea curată spre SPV/ghișeul.ro apare
    assert "ghiseul.ro" in msg
    # codul de buget util rămâne
    assert "55.04" in msg


# ── D212 (județ non-BN → iban_cont None) → tot mesaj SPV, fără crash ─
def test_d212_non_bn_fara_iban_tot_spv(tmp_path):
    Session, uid = _setup(tmp_path, judet="CLUJ")
    msg = _detail(Session, uid, "D212")
    assert "RO__TREZ" not in msg
    assert "ghiseul.ro" in msg


# ── D301 (IBAN REAL) → IBAN-ul real apare (dovada că NU stric plata validă) ──
# D301 e aplicabil unui PFA cu COD SPECIAL TVA (SPECIAL_INTRACOM) + factură intracom
# în lună → aici forțăm baza intracom cu monkeypatch (fără a crea documente).
def test_d301_iban_real_neatins(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, regim_tva="SPECIAL_INTRACOM")
    monkeypatch.setattr(pf, "_get_intracom_base_for_month", lambda *a, **k: 100.0)
    msg = _detail(Session, uid, "D301")
    assert "RO24TREZ10120A100101XTVA" in msg


# ── Footer condiționat: fără „Copiază IBAN" când nu e IBAN tipăribil ─
def test_footer_fara_copiaza_iban_pe_d212(tmp_path):
    Session, uid = _setup(tmp_path, judet="BN")
    msg = _detail(Session, uid, "D212")
    assert "Copiază IBAN" not in msg


def test_footer_cu_copiaza_iban_pe_d301(tmp_path, monkeypatch):
    Session, uid = _setup(tmp_path, regim_tva="SPECIAL_INTRACOM")
    monkeypatch.setattr(pf, "_get_intracom_base_for_month", lambda *a, **k: 100.0)
    msg = _detail(Session, uid, "D301")
    assert "Copiază IBAN" in msg
