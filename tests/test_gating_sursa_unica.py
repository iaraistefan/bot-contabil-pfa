"""
GARDIAN — harta feature→tier e SINGURA sursă de adevăr pentru porți.

De ce există fișierul ăsta: D212 a fost livrat cu poarta greșită (PRO în loc de
START) fiindcă `execute_declaratie_d212` și-a declarat tier-ul singură, copiind
`feature="declaratii"` de la fratele lunar. Harta spunea START, codul cerea PRO,
și nimeni n-a observat pentru că erau două surse de adevăr care nu se ating.

Gardianul de mai jos face imposibilă a doua sursă: niciun call-site de gating nu
are voie să numească un tier literal. Toate trec prin `feature_tier(...)`.

Se verifică prin AST, nu prin regex — apelurile de gating se întind pe mai multe
rânduri, iar un regex pe linie le-ar rata exact pe cele mai lungi.
"""

import ast
from pathlib import Path

import pytest

from app.services import gating
from app.services import subscription as sub

RADACINA = Path(__file__).resolve().parents[1]

# Funcțiile prin care se trece o poartă. Oricare dintre ele primește un tier.
APELURI_DE_POARTA = {
    "has_feature", "user_has_feature", "require_tier_bot",
    "_require_tier", "has_tier_at_least",
}

# Numele tier-urilor, ca literal. `sub.PRO`, `subscription.PRO`, `_sub.PRO`,
# `PRO` sau chiar "PRO" — toate sunt aceeași greșeală.
TIERE = {"FREE", "START", "PRO", "MAX"}

# gating.py și subscription.py DEFINESC tier-urile — acolo literalele sunt corecte.
SCUTITE = {
    RADACINA / "app" / "services" / "gating.py",
    RADACINA / "app" / "services" / "subscription.py",
}


def _fisiere_productie():
    fisiere = [p for p in (RADACINA / "app").rglob("*.py") if p not in SCUTITE]
    fisiere.append(RADACINA / "bot_contabil.py")
    return sorted(fisiere)


def _e_tier_literal(nod) -> bool:
    """Nodul e un tier numit direct, în loc de un apel la feature_tier?"""
    if isinstance(nod, ast.Attribute) and nod.attr in TIERE:
        return True                                  # sub.PRO / subscription.PRO
    if isinstance(nod, ast.Name) and nod.id in TIERE:
        return True                                  # PRO importat direct
    if isinstance(nod, ast.Constant) and nod.value in TIERE:
        return True                                  # "PRO"
    return False


def _nume_apel(nod: ast.Call) -> str:
    f = nod.func
    if isinstance(f, ast.Attribute):
        return f.attr                                # gating.has_feature
    if isinstance(f, ast.Name):
        return f.id                                  # _require_tier
    return ""


def _afisaj(cale: Path) -> str:
    """Cale relativă la repo când se poate; altfel numele (fișierele de injectare
    din tmp_path sunt în afara repo-ului)."""
    try:
        return str(cale.relative_to(RADACINA))
    except ValueError:
        return cale.name


def _incalcari(cale: Path):
    # utf-8-sig: un BOM lăsat de un editor Windows ar face `ast.parse` să crape,
    # iar gardianul ar raporta o eroare de sintaxă în loc de constatarea reală.
    arbore = ast.parse(cale.read_text(encoding="utf-8-sig"), filename=str(cale))
    for nod in ast.walk(arbore):
        if not isinstance(nod, ast.Call):
            continue
        if _nume_apel(nod) not in APELURI_DE_POARTA:
            continue
        argumente = list(nod.args) + [k.value for k in nod.keywords]
        for arg in argumente:
            if _e_tier_literal(arg):
                yield (f"{_afisaj(cale)}:{nod.lineno}: "
                       f"{_nume_apel(nod)}(...) primeste un tier literal "
                       f"— foloseste gating.feature_tier(<feature>)")


def test_niciun_callsite_de_gating_nu_numeste_un_tier_literal():
    gasite = [x for cale in _fisiere_productie() for x in _incalcari(cale)]
    assert gasite == [], (
        "a aparut a doua sursa de adevar pentru tier-uri:\n" + "\n".join(gasite))


def test_gardianul_chiar_prinde_o_incalcare(tmp_path):
    """Un gardian care nu poate esua nu e gardian. Injectam ce paziim."""
    momeala = tmp_path / "momeala.py"
    momeala.write_text(
        "import app.services.subscription as sub\n"
        "def f(session, user_id):\n"
        "    return gating.has_feature(\n"
        "        session, user_id, sub.PRO)\n",   # apel pe MAI MULTE randuri
        encoding="utf-8",
    )
    gasite = list(_incalcari(momeala))
    assert len(gasite) == 1, gasite
    assert "tier literal" in gasite[0]


@pytest.mark.parametrize("forma", [
    'gating.has_feature(s, u, sub.PRO)',
    'gating.has_feature(s, u, subscription.MAX)',
    'gating.has_feature(s, u, "PRO")',
    'gating.has_feature(s, u, min_tier=sub.START)',
    '_require_tier(u, _sub.PRO, feature="x")',
])
def test_gardianul_prinde_toate_formele(tmp_path, forma):
    f = tmp_path / "f.py"
    f.write_text(f"def g(s, u):\n    return {forma}\n", encoding="utf-8")
    assert list(_incalcari(f)), f"nu a prins: {forma}"


def test_gardianul_nu_da_fals_pozitiv_pe_forma_corecta(tmp_path):
    f = tmp_path / "f.py"
    f.write_text(
        "def g(s, u):\n"
        "    return gating.has_feature(s, u, gating.feature_tier('declaratii'))\n",
        encoding="utf-8",
    )
    assert list(_incalcari(f)) == []


# ════════════════════════════════════════════════════════════
#   HARTA — ce vinde fiecare plan
# ════════════════════════════════════════════════════════════

def test_d212_fisier_e_din_start_nu_din_pro():
    """Decizia de produs, prinsă în test: START vinde declarația ANUALĂ gata de
    depus. Dacă cineva o mută înapoi pe PRO, START redevine nevandabil față de
    FREE și testul ăsta spune de ce."""
    assert gating.feature_tier("d212_fisier") == sub.START
    assert gating.feature_tier("d212_estimare") == sub.START
    assert gating.feature_tier("declaratii") == sub.PRO


def test_estimarea_si_fisierul_sunt_doua_feature_uri_distincte():
    assert "d212" not in gating.FEATURES, "intrarea unica a fost re-introdusa"
    est = gating.FEATURES["d212_estimare"]
    fis = gating.FEATURES["d212_fisier"]
    assert est["label"] != fis["label"]
    assert est["beneficiu"] != fis["beneficiu"]
    # Fișierul vorbește despre fișier, estimarea despre calcul — altfel un user
    # care cere XML-ul citește despre estimare.
    assert "XML" in fis["beneficiu"]
    assert "XML" not in est["beneficiu"]


def test_namespace_urile_trimit_la_feature_ul_potrivit():
    assert gating.NAMESPACE_FEATURE["d212"] == "d212_fisier"
    assert gating.NAMESPACE_FEATURE["du"] == "d212_estimare"
    for ns in ("d301", "d390", "d100", "d207"):
        assert gating.NAMESPACE_FEATURE[ns] == "declaratii"


# ════════════════════════════════════════════════════════════
#   MESAJUL DE UPSELL — derivat, nu literal
# ════════════════════════════════════════════════════════════

def test_eticheta_enumera_declaratiile_derivate_din_harta():
    assert gating.coduri_declaratii("declaratii") == ["D100", "D207", "D301", "D390"]
    assert gating.coduri_declaratii("d212_fisier") == ["D212"]
    # `du` NU e cod de declarație — nu are voie să intre în enumerare
    assert gating.coduri_declaratii("d212_estimare") == []


def test_enumerarea_se_muta_singura_cand_harta_se_schimba(monkeypatch):
    """Proba că e derivare, nu coincidență: mut D390 pe altă poartă și enumerarea
    din mesaj trebuie să se schimbe fără să ating vreun șir de text."""
    harta = dict(gating.NAMESPACE_FEATURE)
    harta["d390"] = "d212_fisier"
    monkeypatch.setattr(gating, "NAMESPACE_FEATURE", harta)
    assert gating.coduri_declaratii("declaratii") == ["D100", "D207", "D301"]
    assert gating.coduri_declaratii("d212_fisier") == ["D212", "D390"]


def test_upsell_pentru_d212_vorbeste_despre_d212_nu_despre_d301():
    """Bug-ul raportat de user: a cerut D212 și a citit despre D301/D390/D100/D207."""
    text = gating.upgrade_text("d212_fisier")
    assert "D212" in text
    for altul in ("D301", "D390", "D100", "D207"):
        assert altul not in text, f"mesajul pentru D212 pomeneste {altul}"
    assert sub.START in text and sub.PRO not in text


def test_upsell_pentru_declaratii_lunare_le_enumera_pe_toate_patru():
    text = gating.upgrade_text("declaratii")
    for cod in ("D301", "D390", "D100", "D207"):
        assert cod in text
    assert "D212" not in text, "D212 nu mai e pe poarta asta"
    assert sub.PRO in text


def test_niciun_label_din_harta_nu_mai_enumera_coduri_literal():
    """Enumerarea trebuie să vină din derivare. Un cod scris de mână în `label` ar
    fi exact șirul care a rămas în urmă data trecută."""
    for nume, f in gating.FEATURES.items():
        for cod in ("D100", "D207", "D212", "D300", "D301", "D390"):
            assert cod not in f["label"], f"FEATURES[{nume!r}].label enumera {cod}"
