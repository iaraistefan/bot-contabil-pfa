"""
F1 — semantica lui `is_salariat`: „salariu de CEL PUȚIN 6 salarii minime pe an",
nu „angajat cu normă întreagă".

PROBLEMA rezolvată:
Flagul însemna un PROXY („normă întreagă"), nu testul legal. Art. 174 alin. (7)
lit. a) cere salarii de cel puțin 6 salarii minime pe an (24.300 lei); lit. c),
pensiile, n-au prag deloc. Un PFA salariat part-time sau angajat la mijlocul
anului bifa proxy-ul fără să atingă pragul → sărea podeaua → SUB-DECLARARE.

RĂDĂCINA NU ERA ÎN MOTOR. Coloanele erau deja separate (`models.py:75-76`), iar
OR-ul din `d212_calc.py:232` e corect odată ce intrările sunt corecte. Greșită
era ÎNTREBAREA pusă userului — deci înțelesul flagului. Reparație de SEMANTICĂ:
zero schemă, zero câmp nou, zero atingere pe calea pensionarului.

Testele de mai jos apără cele trei lucruri care pot regresa:
  1. sub prag (flag False) → podeaua SE aplică;
  2. pensionar → scutit indiferent de sumă (lit. c) n-are prag);
  3. bot și web pun ACEEAȘI întrebare, cu ACELAȘI prag.

⚠️ TOATE ANCORELE SE DERIVĂ DIN `PARAMETRI_CONTRIBUTII`, NU SE SCRIU LITERAL.
Un gardian cu „6" scris de mână ar fi apărat textul ÎNVECHIT dacă legea muta
multiplul podelei: s-ar fi transformat din pază în CIMENTARE — ar fi cerut ca
textele să păstreze cifra veche și ar fi picat exact pe cine le actualiza
corect. Derivat din `cass_jos`, gardianul cade când parametrul se schimbă iar
textele rămân în urmă. Prinde deriva în loc s-o fixeze.
"""

import re
from pathlib import Path

from app.domain.contributii import calcul_cass, PARAMETRI_CONTRIBUTII
from app.integrations.anaf.d212_calc import calculeaza_d212

_ROOT = Path(__file__).resolve().parent.parent

AN = 2026
SMB = PARAMETRI_CONTRIBUTII[AN]["salariu_minim"]      # 4050
_MULT = PARAMETRI_CONTRIBUTII[AN]["cass_jos"]         # 6 — multiplul podelei CASS
PRAG_JOS_RON = _MULT * SMB                             # 24.300
SUB_PRAG = 13_950.0                                    # venit net PFA sub podea


# ════════════════════════════════════════════════════════════
#   1. SALARIAT SUB PRAG — NU mai e scutit de podea
# ════════════════════════════════════════════════════════════

def test_salariat_sub_prag_nu_e_scutit_de_podea():
    """
    MIEZUL. Cine are salariu SUB 6 salarii minime pe an nu se califică pentru
    excepția de la art. 174 alin. (7) lit. a) → răspunde NU la întrebarea nouă
    → podeaua se aplică, ca oricărui neasigurat.

    Înainte bifa „normă întreagă" și scăpa de podea — de aici sub-declararea.
    """
    r = calcul_cass(SUB_PRAG, AN, asigurat_salariat=False)
    assert r["baza"] == PRAG_JOS_RON                 # 24.300, NU venitul real
    assert r["valoare"] == round(PRAG_JOS_RON * 0.10, 2)   # 2.430
    assert "minima" in r["nota"] or "minimă" in r["nota"]


def test_salariat_peste_prag_ramane_scutit():
    """Cine chiar atinge pragul păstrează excepția — 10% pe venitul real."""
    r = calcul_cass(SUB_PRAG, AN, asigurat_salariat=True)
    assert r["baza"] == SUB_PRAG
    assert r["valoare"] == round(SUB_PRAG * 0.10, 2)     # 1.395


# ════════════════════════════════════════════════════════════
#   2. PENSIONARUL — scutit indiferent de sumă (lit. c) n-are prag)
# ════════════════════════════════════════════════════════════

def test_pensionar_scutit_indiferent_de_suma():
    """
    Art. 174 alin. (7) lit. c): pensiile NU au prag. Un pensionar scapă de
    podea chiar dacă `asigurat_salariat` e False — prin OR-ul din d212_calc.
    Calea asta NU trebuie atinsă de reparația pe salarii.
    """
    r = calculeaza_d212(
        SUB_PRAG, 0.0, an=AN, salariu_minim=SMB,
        pensionar=True, asigurat_salariat=False,
    )
    assert r.cass == round(SUB_PRAG * 0.10, 2)      # 1.395 — pe net real
    assert r.cass != round(PRAG_JOS_RON * 0.10, 2)    # NU podeaua


def test_pensionar_cu_pensie_mica_tot_scutit():
    """Nu introducem un prag unde legea n-are: suma pensiei nu apare nicăieri."""
    mic = 1_000.0
    r = calculeaza_d212(
        mic, 0.0, an=AN, salariu_minim=SMB,
        pensionar=True, asigurat_salariat=False,
    )
    assert r.cass == round(mic * 0.10, 2)


def test_neasigurat_ramane_pe_podea():
    """REGRESIE: fără niciun flag, comportamentul e neschimbat."""
    r = calculeaza_d212(
        SUB_PRAG, 0.0, an=AN, salariu_minim=SMB,
        pensionar=False, asigurat_salariat=False,
    )
    assert r.cass == round(PRAG_JOS_RON * 0.10, 2)   # 2.430


# ════════════════════════════════════════════════════════════
#   3. GARDIAN — bot și web pun ACEEAȘI întrebare
# ════════════════════════════════════════════════════════════

# Fraza-ancoră trebuie să apară pe AMBELE suprafețe. Dacă cineva reformulează una
# singură, testul cade — exact scenariul care a produs blocantul: web-ul spunea
# „normă întreagă", botul spunea „6 salarii minime", și nimeni n-a văzut.
#
# ⚠️ ANCORA SE DERIVĂ, NU SE SCRIE LITERAL. Cu „6" scris de mână, gardianul ar fi
# apărat textul ÎNVECHIT dacă legea muta multiplul de la 6 la altceva: s-ar fi
# transformat din pază în CIMENTARE — ar fi cerut ca textele să păstreze cifra
# veche, și ar fi picat exact pe cine le actualiza corect. Derivată din
# `cass_jos`, cade când parametrul se schimbă iar textele rămân în urmă.
# Prinde deriva în loc s-o fixeze.
_PRAG_CANONIC = f"cel puțin {_MULT} salarii minime"

_WEB = _ROOT / "app" / "http" / "templates" / "dashboard.html"
_BOT = _ROOT / "app" / "services" / "declaratie_unica_ui.py"


def test_pragul_apare_pe_ambele_suprafete():
    web = _WEB.read_text(encoding="utf-8")
    bot = _BOT.read_text(encoding="utf-8")
    assert _PRAG_CANONIC in web, (
        f"Dashboard-ul nu mai poarta pragul [{_PRAG_CANONIC}] - "
        "userul bifeaza fara sa stie ce nivel i se cere."
    )
    assert _PRAG_CANONIC in bot, (
        f"Botul nu mai poarta pragul [{_PRAG_CANONIC}] - "
        "cele doua suprafete au divergat."
    )


def test_web_nu_mai_intreaba_de_norma_intreaga():
    """
    Proxy-ul vechi era exact bug-ul: „normă întreagă" nu e testul legal.
    Cade dacă cineva îl reintroduce.
    """
    web = _WEB.read_text(encoding="utf-8")
    toggle = re.search(r'tog\("is_salariat".*', web)
    assert toggle is not None, "toggle-ul is_salariat a disparut din dashboard"
    assert "normă întreagă" not in toggle.group(0), (
        "Toggle-ul is_salariat a revenit la proxy-ul [norma intreaga] - "
        "part-time si angajarea partiala de an trec sub prag si sar podeaua."
    )


def test_suma_pragului_e_derivata_nu_hardcodata():
    """
    Cifra de lângă prag trebuie SĂ VINĂ din payload, nu scrisă în template:
    altfel devine o constantă fiscală care se învechește la schimbarea SMB.
    Cade dacă cineva o înlocuiește cu un număr literal.
    """
    web = _WEB.read_text(encoding="utf-8")
    toggle = re.search(r'tog\("is_salariat".*', web).group(0)
    assert "_cass_prag_jos_ron" in toggle, (
        "Suma pragului nu mai vine din payload - risca sa fie hardcodata."
    )
    # Variantele in care s-ar putea strecura cifra, si ele DERIVATE (nu scrise):
    # „24300" si formatul RO „24.300".
    _brut = str(int(PRAG_JOS_RON))
    _ro = f"{int(PRAG_JOS_RON):,}".replace(",", ".")
    assert _brut not in toggle and _ro not in toggle, (
        "Suma pragului pare scrisa literal in template - trebuie derivata."
    )


def test_pragul_din_payload_e_corect():
    """Sursa unică: `prag_cass6_status` → același număr ca 6 × SMB."""
    from app.domain.contributii import prag_cass6_status
    assert prag_cass6_status(0.0, AN)["threshold_ron"] == PRAG_JOS_RON


def test_pensia_e_marcata_fara_prag_pe_ambele():
    """
    lit. c) n-are prag — și asta trebuie SPUS, altfel un pensionar cu pensie
    mică se auto-exclude crezând că pragul i se aplică și lui.
    """
    bot = _BOT.read_text(encoding="utf-8")
    assert "la pensie nu contează suma" in bot
