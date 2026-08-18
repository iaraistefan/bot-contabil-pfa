"""
Punctul de reluare a wizardului se DERIVĂ din date, nu din indexul salvat.

De ce: `onboarding_step` e un index în ordinea de ATUNCI. Prima reordonare a
listei de pași îl face să însemne alt pas. Nu e ipotetic — pe 18 aug 2026 doi
useri reali stăteau la `onboarding_step = 1`, iar mutarea CUI-ului pe prima
poziție i-ar fi aterizat pe „regim", sărind complet peste CUI: ar fi ieșit din
wizard fără firmă.

Aici punctul de reluare se calculează din CE LIPSEȘTE (lista vine de la server,
din `_onboarding_missing` — aceeași funcție care decide și finalizarea), iar
`current_step` rămâne doar PLAFON, ca nimeni să nu fie împins peste o confirmare
pe care n-a văzut-o.

Al doilea test din fișier e cel care contează pe termen lung: reordonarea listei
NU schimbă unde aterizează un user existent. El transformă reordonarea dintr-o
operațiune riscantă într-una banală.
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

from app.models import User

_ROOT = Path(__file__).resolve().parent.parent
_HTML = (_ROOT / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")

# Ordinea de AZI și una REORDONATĂ (CUI primul) — testele rulează pe amândouă.
ORDINE_AZI = ["nume", "cui", "regim", "situatie"]
ORDINE_NOUA = ["cui", "regim", "situatie", "nume"]


def _bucata(nume_fn):
    m = re.search(r"function " + nume_fn + r"\((?:status)?\)\s*\{[\s\S]*?\n  \}", _HTML)
    assert m, f"{nume_fn} negăsit în dashboard.html"
    return m.group(0)


def _harta():
    m = re.search(r"const WIZ_STEP_PT_LIPSA=\{[^}]*\};", _HTML)
    assert m, "WIZ_STEP_PT_LIPSA negăsit"
    return m.group(0)


def _ateriza(*, lipsa, current_step, pasi, derivare=True):
    """Rulează enterWizard() REAL în node și întoarce numele pasului afișat."""
    prelude = """
      const WIZ={i:0,data:{},esc:(x)=>x};
      let ECRAN=null;
      const document={body:{classList:{add(){},remove(){}}},getElementById:()=>null};
      function wizSteps(){ return %s; }
      function wizRender(){ ECRAN=WIZ.steps[WIZ.i]; }
      function wizPoarta(){ ECRAN="poarta"; }
      function wizDone(){ ECRAN="finalizare"; }
    """ % json.dumps(pasi)
    corp = _bucata("enterWizard")
    if not derivare:
        # INJECTARE: comportamentul VECHI — indexul salvat, fără derivare.
        corp = corp.replace(
            "const derivat = wizPunctDeReluare(status);",
            "const derivat = 0;").replace(
            "WIZ.i = Math.min(derivat, plafon);",
            "WIZ.i = plafon;")
    script = (prelude + _harta() + "\n" + _bucata("wizPunctDeReluare") + "\n" + corp
              + "\nenterWizard(" + json.dumps({
                  "data": {}, "current_step": current_step, "lipsa": lipsa,
                  "eligibilitate_trece": True,
              }) + ");\nconsole.log(ECRAN);")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as f:
        f.write(script)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True)
    finally:
        Path(path).unlink(missing_ok=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node indisponibil")


# ── 1. MIEZUL: fără CUI aterizează la „cui", oricare ar fi indexul ──

@needs_node
@pytest.mark.parametrize("pasi", [ORDINE_AZI, ORDINE_NOUA])
def test_fara_cui_ateriza_la_cui(pasi):
    # userul real: pas 1 salvat, are `name` (din Telegram), n-are firmă și regim
    assert _ateriza(lipsa=["firma", "regim_impunere"], current_step=1, pasi=pasi) == "cui"


@needs_node
def test_fara_derivare_ar_sari_peste_cui():
    """Injectare: cu indexul salvat în loc de derivare, userul sare CUI-ul."""
    unde = _ateriza(lipsa=["firma", "regim_impunere"], current_step=1,
                    pasi=ORDINE_NOUA, derivare=False)
    assert unde == "regim", (
        "injectarea trebuia să reproducă bug-ul (aterizare pe indexul 1 = regim)"
    )
    assert unde != "cui"


# ── 2. Gardianul care face reordonarea banală ──

@needs_node
@pytest.mark.parametrize("lipsa,asteptat", [
    (["firma", "regim_impunere"], "cui"),
    (["regim_impunere"], "regim"),
    (["name"], "nume"),
    (["masina"], "finalizare"),   # „masina" nu e în lista de pași non-ridesharing
])
def test_reordonarea_nu_schimba_unde_ateriza(lipsa, asteptat):
    a = _ateriza(lipsa=lipsa, current_step=9, pasi=ORDINE_AZI)
    b = _ateriza(lipsa=lipsa, current_step=9, pasi=ORDINE_NOUA)
    assert a == b == asteptat, f"reordonarea a mutat aterizarea: {a} vs {b}"


# ── 3. Caz-limită: nu lipsește nimic, dar nu e finalizat ──

@needs_node
@pytest.mark.parametrize("pasi", [ORDINE_AZI, ORDINE_NOUA])
def test_nimic_lipsa_dar_nefinalizat_merge_la_finalizare(pasi):
    """Comportament DEFINIT, nu accidental: ecranul de rezumat, unde singurul
    lucru rămas e chiar apăsarea care lipsește."""
    assert _ateriza(lipsa=[], current_step=2, pasi=pasi) == "finalizare"


# ── 4. current_step e PLAFON, nu sugestie ──

@needs_node
def test_plafonul_nu_impinge_inainte():
    # date pentru pașii 0-2 completate, dar userul a ajuns doar la pasul 2:
    # derivarea ar zice „situatie" (index 2)... plafonul îl ține la 2, nu mai departe
    assert _ateriza(lipsa=["masina"], current_step=2,
                    pasi=["nume", "cui", "regim", "masina"]) == "regim"


@needs_node
def test_plafonul_nu_trage_inapoi_cand_derivarea_e_mai_devreme():
    # invers: a ajuns departe, dar îi lipsește ceva de la început → îl ducem ACOLO
    assert _ateriza(lipsa=["firma"], current_step=3, pasi=ORDINE_AZI) == "cui"


# ── 5. O singură hartă „lipsă → pas" ──

def test_harta_lipsa_pas_nu_e_scrisa_de_doua_ori():
    assert _HTML.count('{name:"nume",firma:"cui",regim_impunere:"regim",masina:"masina"}') == 1, (
        "harta lipsă→pas apare de mai multe ori — a doua copie va diverge"
    )
    assert "WIZ_STEP_PT_LIPSA[(d.missing" in _HTML, "wizComplete nu refolosește harta"


def test_serverul_trimite_lista_de_lipsuri():
    import inspect
    from app.http import app as webapp
    src = inspect.getsource(webapp.onboarding_status)
    assert '"lipsa"' in src and "_onboarding_missing" in src, (
        "statusul trebuie să deriveu lista din _onboarding_missing, nu din a doua listă"
    )


def test_lista_obligatorie_ramane_intr_un_singur_loc():
    """`_onboarding_missing` e sursa unică pentru «ce e obligatoriu»."""
    import inspect
    from app.http import app as webapp
    src = inspect.getsource(webapp)
    assert src.count("def _onboarding_missing") == 1


def test_status_expune_lipsa_pe_user_real(monkeypatch, tmp_path):
    from app.http import app as webapp
    eng = create_engine(f"sqlite:///{(tmp_path / 'rel.db').as_posix()}")
    User.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    s = S()
    # exact profilul celor doi useri reali: nume din Telegram, restul gol
    s.add(User(telegram_id=1, name="Wn rain", onboarding_step=1,
               onboarding_completed=False, eligibilitate_pfa="DA"))
    s.commit()
    uid = s.query(User).one().id
    s.close()
    monkeypatch.setattr(webapp, "_require_user", lambda: (uid, None))
    monkeypatch.setattr(webapp, "get_session", lambda: S())
    d = webapp.flask_app.test_client().get("/api/v1/onboarding/status").get_json()
    assert "name" not in d["lipsa"]            # numele din Telegram trece drept completat
    assert "firma" in d["lipsa"]
    assert d["current_step"] == 1              # plafonul, neatins
