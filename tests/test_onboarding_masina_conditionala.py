"""
Mașina condiționată de ridesharing (audit #5 / I2).

Pe web, mașina era obligatorie NECONDIȚIONAT la finalizarea onboarding-ului → un PFA
non-șofer (IT/medical/trader) NU putea termina fără să înregistreze un vehicul (blocaj
real), deși în Telegram mașina e opțională pentru toți.

Fix: mașina e cerută DOAR pentru ridesharing (backend `_onboarding_missing` + frontend
`wizSteps()`). Șoferul rămâne neatins (deductibilitatea auto e esențială pentru el);
non-șoferul e deblocat. Web ≡ Telegram.
"""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.http import app as webapp

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


# ── Backend: gate-ul _onboarding_missing ─────────────────────

def _profil(activity_code):
    p = {"name": "x", "firma_cui": "1", "regim_impunere": "NORMA_VENIT"}
    if activity_code is not None:
        p["activity_code"] = activity_code
    return p


def test_sofer_fara_vehicul_cere_masina():
    # ridesharing fără vehicul → „masina" în missing (comportament PĂSTRAT)
    assert "masina" in webapp._onboarding_missing(_profil("ridesharing"), has_vehicul=False)


def test_nonsofer_fara_vehicul_nu_cere_masina():
    # non-ridesharing fără vehicul → „masina" NU în missing (DEBLOCAT)
    assert "masina" not in webapp._onboarding_missing(_profil("it_freelance"), has_vehicul=False)


def test_activity_code_lipsa_tratata_ca_nonsofer():
    # neclasificat (None) → nu blochează pe mașină
    assert "masina" not in webapp._onboarding_missing(_profil(None), has_vehicul=False)


def test_sofer_cu_vehicul_nu_mai_cere_masina():
    assert "masina" not in webapp._onboarding_missing(_profil("ridesharing"), has_vehicul=True)


# ── Frontend: wizSteps() — comportamental, rulat prin node ───

def _wizsteps_via_node(is_ridesharing, has_bolt=False):
    m = re.search(r"function wizSteps\(\)\s*\{[\s\S]*?\n  \}", _HTML)
    assert m, "wizSteps() negăsit în dashboard.html"
    rs = "true" if is_ridesharing else "false"
    pf = '"BOLT"' if has_bolt else "null"
    prelude = (
        "const WIZ={data:{is_ridesharing:" + rs + ",_platforme:" + pf + "}};\n"
        "function wizHasBolt(){return WIZ.data._platforme==='BOLT'||WIZ.data._platforme==='AMBELE';}\n"
    )
    script = prelude + m.group(0) + "\nconsole.log(JSON.stringify(wizSteps()));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_wizsteps_nonsofer_fara_masina():
    pasi = _wizsteps_via_node(is_ridesharing=False)
    assert "masina" not in pasi                       # non-șofer → pasul mașină NU apare
    assert pasi == ["nume", "cui", "regim", "situatie"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")
def test_wizsteps_sofer_cu_masina():
    pasi = _wizsteps_via_node(is_ridesharing=True, has_bolt=True)
    assert "masina" in pasi                            # șofer → pasul mașină apare
    assert "platforme" in pasi and "nerezident" in pasi
    assert "apibolt" in pasi                           # Bolt selectat → pas conectare
