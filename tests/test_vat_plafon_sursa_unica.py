"""
Plafon TVA — sursă unică de text + gardieni.

Trei lucruri se verifică aici:
  1. cele trei stări dau cele trei mesaje, cu fondul juridic corect;
  2. GARDIAN: textul nu se duplică — fraza-cheie apare o singură dată în app/;
  3. GARDIAN: „10 zile" nu mai există nicăieri în app/ pe subiectul plafonului.

Temeiul: art. 310 alin. (6) Cod fiscal după OG 22/2025 (în vigoare 01.09.2025),
verificat pe forma consolidată valabilă la 08.08.2026 — înregistrarea se cere
„cel târziu la data depăşirii plafonului", iar regimul normal se aplică
„începând cu tranzacţia care conduce la depăşirea plafonului".
"""
import re
from pathlib import Path

import pytest

from app.domain.vat_plafon_msg import (
    build_vat_plafon_msg,
    STATUS_OK,
    STATUS_APROAPE,
    STATUS_DEPASIT,
)

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# Fişiere care au voie să conţină „10 zile" / „sfârşitul lunii".
#   d700_ghid.py     — „3-10 zile" e durata de ridicare a certificatului de la
#                      ghişeul ANAF: realitate administrativă, nu termen legal.
#   vat_plafon_msg.py — docstring-ul explică EXPLICIT regula veche şi de ce a
#                      fost eliminată de OG 22/2025. Fără istoricul ăsta scris
#                      undeva, cineva o reintroduce peste un an crezând că
#                      repară o omisiune. Textele LIVRATE din acest modul sunt
#                      verificate separat (test_nicio_stare_nu_pomeneste_*),
#                      deci nu rămâne o portiţă.
ALLOWLIST_REGULA_VECHE = {"d700_ghid.py", "vat_plafon_msg.py"}


def _app_text_files():
    """Toate fişierele de cod/şablon din app/ (fără cache, fără binare)."""
    for p in APP_DIR.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in (".py", ".html", ".js"):
            continue
        if "__pycache__" in p.parts:
            continue
        yield p


# ============================================================
#   1. CELE TREI STĂRI → CELE TREI MESAJE
# ============================================================

def test_ok_ramane_neutru():
    """Sub prag: doar informativ, fără avertisment, fără pași."""
    m = build_vat_plafon_msg(STATUS_OK, 100_000, 395_000)
    assert "✅" in m["lung"]
    assert "25%" in m["lung"]                      # 100k din 395k
    assert "295.000" in m["scurt"]                 # cât a mai rămas
    # nu speriem pe nimeni care e la un sfert de plafon
    assert "plătitor de TVA pe loc" not in m["scurt"]
    assert "retroactiv" not in m["lung"]


def test_aproape_spune_cat_a_ramas_si_ca_nu_exista_zile_de_gratie():
    """≥80%: mesajul important — cât a mai rămas ȘI regula reală."""
    m = build_vat_plafon_msg(STATUS_APROAPE, 340_000, 395_000)
    lung = m["lung"]
    assert "🟡" in lung
    assert "86%" in lung                           # 340k/395k
    assert "55.000 lei" in lung                    # cât a mai rămas
    # fondul juridic: pe loc, din acea tranzacţie, fără graţie
    assert "pe loc" in lung
    assert "tranzacția care îl rupe" in lung
    assert "Nu există zile de grație" in lung
    # ton de avertisment util, nu de panică: nu cere acţiune azi
    assert "Nu trebuie să faci nimic azi" in lung
    # varianta scurtă duce acelaşi fond
    assert "55.000 lei" in m["scurt"]
    assert "pe loc" in m["scurt"]


def test_depasit_spune_ca_esti_deja_platitor_si_da_pasii():
    """≥100%: deja plătitor, retroactiv, cu paşi concreţi."""
    m = build_vat_plafon_msg(STATUS_DEPASIT, 410_000, 395_000)
    lung = m["lung"]
    assert "🔴" in lung
    # miezul: eşti DEJA plătitor, din tranzacţia care a rupt plafonul
    assert "Ești deja plătitor de TVA" in lung
    assert "tranzacția care a rupt plafonul" in lung
    assert "Nu de luna viitoare, nu de când depui cererea" in lung
    # paşii concreţi
    assert "1️⃣" in lung and "2️⃣" in lung and "3️⃣" in lung
    assert "formularul 700" in lung
    assert "SPV" in lung
    assert "retroactiv" in lung
    # data înregistrării = ziua depăşirii (art. 316 alin. (1^1) lit. b)
    assert "ziua în care ai depășit plafonul" in lung
    # varianta scurtă
    assert "ești deja plătitor de TVA" in m["scurt"]
    assert "azi" in m["scurt"]


@pytest.mark.parametrize("status", [STATUS_OK, STATUS_APROAPE, STATUS_DEPASIT])
def test_nicio_stare_nu_pomeneste_zile_de_gratie(status):
    """Regula veche nu are voie să reapară în niciun mesaj."""
    m = build_vat_plafon_msg(status, 300_000, 395_000)
    for varianta in (m["lung"], m["scurt"]):
        assert "10 zile" not in varianta
        assert "sfârșitul lunii" not in varianta


def test_none_safe():
    """Cifră/plafon lipsă nu aruncă (payload parţial, user nou)."""
    m = build_vat_plafon_msg(STATUS_OK, None, None)
    assert isinstance(m["lung"], str) and isinstance(m["scurt"], str)


# ============================================================
#   2. GARDIAN — SURSA E CHIAR UNICĂ
# ============================================================

# Fraze care definesc regula. Dacă apar ORIUNDE în afara sursei unice,
# înseamnă că cineva a copiat textul în loc să-l consume.
#
# De ce „nicăieri altundeva" şi nu „exact o dată": în sursă frazele sunt sparte
# pe linii de f-string, deci nici acolo nu apar literal. Ce contează e că nu
# apar într-un AL DOILEA loc — adică nimeni n-a rescris mesajul altundeva.
FRAZE_CANONICE = [
    "tranzacția care a rupt",
    "Ești deja plătitor de TVA",
    "Nu există zile de grație",
    "plătitor de TVA pe loc",
]


@pytest.mark.parametrize("fraza", FRAZE_CANONICE)
def test_gardian_textul_nu_se_duplica(fraza):
    """
    Nicio frază canonică nu apare în afara sursei unice.

    Cade dacă cineva rescrie mesajul de plafon TVA în alt modul, în alt şablon
    sau direct în JS — exact greşeala pe care refactorizarea asta a reparat-o.
    """
    intrusi = [
        str(p.relative_to(APP_DIR)) for p in _app_text_files()
        if p.name != "vat_plafon_msg.py"
        and fraza in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not intrusi, (
        f"Fraza {fraza!r} a fost copiată în: {intrusi}. "
        f"Textul de plafon TVA se scrie DOAR în app/domain/vat_plafon_msg.py; "
        f"celelalte suprafeţe îl consumă prin build_vat_plafon_msg()."
    )


def test_gardian_suprafetele_consuma_sursa_unica():
    """Cele trei suprafeţe importă sursa, nu îşi compun textul."""
    fp = (APP_DIR / "domain" / "fiscal_profile.py").read_text(encoding="utf-8")
    pa = (APP_DIR / "services" / "proactive_alerts.py").read_text(encoding="utf-8")
    ap = (APP_DIR / "http" / "app.py").read_text(encoding="utf-8")
    for continut in (fp, pa, ap):
        assert "build_vat_plafon_msg" in continut

    # dashboard-ul consumă câmpul din payload, nu compune text
    dash = (APP_DIR / "http" / "templates" / "dashboard.html").read_text(encoding="utf-8")
    assert "vat.mesaj_scurt" in dash


# ============================================================
#   3. GARDIAN — „10 ZILE" A DISPĂRUT DIN app/
# ============================================================

def test_gardian_niciun_10_zile_ramas_in_app():
    """
    Regula veche (10 zile de la sfârşitul lunii) nu mai are voie nicăieri.

    A fost eliminată de OG 22/2025. Singura excepţie permisă e ghidul D700,
    unde „3-10 zile" e durata de ridicare a certificatului de la ANAF.
    """
    vinovati = []
    for p in _app_text_files():
        if p.name in ALLOWLIST_REGULA_VECHE:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"10 zile|zece zile", txt, re.IGNORECASE):
            linie = txt[:m.start()].count("\n") + 1
            vinovati.append(f"{p.relative_to(APP_DIR)}:{linie}")
    assert not vinovati, (
        "Sintagma '10 zile' a reaparut in: " + ", ".join(vinovati) +
        ". Termenul de inregistrare TVA e ACUM chiar ziua depasirii "
        "(art. 310 alin. (6), OG 22/2025) — nu exista zile de gratie."
    )


def test_gardian_niciun_sfarsitul_lunii_pe_tva():
    """Cealaltă jumătate a regulii vechi (ficţiunea „prima zi a lunii următoare")."""
    vinovati = [
        str(p.relative_to(APP_DIR)) for p in _app_text_files()
        if p.name not in ALLOWLIST_REGULA_VECHE
        and "sfârșitul lunii" in p.read_text(encoding="utf-8", errors="ignore")
    ]
    assert not vinovati, f"Sintagma 'sfarsitul lunii' a reaparut in: {vinovati}"
