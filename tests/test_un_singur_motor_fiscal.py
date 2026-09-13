"""
GARDIAN: un singur motor pentru o singură întrebare fiscală.

De ce există
------------
D212 a avut DOUĂ motoare care răspundeau la aceeași întrebare: `du_calc`
(`app/domain/declaratie_unica.py`) pe drumul din meniu, și `compute_d212_anual`
pe drumul cu fișier. Nu divergeau în matematică, ci în SURSA RĂSPUNSULUI: unul
întreba userul despre asigurare și îi arunca răspunsul, celălalt îl citea din profil.
Pe date reale de producție, 2.430 lei față de 174,56 lei pe linia CASS — de 7,3 ori,
pe același om, în aceeași zi.

Cum prinde CLASA, nu instanța
-----------------------------
Nu caută cuvântul „du_calc" nicăieri. Un al doilea motor poate apărea sub orice nume.
Semnalul e STRUCTURAL: orice motor fiscal care produce CAS și CASS trebuie să treacă
prin primitivele din `app.domain.contributii` — ele sunt sursa unică a matematicii
contribuțiilor, iar un calcul care NU trece pe acolo ar fi o a treia problemă, nu a
doua.

Deci gardianul îngheață LISTA MODULELOR care cheamă primitivele. Un modul nou care
le cheamă = un motor nou = testul cade, oricum s-ar numi. Un modul nou care NU le
cheamă dar calculează contribuții pe cont propriu ar fi prins de gardianul de
constante fiscale, care e altă poveste.

A doua verificare, pe SUPRAFEȚE: un ecran care arată userului o cifră D212 trebuie
s-o ia din motorul canonic. Suprafețele n-au voie să importe alt calculator.

Ce NU verifică
--------------
Că cele două motoare dau aceleași cifre. Nu poate: calea manuală există tocmai
pentru cifre care nu-s în DB, deci n-are cu ce compara. Gardianul apără UNICITATEA,
nu egalitatea — iar unicitatea e ce lipsea.
"""

import re
from pathlib import Path

RADACINA = Path(__file__).resolve().parents[1]
APP = RADACINA / "app"
BOT = RADACINA / "bot_contabil.py"

# Primitivele de contribuții — sursa unică a matematicii CAS/CASS.
_APEL_PRIMITIVA = re.compile(r"\bcontributii\.calcul_ca(?:s|ss)\s*\(")

# ── LISTA ÎNGHEȚATĂ a modulelor care au voie să cheme primitivele ──
#
# Măsurată la 13.09.2026, nu presupusă. Fiecare are un motiv scris; un modul NOU
# care cheamă primitivele = un motor nou și testul cade.
#
# ⚠️ Lista poate DOAR SĂ SCADĂ. Dacă adaugi ceva aici, adaugi un al doilea răspuns
# la o întrebare care are deja unul — exact bug-ul pe care gardianul îl păzește.
MOTOARE_PERMISE = {
    # CANONIC: motorul D212 anual. Tot ce e user-facing trebuie să ajungă aici.
    "d212_calc.py",
    # Estimarea LUNARĂ (altă întrebare: „cât strâng luna asta", nu „cât datorez pe an").
    # Consumat exclusiv prin tax_engine; nu e o a doua cale spre D212.
    "tax_calculator.py",
    # Explicativ: `app.py` re-derivă NOTELE și pragurile pentru hero-ul web, dar
    # cifrele afișate vin din `compute_d212_anual` (r.cas / r.cass / r.impozit).
    # ⚠️ Cheamă primitivele FĂRĂ flagurile de profil, deci notele pot descrie alt caz
    # decât cifrele pentru un salariat peste prag. Cunoscut, nefixat aici.
    "app.py",
    # TEMPORAR — calea MANUALĂ din bot. Singurul rest al motorului vechi.
    # `compute_d212_anual` citește din DB și nu acceptă cifre injectate, deci calea
    # manuală nu se putea muta, trebuie construită. Vezi `_finalizeaza_calcul` în
    # `declaratie_unica_ui.py` pentru ce anume ar cere.
    # CÂND se construiește injectarea, fișierul ăsta iese din listă.
    "declaratie_unica.py",
}

# Suprafețele care arată cifre userului. Ele n-au voie să calculeze — doar să ceară.
SUPRAFETE = ("bot_contabil.py", "declaratie_unica_ui.py", "plata_fiscala.py",
             "ghid_ui.py", "proactive_alerts.py", "scheduler.py")


def _fisiere_py():
    for p in APP.rglob("*.py"):
        if "__pycache__" not in p.parts:
            yield p
    if BOT.exists():
        yield BOT


def test_doar_motoarele_permise_cheama_primitivele_de_contributii():
    """
    CLASA: un al doilea motor fiscal, sub orice nume, cade aici.
    """
    vinovati = []
    for p in _fisiere_py():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in _APEL_PRIMITIVA.finditer(txt):
            if p.name in MOTOARE_PERMISE:
                continue
            nr = txt[:m.start()].count("\n") + 1
            vinovati.append(f"{p.relative_to(RADACINA)}:{nr}")

    assert not vinovati, (
        "Module care calculează CAS/CASS pe cont propriu, în afara listei:\n  "
        + "\n  ".join(vinovati)
        + "\n\nUn al doilea motor care răspunde la aceeași întrebare fiscală e "
        "exact bug-ul pe care gardianul îl păzește: D212 a avut două, iar ele "
        "dădeau 2.430 lei și 174,56 lei pentru același om.\n"
        "Dacă ai nevoie de cifrele CAS/CASS, cere-le motorului "
        "(`tax_engine.compute_d212_anual`), nu le recalcula."
    )


def test_lista_inghetata_nu_ramane_in_urma():
    """Un modul care nu mai cheamă primitivele trebuie scos din listă."""
    cheama = set()
    for p in _fisiere_py():
        if _APEL_PRIMITIVA.search(p.read_text(encoding="utf-8", errors="ignore")):
            cheama.add(p.name)
    fantome = MOTOARE_PERMISE - cheama
    assert not fantome, (
        f"Module în MOTOARE_PERMISE care NU mai cheamă primitivele: {sorted(fantome)}.\n"
        "Scoate-le — lista poate doar să scadă, altfel devine o ficțiune."
    )


def test_calea_automata_foloseste_motorul_canonic():
    """
    Instanța reparată, ancorată pe text: ecranul D212 din meniu trebuie să ceară
    cifrele de la `compute_d212_anual`. Gardianul de clasă de mai sus n-ar prinde
    asta singur — un UI care cheamă un motor greșit nu atinge primitivele.
    """
    txt = (APP / "services" / "declaratie_unica_ui.py").read_text(encoding="utf-8")
    assert "compute_d212_anual" in txt, (
        "calea automată nu mai cere cifrele motorului canonic"
    )
    # Calea manuală are voie să folosească `du_calc`, dar DOAR ea: dacă apare și pe
    # calea automată, cele două răspunsuri se despart din nou.
    pozitie_auto = txt.find("_finalizeaza_automat")
    assert pozitie_auto > 0
    corp_auto = txt[pozitie_auto:txt.find("async def _finalizeaza_calcul")]
    assert "du_calc" not in corp_auto, (
        "calea AUTOMATĂ a redevenit dependentă de motorul vechi (`du_calc`)"
    )


def test_suprafetele_nu_calculeaza_singure():
    """
    Suprafețele (bot, ecrane, alerte, scheduler) cer cifre, nu le produc.
    Redundant cu primul test azi — dar el apără PRIMITIVELE, ăsta apără STRATUL.
    Dacă mâine apare un calcul care ocolește primitivele, stratul rămâne păzit.
    """
    vinovati = []
    for p in _fisiere_py():
        if p.name not in SUPRAFETE:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in _APEL_PRIMITIVA.finditer(txt):
            nr = txt[:m.start()].count("\n") + 1
            vinovati.append(f"{p.relative_to(RADACINA)}:{nr}")
    assert not vinovati, (
        "Suprafețe care calculează contribuții în loc să le ceară:\n  "
        + "\n  ".join(vinovati)
    )
