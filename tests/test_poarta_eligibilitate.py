"""
Poarta de eligibilitate „Ai PFA în România?" — PRECONDIȚIE, nu pas.

Miezul e mecanic: `enterWizard` sare direct la `current_step` citit din profil.
Orice pas de index 0 ar fi ocolit de oricine are `onboarding_step > 0` — adică
exact de cine a început deja configurarea. De aceea poarta se verifică ÎNAINTEA
calculului lui `WIZ.i` și NU intră în `wizSteps()`.

Întrebarea e pe FAPT, nu pe identitate: un străin cu PFA în România e eligibil,
un român fără PFA nu are ce administra aici.

Blocarea e REVERSIBILĂ prin construcție — „" scrie NULL înapoi, deci un clic
greșit nu exclude permanent un client real.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.domain import eligibilitate as elig
from app.models import User

_ROOT = Path(__file__).resolve().parent.parent
_HTML = (_ROOT / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _web(monkeypatch, tmp_path, nume, *, raspuns=None, step=0):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / nume).as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    s.add(User(telegram_id=1, eligibilitate_pfa=raspuns, onboarding_step=step))
    s.commit()
    uid = s.query(User).one().id
    s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    return webapp.flask_app.test_client(), S, uid


# ── 1. Regula pură ───────────────────────────────────────────

@pytest.mark.parametrize("val,trece", [
    (elig.DA, True),
    (elig.VREAU, True),      # exact omul căruia îi e de folos ghidul de înființare
    (elig.NU, False),
    (None, False),           # neîntrebat NU e trecere
    ("", False),
    ("da", True),            # normalizat la scriere, dar regula e pe valoarea stocată
])
def test_regula_de_trecere(val, trece):
    assert elig.trece_poarta(val.upper() if isinstance(val, str) else val) is trece


# ── 2. MIEZUL: pas avansat, fără răspuns → tot vede poarta ───

@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_pas_5_fara_raspuns_vede_totusi_poarta():
    """Ăsta e testul care contează: resume-ul NU are voie să ocolească poarta."""
    ecran = _enterwizard_via_node(eligibilitate_pfa=None, trece=False, current_step=5)
    assert ecran == "poarta", (
        "userul cu onboarding_step=5 a intrat în wizard fără să răspundă — "
        "poarta a fost tratată ca pas, nu ca precondiție"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_cu_raspuns_da_nu_mai_vede_poarta_indiferent_de_pas():
    for pas in (0, 3, 5):
        assert _enterwizard_via_node(
            eligibilitate_pfa="DA", trece=True, current_step=pas
        ) == "wizard", f"poarta reapare la pasul {pas}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_raspuns_negativ_duce_la_ecranul_de_blocare():
    assert _enterwizard_via_node(
        eligibilitate_pfa="NU", trece=False, current_step=0
    ) == "blocat"


def _enterwizard_via_node(*, eligibilitate_pfa, trece, current_step):
    """Rulează enterWizard() real, cu tot ce atinge înlocuit cu spioni.

    Întoarce „poarta" / „blocat" / „wizard" — care ecran a fost randat.
    """
    m = re.search(r"function enterWizard\(status\)\s*\{[\s\S]*?\n  \}", _HTML)
    assert m, "enterWizard negăsit"
    prelude = """
      const WIZ={i:0,data:{},esc:(x)=>x};
      let ECRAN=null;
      const document={body:{classList:{add(){},remove(){}}},getElementById:()=>null};
      function wizSteps(){ return ["nume","cui","regim","situatie"]; }
      function wizRender(){ ECRAN="wizard"; }
      function wizPoarta(){ ECRAN = WIZ.data.eligibilitate_pfa==="NU" ? "blocat" : "poarta"; }
    """
    script = (prelude + m.group(0)
              + f"\nenterWizard({json.dumps({'data': {}, 'current_step': current_step, 'eligibilitate_pfa': eligibilitate_pfa, 'eligibilitate_trece': trece})});"
              + "\nconsole.log(ECRAN);")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# ── 3. Serverul refuză, nu doar clientul ────────────────────

def test_save_refuza_fara_raspuns_chiar_chemat_direct(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "fara.db", raspuns=None)
    r = client.post("/api/v1/onboarding/save", json={"name": "Ocolitor", "step": 1})
    assert r.status_code == 403
    assert r.get_json()["error"] == "eligibilitate_lipsa"
    s = S()
    try:
        assert s.get(User, uid).name is None          # nimic scris
    finally:
        s.close()


def test_save_refuza_si_pe_raspuns_negativ(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "nu.db", raspuns="NU")
    r = client.post("/api/v1/onboarding/save", json={"name": "X", "step": 1})
    assert r.status_code == 403


def test_save_accepta_chiar_raspunsul_portii(monkeypatch, tmp_path):
    # exceptia necesara: altfel nimeni n-ar putea trece vreodata
    client, S, uid = _web(monkeypatch, tmp_path, "poarta.db", raspuns=None)
    r = client.post("/api/v1/onboarding/save", json={"eligibilitate_pfa": "DA"})
    assert r.status_code == 200
    s = S()
    try:
        assert s.get(User, uid).eligibilitate_pfa == "DA"
    finally:
        s.close()


def test_dupa_raspuns_salvarea_normala_trece(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "dupa.db", raspuns="VREAU")
    assert client.post("/api/v1/onboarding/save",
                       json={"name": "Ion", "step": 1}).status_code == 200


# ── 4. Calea de întors ───────────────────────────────────────

def test_blocarea_e_reversibila(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "revers.db", raspuns="NU")
    # butonul „am apăsat greșit" trimite sirul gol → sterge raspunsul
    assert client.post("/api/v1/onboarding/save",
                       json={"eligibilitate_pfa": ""}).status_code == 200
    s = S()
    try:
        assert s.get(User, uid).eligibilitate_pfa is None      # înapoi la neîntrebat
    finally:
        s.close()
    # iar apoi poate răspunde altfel
    assert client.post("/api/v1/onboarding/save",
                       json={"eligibilitate_pfa": "DA"}).status_code == 200


def test_status_expune_poarta(monkeypatch, tmp_path):
    client, S, uid = _web(monkeypatch, tmp_path, "status.db", raspuns=None, step=5)
    d = client.get("/api/v1/onboarding/status").get_json()
    assert d["eligibilitate_pfa"] is None
    assert d["eligibilitate_trece"] is False
    assert d["current_step"] == 5          # pasul e neatins de poartă


# ── 5. Ce NU s-a atins + textul ──────────────────────────────

def test_poarta_nu_e_pas_in_wizsteps():
    m = re.search(r"function wizSteps\(\)\s*\{[\s\S]*?\n  \}", _HTML)
    assert "eligibil" not in m.group(0).lower(), "poarta a intrat în wizSteps — ar fi sărită la resume"


def test_poarta_e_verificata_inaintea_calculului_pasului():
    m = re.search(r"function enterWizard\(status\)\s*\{[\s\S]*?\n  \}", _HTML)
    linii = ["" if l.strip().startswith("//") else l for l in m.group(0).splitlines()]
    poarta = next(i for i, l in enumerate(linii) if "eligibilitate_trece" in l)
    calcul = next(i for i, l in enumerate(linii) if "WIZ.i =" in l or "WIZ.i=" in l)
    assert poarta < calcul, "poarta e DUPĂ calculul lui WIZ.i — resume-ul o ocolește"


def test_textul_spune_ce_e_de_ce_si_cum_revine():
    assert "Coniar" in elig.MESAJ_BLOCAT
    assert "cetățeniei" in elig.MESAJ_BLOCAT            # nu e despre identitate
    assert "greșeală" in elig.MESAJ_BLOCAT              # calea de întors
    assert "nationality" in elig.MESAJ_BLOCAT_EN
    assert "mistake" in elig.MESAJ_BLOCAT_EN
    for cheie in ("Coniar", "nationality", "mistake", "Am apăsat greșit"):
        assert cheie in _HTML, f"ecranul de blocare din UI nu conține {cheie!r}"
