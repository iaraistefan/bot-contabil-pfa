"""
GARDIANUL F2 — temeiul datat pentru proza fiscală nouă.

Trei verificări ÎNGUSTE, pe o suprafață identificabilă STRUCTURAL:

  1. STRUCTURAL  — fiecare definiție din `DEFINITII_OBLIGATII` poartă un bloc de temei
                   (excepțiile sunt lista înghețată, care poate doar să scadă);
  2. FORMA       — temeiurile existente au cele cinci elemente, cu NEGĂSIT ca stare
                   VALIDĂ, nu ca eșec;
  3. PROSPEȚIMEA — pe data VERIFICĂRII, nu pe cea a consolidării.

CE NU FACE, ȘI DE CE
────────────────────
Nu detectează „proză fiscală" nicăieri. Întrebarea nu e decidabilă mecanic, iar un
clasificator pe cuvinte-cheie ar produce fals-pozitive — care nu sunt un deranj, ci
MECANISMUL PRIN CARE MOARE UN GARDIAN: se umple allowlist-ul, apoi nu mai păzește
nimic. Așa că se uită la 8 definiții cu graniță sintactică limpede, care acoperă 37
din cele 96 de afirmații ale inventarului.

Nu verifică nici dacă temeiul e ADEVĂRAT. Un temei complet și fals arată identic cu
unul complet și adevărat — s-a întâmplat de două ori (plafonul CASS atribuit Legii
141/2025 în loc de 239/2025, PR #127; cota TVA atribuită OUG 115/2023 în loc de Legea
141/2025, PR #168). E un gardian de COMPLETITUDINE.

TIPARELE NU SE SCRIU AICI
─────────────────────────
Tot ce e tipar vine din `app.domain.temei_legal`. Testul nu are voie să-și scrie
propriile regex-uri: ar fi a doua copie a formei, adică exact tiparul care a produs
mesajul de plafon TVA în trei formulări și termenul anual în două motoare. Modulul e
sursa; dacă vreodată diverg, modulul are dreptate — el rulează.
"""

import re
from datetime import date
from pathlib import Path

import pytest

from app.domain import temei_legal as tl
from app.domain.fiscal_calendar import DEFINITII_OBLIGATII

FISIER = Path(__file__).resolve().parents[1] / "app" / "domain" / "fiscal_calendar.py"

# Granița sintactică a unei definiții. NU e euristică pe text — e forma exactă în care
# sunt scrise cele 8, verificată de `test_extractorul_vede_toate_definitiile`.
_START = re.compile(r'^\s{4}"([A-Z0-9_]+)": DefinitieObligatie\($')
_SFARSIT = "    ),"
_ANCORA_DICT = "DEFINITII_OBLIGATII"


def _blocuri_temei():
    """
    {cheie: text_comentariilor} pentru fiecare definiție.

    Blocul unei definiții = de la sfârșitul celei precedente până la sfârșitul ei.
    Fereastra e aleasă așa fiindcă temeiurile stau în DOUĂ poziții structurale — D700
    îl are ÎNAINTEA definiției, D101 și D207 ÎNĂUNTRUL ei, înaintea unui câmp. O
    fereastră fixă (ultimele N linii) ar fi ratat-o pe una dintre ele; a fost prima
    greșeală la scrierea gardianului.
    """
    linii = FISIER.read_text(encoding="utf-8").split("\n")
    baza = next(i for i, l in enumerate(linii) if l.startswith(_ANCORA_DICT))
    starturi = [(i, m.group(1)) for i, l in enumerate(linii) for m in [_START.match(l)] if m]
    sfarsituri = [i for i, l in enumerate(linii) if l.rstrip() == _SFARSIT]

    blocuri, capat_anterior = {}, baza
    for s, cheie in starturi:
        e = next(x for x in sfarsituri if x > s)
        comentarii = [l for l in linii[capat_anterior:e + 1] if l.lstrip().startswith("#")]
        blocuri[cheie] = "\n".join(comentarii)
        capat_anterior = e
    return blocuri


# ============================================================
#   0. EXTRACTORUL — dacă el minte, tot restul e decor
# ============================================================

def test_extractorul_vede_toate_definitiile():
    """
    Ancora gardianului. Dacă `DefinitieObligatie(` se scrie vreodată altfel (pe un
    rând, cu alt indent), extractorul ar găsi ZERO definiții și TOATE testele de mai
    jos ar trece pe vid — un gardian verde care nu păzește nimic.
    """
    gasite = set(_blocuri_temei())
    assert gasite == set(DEFINITII_OBLIGATII), (
        f"extractorul vede {sorted(gasite)}, dicționarul are "
        f"{sorted(DEFINITII_OBLIGATII)} — granița sintactică s-a schimbat"
    )
    assert len(gasite) == 8


# ============================================================
#   1. STRUCTURAL — fiecare definiție poartă temei
# ============================================================

def test_fiecare_definitie_are_temei_sau_e_in_lista_inghetata():
    blocuri = _blocuri_temei()
    fara_temei = {k for k, txt in blocuri.items() if not tl.analizeaza(txt).e_complet}
    noi = fara_temei - tl.LISTA_INGHETATA
    assert not noi, (
        "Definiții FĂRĂ temei complet, care NU sunt în lista înghețată: "
        + ", ".join(sorted(noi))
        + "\n\nOrice definiție NOUĂ trebuie să poarte temei — vezi forma în "
        "docs/FORMA-TEMEI-LEGAL.md (cinci elemente). Lista înghețată din "
        "app/domain/temei_legal.py e o DATORIE CONSEMNATĂ pentru definițiile care "
        "existau la 13.09.2026, nu o ușă prin care intră altele: ea poate doar să scadă."
    )


def test_lista_inghetata_nu_ramane_in_urma():
    """
    Cealaltă direcție: o definiție care A PRIMIT temei trebuie ștearsă din listă.
    Altfel lista devine o ficțiune care rămâne în urma realității, iar peste un an
    nimeni nu mai știe care intrări sunt datorie adevărată.
    """
    blocuri = _blocuri_temei()
    au_temei = {k for k, txt in blocuri.items() if tl.analizeaza(txt).e_complet}
    rezolvate = au_temei & tl.LISTA_INGHETATA
    assert not rezolvate, (
        "Definiții care au ACUM temei complet, dar au rămas în LISTA_INGHETATA: "
        + ", ".join(sorted(rezolvate))
        + "\nȘterge-le din app/domain/temei_legal.py — lista poate doar să scadă."
    )


def test_lista_inghetata_e_masurata_nu_inventata():
    """Nicio cheie din listă nu poate lipsi din dicționar (typo sau definiție ștearsă)."""
    fantome = tl.LISTA_INGHETATA - set(DEFINITII_OBLIGATII)
    assert not fantome, f"chei în LISTA_INGHETATA care nu există: {sorted(fantome)}"


# ============================================================
#   2. FORMA — cele cinci elemente
# ============================================================

@pytest.mark.parametrize("cheie", sorted(set(DEFINITII_OBLIGATII) - tl.LISTA_INGHETATA))
def test_temeiul_are_toate_cele_cinci_elemente(cheie):
    raport = tl.analizeaza(_blocuri_temei()[cheie])
    assert raport.e_complet, (
        f"Temeiul lui {cheie} e incomplet. Lipsesc:\n  - "
        + "\n  - ".join(raport.elemente_lipsa)
        + "\n\nForma completă: docs/FORMA-TEMEI-LEGAL.md"
    )


def test_negasit_e_stare_valida_nu_esec():
    """
    D700 poartă `NEGĂSIT` la elementul 3 — și TREBUIE să treacă. Absența informației
    nu e dovada absenței modificării; un „negăsit" scris cu ce s-a încercat și când e
    un temei onest, nu unul rupt.
    """
    bloc = _blocuri_temei()["D700"]
    assert tl.MARCA_NEGASIT in bloc, "D700 nu mai poartă NEGĂSIT — testul a rămas în urmă"
    assert tl.RE_NEGASIT_MOTIVAT.search(bloc), 'NEGASIT fara "cautat <data>"'
    assert tl.analizeaza(bloc).e_complet, "un NEGĂSIT corect scris NU are voie să pice"


# ============================================================
#   3. PROSPEȚIMEA — pe data VERIFICĂRII
# ============================================================

@pytest.mark.parametrize("cheie", sorted(set(DEFINITII_OBLIGATII) - tl.LISTA_INGHETATA))
def test_temeiul_e_proaspat(cheie):
    d = tl.analizeaza(_blocuri_temei()[cheie]).data_verificarii
    assert d is not None, f"{cheie} n-are dată de verificare (elementul 5)"
    assert not tl.e_expirat(d, date.today()), (
        f"Temeiul lui {cheie} a fost verificat la {d.strftime('%d.%m.%Y')}, adică acum "
        f"{tl.luni_de_la(d, date.today())} luni — pragul e "
        f"{tl.PRAG_PROSPETIME_LUNI}.\n\n"
        "⚠️ NU rezolva asta editând data. Re-verifică textul pe forma consolidată "
        "(legislatie.just.ro), și abia apoi scrie data de azi. O dată împinsă fără "
        "verificare e exact minciuna pe care gardianul o previne — și e singurul lui "
        "mod de eșec care se repară cu o apăsare de tastă."
    )


def test_prospetimea_se_masoara_pe_verificare_nu_pe_consolidare():
    """
    Invariantul care dă sens separării elementelor 4 și 5: un temei cu formă
    consolidată VECHE, dar verificat ieri, e PROASPĂT. Dacă cineva mută vreodată
    măsurătoarea pe data consolidării, testul ăsta cade.
    """
    Q1, Q2 = tl.GHILIMEA_DESCHIDERE, tl.GHILIMEA_INCHIDERE
    azi = date(2026, 9, 13)
    bloc = (
        "# art. 310 alin. (6): " + Q1 + "cel tarziu la data depasirii plafonului" + Q2
        + "\n# modificat prin OG 22/2025 (MO 806/29.08.2025)."
        "\n# Forma consolidata legislatie.just.ro valabila la 01.01.2020."
        "\n# Verificat 01.09.2026."
    )
    raport = tl.analizeaza(bloc)
    assert raport.e_complet
    assert not tl.e_expirat(raport.data_verificarii, azi), (
        "consolidare veche + verificare recentă = PROASPĂT"
    )


# ============================================================
#   4. TIPARELE VIN DIN MODUL, NU DE AICI
# ============================================================

def test_gardianul_nu_isi_scrie_propriile_tipare():
    """
    Meta-gardian. Testul ăsta are voie să conțină UN SINGUR regex — cel al graniței
    sintactice (`_START`), care e despre forma codului Python, nu despre forma
    temeiului. Orice alt `re.compile` aici ar fi a doua copie a formei canonice.
    """
    sursa = Path(__file__).read_text(encoding="utf-8")
    # Acul se compune, ca să nu se numere pe sine: scris literal, ar apărea de două ori.
    ac = "re." + "compile("
    compilari = sursa.count(ac)
    assert compilari == 1, (
        f"{compilari} `re.compile` în gardian — tiparele temeiului se importă din "
        "app/domain/temei_legal.py, nu se rescriu aici. Vezi antetul modulului: la "
        "divergență modulul are dreptate, fiindcă el rulează."
    )
