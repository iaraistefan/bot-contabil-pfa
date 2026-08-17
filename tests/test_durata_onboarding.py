"""
GARDIAN: nicăieri în produs nu promitem că onboarding-ul durează un minut.

Adevărul, măsurat în `wizSteps()` (dashboard.html): 4 pași pentru un non-șofer,
dar 7 pentru șofer (+mașină, +platforme, +nerezident) și 8 dacă alege Bolt
(+apibolt), plus ecranul de finalizare care cere și data certificatului. Șoferul
de Bolt/Uber e chiar publicul-țintă, deci cazul lung e cazul normal.

DE CE E PE TOT REPO-UL. Prima versiune a gardianului (PR #142) apăra UN SINGUR
mesaj — cel al porții de ingestie. Între timp fraza trăia în încă două locuri
(`/start` și fallback-ul din chat), pe care nu le atingea. Un gardian care apără
o instanță dintr-o clasă de afirmații e mai rău decât niciunul: lasă impresia că
problema e rezolvată. Vezi §3.2 — „apără instanța, nu clasa" + granularitatea.

LISTA E DERIVATĂ, nu scrisă de mână: variantele se obțin ca produs cartezian
între cuantificatori și unitate, în ambele limbi (vezi `_variante()`). Ce NU se
poate deriva e *contextul* — și de aceea există al doilea filtru, explicat mai jos.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

# Cod de productie + template-uri. Testele si docs sunt excluse deliberat:
# acolo fraza APARE legitim, ca sa explice de ce e interzisa.
_FISIERE = (
    [_ROOT / "bot_contabil.py"]
    + sorted((_ROOT / "app").rglob("*.py"))
    + sorted((_ROOT / "app").rglob("*.html"))
)

# ── lista DERIVATA: cuantificator × unitate ──────────────────
_CUANTIFICATORI_RO = ["sub", "în", "in", "într", "intr", "doar", "numai", "cam"]
_CUANTIFICATORI_EN = ["under", "in", "within", "less than", "about", "takes",
                      "take", "only", "just"]
_UNITATE_EN = ["a minute", "one minute", "1 minute"]


def _variante():
    """Produsul cartezian cuantificator × unitate, ca fragmente de tipar.

    Separatorul e `[\\s-]+`, nu spațiu: româna contractă („într-un minut"), deci
    o listă de șiruri lipite cu spațiu ar rata exact varianta cea mai firească.
    """
    ro = [rf"\b{re.escape(c)}[\s-]+un\s+minut" for c in _CUANTIFICATORI_RO]
    en = [rf"\b{re.escape(c)}\s+{re.escape(u)}"
          for c in _CUANTIFICATORI_EN for u in _UNITATE_EN]
    return ro + en + [r"\b60\s+de\s+secunde", r"\b60\s+seconds"]


_TIPAR = re.compile("|".join(_variante()), re.IGNORECASE)

# ── al doilea filtru: CONTEXTUL ──────────────────────────────
# „Bolt a limitat cererile (prea multe într-un minut)" e adevarat si trebuie sa
# treaca. Fraza singura nu distinge intre o promisiune de durata si o descriere
# de rate-limit — doar vecinatatea o face. De aceea cuvintele de context sunt
# LITERALE: sunt vocabularul configurarii, nu variante ale aceleiasi expresii,
# deci n-au din ce sa fie derivate.
_CONTEXT_CONFIGURARE = [
    "configur", "onboard", "setup", "set up", "profil", "profile",
]
_FEREASTRA = 8      # linii in jurul potrivirii


def _incalcari():
    gasite = []
    for f in _FISIERE:
        linii = f.read_text(encoding="utf-8").splitlines()
        for i, linie in enumerate(linii):
            if not _TIPAR.search(linie):
                continue
            jur = "\n".join(linii[max(0, i - _FEREASTRA): i + _FEREASTRA + 1]).lower()
            if any(k in jur for k in _CONTEXT_CONFIGURARE):
                gasite.append((f.relative_to(_ROOT).as_posix(), i + 1, linie.strip()))
    return gasite


def test_nicaieri_nu_promitem_un_minut_de_configurare():
    incalcari = _incalcari()
    assert not incalcari, (
        "Promisiune de durată neadevărată pentru onboarding "
        f"({len(incalcari)}):\n"
        + "\n".join(f"  {f}:{n} → {l}" for f, n, l in incalcari)
        + "\n\nAdevărul: 4 pași pentru non-șofer, 7-8 pentru șofer (wizSteps()). "
          "Formula folosită în produs: „câțiva pași, două-trei minute”."
    )


# ── gardianul gardianului ────────────────────────────────────

def test_tiparul_prinde_variantele_asteptate():
    """Dacă produsul cartezian se strică, testul de mai sus trece degeaba."""
    for exemplu in ["sub un minut", "într-un minut", "intr-un minut",
                    "under a minute", "takes a minute", "in one minute",
                    "less than 1 minute", "60 de secunde"]:
        assert _TIPAR.search(exemplu), f"tiparul nu prinde {exemplu!r}"


def test_tiparul_nu_prinde_formularea_corecta():
    for ok in ["câțiva pași, două-trei minute", "a few minutes",
               "Așteaptă ~1-2 minute", "peste câteva minute"]:
        assert not _TIPAR.search(ok), f"fals pozitiv pe {ok!r}"


def test_rate_limit_bolt_nu_e_fals_pozitiv():
    """„prea multe într-un minut" e adevărat — trece prin filtrul de context."""
    bolt = (_ROOT / "app" / "integrations" / "bolt_sync.py").read_text(encoding="utf-8")
    assert "într-un minut" in bolt              # fraza chiar e acolo
    assert not [x for x in _incalcari() if "bolt_sync" in x[0]]


def test_scanarea_acopera_si_template_urile():
    cai = {f.as_posix() for f in _FISIERE}
    assert any(c.endswith("dashboard.html") for c in cai)
    assert any(c.endswith("bot_contabil.py") for c in cai)
    assert any(c.endswith("services/onboarding.py") for c in cai)
    assert len(_FISIERE) > 20                   # chiar scaneaza repo-ul, nu 3 fisiere
