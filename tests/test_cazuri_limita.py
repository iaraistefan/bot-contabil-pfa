"""
PAS 2 — cazuri-limită CAS/CASS (pensionar + angajat altundeva).

- Pensionar → CAS 0 (art. 150); CASS = 10% × net real (asigurat).
- Angajat (asigurat prin salariu) sub 6 SMB → CASS = 10% × net real (NU 0, NU minimul 2.430).
- Neasigurat sub prag → CASS = minimul 2.430 (NESCHIMBAT, regresie).
- Default (ambele False) → toate calculele identice cu azi (regresie 0).

⚠️ Zona „CASS asigurat sub prag" = surse secundare convergente (varianta b), de re-validat CECCAR.
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain.contributii import calcul_cas, calcul_cass
from app.integrations.anaf.d212_calc import calculeaza_d212
from app.models import User
from app.repositories import users as users_repo
from app.services import tax_engine

AN = 2026
SMB = 4050
PRAG6 = 6 * SMB   # 24.300


# ════════════ contributii — reguli pure ════════════
def test_pensionar_cas_zero():
    r = calcul_cas(200_000, AN, pensionar=True)
    assert r["valoare"] == 0.0 and r["aplicabil"] is False


def test_asigurat_sub_prag_pe_net_real():
    # exemplul confirmat: net 13.950 → CASS 1.395 (= 10% × 13.950), NU 0, NU 2.430
    r = calcul_cass(13_950, AN, asigurat_salariat=True)
    assert r["valoare"] == 1_395.0 and r["baza"] == 13_950.0 and r["aplicabil"] is True


def test_neasigurat_sub_prag_minim_neschimbat():
    # REGRESIE: neasigurat sub 6 SMB → baza minimă 6 SMB = 24.300 → CASS 2.430
    r = calcul_cass(13_950, AN, asigurat_salariat=False)
    assert r["valoare"] == 2_430.0 and r["baza"] == float(PRAG6)


def test_asigurat_peste_prag_neschimbat():
    # peste 6 SMB: 10% × net, indiferent de asigurat (toate variantele coincid)
    a = calcul_cass(60_000, AN, asigurat_salariat=True)["valoare"]
    b = calcul_cass(60_000, AN, asigurat_salariat=False)["valoare"]
    assert a == b == 6_000.0


# ════════════ d212_calc — cablare flag-uri ════════════
def test_d212_pensionar_cas0_cass_net_real():
    # pensionar cu venit net mic (sub 6 SMB) → CAS 0 + CASS 10% × net real
    r = calculeaza_d212(20_000, 6_050, an=AN, salariu_minim=SMB, pensionar=True)  # net 13.950
    assert r.cas == 0.0
    assert r.cass == 1_395.0          # 10% × 13.950 (pensionar = asigurat pt CASS)


def test_d212_angajat_cass_net_real():
    r = calculeaza_d212(20_000, 6_050, an=AN, salariu_minim=SMB, asigurat_salariat=True)
    assert r.cass == 1_395.0          # angajat sub prag → 10% × net real
    assert r.cas == 0.0               # net 13.950 < 12 SMB → CAS oricum 0 (prag)


def test_d212_pensionar_si_angajat_simultan():
    r = calculeaza_d212(20_000, 6_050, an=AN, salariu_minim=SMB,
                        pensionar=True, asigurat_salariat=True)
    assert r.cas == 0.0 and r.cass == 1_395.0


def test_d212_default_regresie_zero():
    # ambele flag-uri False → comportament IDENTIC cu azi (neasigurat)
    r = calculeaza_d212(20_000, 6_050, an=AN, salariu_minim=SMB)  # net 13.950
    assert r.cass == 2_430.0          # baza minimă (neschimbat)
    assert r.cas == 0.0               # sub 12 SMB


# ════════════ tax_engine — flag-uri din profil (cale reală) ════════════
def _patch_profil(monkeypatch, **flags):
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda *a, **k: {"income_total": 20_000.0/12, "expense_deductible_total": 6_050.0/12})
    pd = {"regim_impunere": "SISTEM_REAL", "activity_code": "ridesharing"}
    pd.update(flags)
    import app.repositories.users as users_repo_mod
    monkeypatch.setattr(users_repo_mod, "get_profile_dict", lambda s, uid: pd)


def test_engine_pensionar_din_profil(monkeypatch):
    _patch_profil(monkeypatch, is_pensionar=True)
    r = tax_engine._compute_d212_anual_uncached(object(), user_id=1, an=AN)
    assert r.cas == 0.0 and r.cass == 1_395.0


def test_engine_session_none_default(monkeypatch):
    # fără sesiune → ambele False → regresie (neasigurat)
    monkeypatch.setattr(tax_engine, "compute_period",
                        lambda *a, **k: {"income_total": 20_000.0/12, "expense_deductible_total": 6_050.0/12})
    r = tax_engine._compute_d212_anual_uncached(None, user_id=1, an=AN)
    assert r.cass == 2_430.0 and r.cas == 0.0


# ════════════ persistență + API ════════════
def _web(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'cl.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S(); u = User(telegram_id=1); s.add(u); s.commit(); uid = u.id; s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


def test_save_si_setari_flaguri(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path)
    r = client.post("/api/v1/onboarding/save",
                    json={"is_pensionar": True, "is_salariat": True, "step": 4})
    assert r.status_code == 200
    s = S(); u = s.get(User, uid)
    assert u.is_pensionar is True and u.is_salariat is True
    s.close()
    d = client.get("/api/v1/setari").get_json()
    assert d["is_pensionar"] is True and d["is_salariat"] is True


# ════════════ gardieni template ════════════
def test_template_wizard_situatie():
    html = (Path(__file__).resolve().parent.parent
            / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "function wizSituatie()" in html
    assert "wizToggleSituatie" in html
    assert "Sunt pensionar" in html and "angajat" in html.lower()
    assert 'is_pensionar:!!WIZ.data.is_pensionar' in html        # save flag-uri
    assert '"situatie","masina"' in html or '"regim","situatie"' in html  # pas în listă
