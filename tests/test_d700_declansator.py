"""
D700 — declanșatorul înregistrării: PRIMIREA SERVICIULUI, nu factura.

De ce există testul ăsta
------------------------
Textul spunea „înainte de prima factură intracomunitară", în patru locuri.
Direcția e periculoasă, nu doar imprecisă: factura de comision vine DUPĂ
prestare. Un user care așteaptă factura ca semnal află că avea o obligație
abia după ce a încălcat-o, fără nicio cale de a o mai respecta la timp.

Temeiul: art. 317 alin. (1) lit. c) Cod fiscal — înregistrarea se solicită
„înaintea primirii serviciilor respective". Forma consolidată legislatie.just.ro
valabilă la 08.08.2026, verificat 18.08.2026. Pentru un șofer, serviciul de
intermediere se primește când conduce → momentul real e PRIMA CURSĂ.

Gardianul scanează TOT `app/`, nu doar fișierul reparat: aceeași propoziție
trăia în două module, cu trei formulări. Un test pe fișier ar fi ratat copia.
"""

import re
from pathlib import Path

import pytest

from app.domain.fiscal_calendar import DEFINITII_OBLIGATII

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Declanșatorul interzis: „(înainte de) prima/primei factură".
_TRIGGER = re.compile(r"(prima|primei)\s+factur", re.IGNORECASE)

# ── Excepții, pe LINIE, nu pe fișier ──────────────────────────────
# Un allowlist pe fișier ar fi inutil aici: `fiscal_calendar.py` e chiar locul
# unde trăiește D700, deci scutirea lui ar dezarma gardianul complet.
#
# d301_generator.py — „cota afisata (din prima factura ...)" e despre D301, unde
#   factura CHIAR e faptul generator: TVA-ul se autocalculează pe factura de
#   comision primită. Acolo „prima factură" nu e un termen de înregistrare, ci
#   sursa cotei dintr-o lună. Legitim.
#
# fiscal_calendar.py — antetul lui D700 NUMEȘTE regula greșită ca s-o respingă
#   („de ce «prima cursă», nu «prima factură»"). Fără istoria asta scrisă lângă
#   cod, cineva o reintroduce peste un an crezând că repară o omisiune — exact
#   raționamentul din `vat_plafon_msg.py`, care e allowlistat pentru „10 zile"
#   din același motiv. Excepția e pe LINIA aceea, nu pe fișier: restul lui
#   fiscal_calendar.py rămâne sub gardian, inclusiv câmpurile livrate ale D700.
ALLOWLIST_LINII = {
    "d301_generator.py": ("toate dintr-o luna au aceeasi cota",),
    "fiscal_calendar.py": ("TEMEIUL DECLANȘATORULUI",),
}

# NOTĂ: `fiscal_calendar.py` conține și afirmații despre D301 legate de factură
# (`descriere`/`cui_se_aplica` la D301, unde factura e faptul generator). Nu au
# nevoie de excepție — nu spun „prima factură", ci „factură de comision", deci
# nu se potrivesc cu declanșatorul de mai sus. Dacă vreodată o afirmație despre
# D301 chiar are nevoie de „prima factură", se adaugă aici, cu motiv scris.


def _app_text_files():
    for p in APP_DIR.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".html", ".js") \
                and "__pycache__" not in p.parts:
            yield p


# ============================================================
#   1. Definiția D700 — declanșatorul, direct
# ============================================================

@pytest.mark.parametrize("camp", ("descriere", "cand", "cui_se_aplica"))
def test_d700_nu_se_declanseaza_pe_factura(camp):
    """Niciun câmp livrat al lui D700 nu trimite userul la factură ca semnal."""
    txt = getattr(DEFINITII_OBLIGATII["D700"], camp) or ""
    gasit = _TRIGGER.search(txt)
    assert not gasit, (
        f"D700.{camp} leaga inregistrarea de factura ({gasit.group(0)!r}). "
        "Factura vine DUPA prestare — userul ar afla prea tarziu. "
        "Declansatorul e primirea serviciului: art. 317 alin. (1) lit. c)."
    )


def test_d700_spune_prima_cursa():
    """Nu e destul să lipsească factura — trebuie să apară momentul real."""
    d = DEFINITII_OBLIGATII["D700"]
    assert "cursă" in d.cand.lower(), "D700.cand nu numeste momentul real (prima cursa)"
    assert "cursă" in d.cui_se_aplica.lower() or "cursă" in d.descriere.lower()


def test_d700_poarta_temeiul_datat():
    """Blocantul temeiului datat: articol + alineat + literă + data verificării."""
    d = DEFINITII_OBLIGATII["D700"]
    assert "317" in d.cand and "alin. (1) lit. c)" in d.cand
    assert "08.08.2026" in d.cand and "18.08.2026" in d.cand, (
        "temeiul lui D700 nu poarta forma consolidata + data verificarii"
    )


# ============================================================
#   2. Gardian repo-wide — copiile
# ============================================================

def test_gardian_niciun_declansator_factura_pentru_inregistrare():
    """
    Scanare pe tot `app/`. Cade dacă „prima factură" reapare oriunde, în afara
    excepțiilor motivate pentru D301 (unde factura e faptul generator).
    """
    vinovati = []
    for p in _app_text_files():
        txt = p.read_text(encoding="utf-8", errors="ignore")
        permise = ALLOWLIST_LINII.get(p.name, ())
        for m in _TRIGGER.finditer(txt):
            nr = txt[:m.start()].count("\n") + 1
            linie = txt.splitlines()[nr - 1]
            if any(frag in linie for frag in permise):
                continue
            vinovati.append(f"{p.relative_to(APP_DIR)}:{nr}")
    assert not vinovati, (
        "Declansatorul 'prima factura' a reaparut in: " + ", ".join(vinovati) +
        ". Inregistrarea in scopuri de TVA se cere INAINTEA PRIMIRII "
        "SERVICIILOR (art. 317 alin. (1) lit. c) — pentru un sofer, inainte de "
        "prima cursa. Daca linia e despre D301, adaug-o in ALLOWLIST_LINII cu motiv."
    )


def test_gardian_special_notes_nu_reapare():
    """
    `SPECIAL_NOTES` a fost șters: duplica DEFINITII_OBLIGATII, n-avea niciun
    consumator, dar era exportat în `__all__` — deci arăta a API public și
    purta a patra copie a declanșatorului greșit.
    """
    import app.domain.fiscal_calendar as fc
    assert not hasattr(fc, "SPECIAL_NOTES"), (
        "SPECIAL_NOTES a reaparut. Continut duplicat fara consumator = a doua "
        "sursa de adevar care se desincronizeaza tacut."
    )
    assert "SPECIAL_NOTES" not in fc.__all__
