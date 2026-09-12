"""
Gardian: formele juridice din wizardul web sunt sincronizate cu Python-ul.

DOUĂ LISTE, DOUĂ ROLURI — distincția pe care gardianul ăsta o apără:

  TAXONOMIE  `FormaJuridica` (enum) ↔ `WIZ_FORMA_LBL` (JS)
             Tot ce EXISTĂ ca formă juridică, inclusiv ce nu servim. E folosită
             ca dicționar de etichete: `WIZ.formaLabel(cod)` traduce orice cod
             care poate ajunge pe ecran — inclusiv un SRL detectat de ANAF, pe
             care îl NUMIM tocmai ca să-i spunem userului de ce ne oprim. Dacă
             taxonomia ar fi ciuntită, acolo ar apărea „SRL_MICRO" brut.

  OFERTĂ     `forma_servita.FORME_SELECTABILE` ↔ `WIZ_FORME_SELECTABILE` (JS)
             Ce se poate ALEGE. Umple `<select>`-ul din wizard și butoanele din
             bot (`onboarding.FORME_JURIDICE`). Submulțime a taxonomiei.

Până la PR-ul ăsta cele două erau UN SINGUR obiect JS: `WIZ_FORMA_LBL` servea și
ca dicționar de etichete, și — prin `Object.keys(...)` — ca listă de opțiuni în
`<select>`. Confuzia era în cod, nu doar în capul nostru: nu se putea eticheta o
formă fără a o și OFERI. Gardianul vechi cerea „fiecare valoare de enum apare în
UI", ceea ce era corect pentru etichete și greșit pentru opțiuni — și ar fi
blocat retragerea SRL-ului din ofertă cerând să-l ținem în dropdown.

Ce verifică acum, în ambele direcții:
  1. orice formă din taxonomie are ETICHETĂ în JS (altfel apare codul brut);
  2. nicio etichetă orfană (cod în JS inexistent în enum = typo sau cod mort);
  3. oferta web == oferta Python, exact (nici lipsă, nici în plus);
  4. oferta bot == oferta Python, exact;
  5. oferta ⊆ taxonomie.

Testele de INJECTARE de la final verifică gardianul însuși: mutez HTML-ul ca să
scot o formă selectabilă din ofertă, și cer să pice. Un gardian care nu e văzut
picând e doar un test verde.

Tehnica (citit dashboard.html ca text) e cea deja folosită în repo — suita nu
execută JS-ul din template, deci verificarea se face pe textul lui. Funcțiile de
parsare iau HTML-ul ca PARAMETRU, nu din global, tocmai ca injectarea să fie
posibilă fără să atingă fișierul de pe disc.
"""

import re
from pathlib import Path

import pytest

from app.domain.fiscal_profile import FormaJuridica
from app.domain.forma_servita import CODURI_SELECTABILE, FORME_SELECTABILE
from app.services.onboarding import FORME_JURIDICE

_HTML = (Path(__file__).resolve().parent.parent
         / "app" / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")


def _wiz_forma_coduri(html: str) -> set:
    """Cheile din obiectul JS WIZ_FORMA_LBL (taxonomia de etichete)."""
    m = re.search(r"const\s+WIZ_FORMA_LBL\s*=\s*\{([\s\S]*?)\}\s*;", html)
    assert m, "WIZ_FORMA_LBL negăsit în dashboard.html"
    # scoatem valorile (string-uri) ca virgulele/`:`-urile din ele să nu treacă drept chei
    corp = re.sub(r'"[^"]*"|\'[^\']*\'', '""', m.group(1))
    return {k for k in re.findall(r"(?:^|,)\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", corp)}


def _wiz_forme_selectabile(html: str) -> list:
    """Codurile din tabloul JS WIZ_FORME_SELECTABILE (oferta), în ordinea din UI."""
    m = re.search(r"const\s+WIZ_FORME_SELECTABILE\s*=\s*\[([\s\S]*?)\]\s*;", html)
    assert m, "WIZ_FORME_SELECTABILE negăsit în dashboard.html"
    return re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', m.group(1))


# ══════════════════════════════════════════════════════════════
#  TAXONOMIE — etichete pentru tot ce poate ajunge pe ecran
# ══════════════════════════════════════════════════════════════

def test_orice_forma_din_taxonomie_are_eticheta():
    """Inclusiv formele NEservite: le arătăm pe nume când explicăm de ce ne oprim."""
    coduri_js = _wiz_forma_coduri(_HTML)
    for forma in FormaJuridica:
        assert forma.value in coduri_js, (
            f"forma {forma.value} există în enum-ul FormaJuridica dar lipsește "
            f"din WIZ_FORMA_LBL din dashboard.html → wizardul ar afișa codul brut. "
            f"Etichetă ≠ ofertă: adaug-o aici chiar dacă forma nu e selectabilă."
        )


def test_nicio_eticheta_orfana_in_dashboard():
    # reversul: o cheie în JS care nu există în enum = cod mort sau typo
    coduri_enum = {f.value for f in FormaJuridica}
    orfane = _wiz_forma_coduri(_HTML) - coduri_enum
    assert not orfane, (
        f"WIZ_FORMA_LBL din dashboard.html conține coduri inexistente în enum-ul "
        f"FormaJuridica: {sorted(orfane)}"
    )


# ══════════════════════════════════════════════════════════════
#  OFERTĂ — ce se poate alege, identic pe toate suprafețele
# ══════════════════════════════════════════════════════════════

def _asserta_oferta_web(html: str):
    """Asertiunea gardianului, extrasă ca s-o pot INJECTA (vezi finalul)."""
    coduri_js = set(_wiz_forme_selectabile(html))
    lipsa = CODURI_SELECTABILE - coduri_js
    assert not lipsa, (
        f"forme SELECTABILE lipsă din WIZ_FORME_SELECTABILE (dashboard.html): "
        f"{sorted(lipsa)} — le servim, dar userul web nu le poate alege"
    )
    in_plus = coduri_js - CODURI_SELECTABILE
    assert not in_plus, (
        f"WIZ_FORME_SELECTABILE oferă forme pe care nu le servim: {sorted(in_plus)} "
        f"— oferta e forma_servita.FORME_SELECTABILE, nu tot enum-ul"
    )


def test_oferta_web_e_exact_oferta_python():
    _asserta_oferta_web(_HTML)


def test_oferta_bot_e_exact_oferta_python():
    """Butoanele din bot și `<select>`-ul din web oferă ACELAȘI lucru."""
    coduri_bot = {f["code"] for f in FORME_JURIDICE}
    assert coduri_bot == CODURI_SELECTABILE, (
        f"onboarding.FORME_JURIDICE (bot) = {sorted(coduri_bot)} dar oferta e "
        f"{sorted(CODURI_SELECTABILE)} — botul și web-ul ar oferi lucruri diferite"
    )


def test_oferta_e_submultime_a_taxonomiei():
    assert FORME_SELECTABILE <= set(FormaJuridica), (
        "FORME_SELECTABILE conține o formă care nu există în taxonomie"
    )


def test_dropdownul_web_e_construit_din_oferta_nu_din_etichete():
    """Regresia structurală: `<select>`-ul nu are voie să se umple din taxonomie.

    Dacă cineva întoarce dropdown-ul la `Object.keys(WIZ_FORMA_LBL)`, cele două
    liste redevin una singură și SRL-ul reapare în ofertă fără ca vreun test de
    mulțimi să observe — fiindcă atunci taxonomia ȘI oferta ar fi iar egale.
    """
    assert "WIZ_FORME_SELECTABILE.map(" in _HTML, (
        "dropdown-ul de formă juridică nu se mai construiește din "
        "WIZ_FORME_SELECTABILE — verifică dashboard.html"
    )
    assert "Object.keys(WIZ_FORMA_LBL)" not in _HTML, (
        "dropdown-ul s-a întors la Object.keys(WIZ_FORMA_LBL): taxonomia a "
        "redevenit ofertă, iar formele neservite sunt din nou selectabile"
    )


# ══════════════════════════════════════════════════════════════
#  INJECTARE — gardianul e văzut PICÂND, nu doar trecând
# ══════════════════════════════════════════════════════════════

def _fara_din_oferta_js(html: str, cod: str) -> str:
    """HTML mutat: `cod` scos din tabloul WIZ_FORME_SELECTABILE."""
    m = re.search(r"(const\s+WIZ_FORME_SELECTABILE\s*=\s*\[)([\s\S]*?)(\]\s*;)", html)
    assert m, "WIZ_FORME_SELECTABILE negăsit — nu pot injecta"
    corp_ciuntit = re.sub(rf'"{cod}"\s*,?\s*', "", m.group(2))
    assert corp_ciuntit != m.group(2), f"injectarea n-a schimbat nimic pentru {cod}"
    return html[:m.start()] + m.group(1) + corp_ciuntit + m.group(3) + html[m.end():]


def _cu_plus_in_oferta_js(html: str, cod: str) -> str:
    """HTML mutat: `cod` ADĂUGAT în tabloul WIZ_FORME_SELECTABILE."""
    m = re.search(r"(const\s+WIZ_FORME_SELECTABILE\s*=\s*\[)", html)
    assert m, "WIZ_FORME_SELECTABILE negăsit — nu pot injecta"
    return html[:m.end()] + f'"{cod}",' + html[m.end():]


@pytest.mark.parametrize("cod", sorted(CODURI_SELECTABILE))
def test_injectare_forma_selectabila_lipsa_din_ui_face_gardianul_sa_pice(cod):
    """Scot pe rând fiecare formă servită din UI și cer gardianului s-o prindă."""
    html_ciuntit = _fara_din_oferta_js(_HTML, cod)
    with pytest.raises(AssertionError, match=cod):
        _asserta_oferta_web(html_ciuntit)


def test_injectare_forma_neservita_adaugata_in_ui_face_gardianul_sa_pice():
    """Direcția inversă: cineva pune la loc SRL-ul în dropdown → gardianul pică."""
    html_umflat = _cu_plus_in_oferta_js(_HTML, "SRL_MICRO")
    with pytest.raises(AssertionError, match="SRL_MICRO"):
        _asserta_oferta_web(html_umflat)


def test_injectarea_nu_a_atins_fisierul_real():
    """Contra-probă: mutațiile de mai sus au fost pe copii, nu pe disc."""
    _asserta_oferta_web(_HTML)
