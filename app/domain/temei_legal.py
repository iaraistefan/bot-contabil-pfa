"""
Subsetul MAȘINĂ-CITIBIL al formei canonice a temeiului legal.

Perechea de cod a documentului `docs/FORMA-TEMEI-LEGAL.md`. Împărțirea e stabilită
acolo și se repetă aici o singură dată, ca să fie citibilă de la locul de muncă:

    • MODULUL e sursa pentru TIPARE (ce se poate verifica mecanic).
    • DOCUMENTUL e sursa pentru JUDECATĂ (de ce, când, ce înseamnă).
    • LA DIVERGENȚĂ, MODULUL ARE DREPTATE — fiindcă el rulează.

Gardianul (`tests/test_gardian_temei.py`) DERIVĂ tot de aici. Dacă vreodată își scrie
propriile tipare, avem a doua copie a formei — exact tiparul care a produs mesajul de
plafon TVA în trei formulări, termenul anual în două motoare și numărul ONRC cu două
date de verificare. A doua copie pare mereu inofensivă în ziua în care se scrie.

CE VERIFICĂ, ȘI CE NU
─────────────────────
Verifică FORMA și PROSPEȚIMEA. NU verifică CORECTITUDINEA atribuirii — un temei
complet și fals arată identic cu unul complet și adevărat (Legea 141/2025 e actul
corect pentru cota TVA și era cel greșit pentru plafonul CASS). Numai citirea legii
prinde asta. E un gardian de completitudine; nu-i cere altceva.

NU ÎNCEARCĂ SĂ DETECTEZE PROZĂ FISCALĂ
──────────────────────────────────────
Deliberat. Întrebarea „fraza asta e o afirmație fiscală?" nu e decidabilă mecanic:
„deductibil 50%" e, „împarte la 2" nu e, deși spun același lucru. Un clasificator pe
cuvinte-cheie ar prinde și prețurile din `subscription.py`, și duratele administrative
din `d700_ghid` (câte zile durează ridicarea unui certificat de la ghișeu — realitate
de procedură, nu termen legal). Iar fals-pozitivele nu sunt un deranj — sunt
MECANISMUL PRIN CARE MOARE UN GARDIAN: se umple allowlist-ul, apoi nu mai păzește
nimic.
Deci gardianul se uită la o suprafață identificabilă STRUCTURAL: definițiile din
`DEFINITII_OBLIGATII`. Sunt 8, adică 37 din cele 96 de afirmații ale inventarului —
cea mai valoroasă bucată, cu zero ambiguitate despre ce e înăuntru.

NOTĂ DE SCRIERE: în literalele Python de mai jos se folosesc APOSTROFI ori de câte ori
textul conține ghilimele românești. O ghilimea ASCII de închidere pusă după una
românească termină string-ul în tăcere — a fost prinsă de trei ori la scrierea acestui
fișier.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

# Ghilimelele românești, ca nume — ca să nu fie scrise literal în regex-uri.
GHILIMEA_DESCHIDERE = "„"   # „
GHILIMEA_INCHIDERE = "”"    # ”


# ============================================================
#            TIPARELE (sursa unică — testul le importă)
# ============================================================

# Data, în convenția folosită peste tot în temeiuri: dd.mm.yyyy
RE_DATA = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")

# 1. Adresa în act: art. 317 · art. 42 alin. (1) · art. 317 alin. (1) lit. c)
RE_ARTICOL = re.compile(r"\bart\.\s?\d+", re.IGNORECASE)

# 2. Citatul literal. Discriminantul e GHILIMEAA DE DESCHIDERE românească („): ea nu
#    apare niciodată într-un string de cod, deci ne scutește de fals-pozitivele pe
#    care le-ar da ghilimelele drepte (prezente peste tot în dict-uri și literale).
#
#    ÎNCHIDEREA e permisivă — acceptă și ” (românească), și " (ASCII). Nu din
#    neglijență: așa scrie PROIECTUL, măsurat pe cele trei temeiuri existente (patru
#    deschideri românești, ZERO închideri românești). A cere perechea completă ar fi
#    însemnat să impunem o convenție tipografică pe care codul n-o urmează, adică să
#    rescriem proza ca să se potrivească gardianului — exact pe dos.
#    Mai e un motiv practic: ghilimeaua ASCII de închidere pusă după una românească
#    termină string-ul Python în tăcere. Am călcat în asta de trei ori scriind acest
#    fișier. Cine scrie temeiuri va călca și el; regexul nu trebuie să-l mai pedepsească
#    și pe axa asta.
#
#    Minimum 10 caractere — un citat de lege nu e un cuvânt.
RE_CITAT = re.compile(
    GHILIMEA_DESCHIDERE + '[^' + GHILIMEA_INCHIDERE + '"]{10,}[' +
    GHILIMEA_INCHIDERE + '"]',
    re.DOTALL,
)

# 3. Actul modificator — TREI STĂRI VALIDE, nu una plus două scuze.
RE_ACT = re.compile(
    r"\b(?:Legea|Lege|O\.?U\.?G\.?|OUG|O\.?G\.?|OG|OPANAF|Ordinul)\s*"
    r"(?:nr\.?\s*)?\d+[/\s]",
    re.IGNORECASE,
)
RE_MO = re.compile(r"\bMO\s?\d+/\d{2}\.\d{2}\.\d{4}|Monitorul Oficial", re.IGNORECASE)
MARCA_NEMODIFICAT = "nemodificat de la publicare"
MARCA_NEGASIT = "NEGĂSIT"   # NEGĂSIT
# Un NEGĂSIT scris corect spune CE s-a încercat și CÂND. Fără asta e indistinct de
# „n-am căutat", iar documentul cere ca starea asta să se scrie cu aceeași demnitate
# ca celelalte două — deci și cu aceleași pretenții.
RE_NEGASIT_MOTIVAT = re.compile(
    MARCA_NEGASIT + r"[\s\S]{0,400}?căutat\s+\d{2}\.\d{2}\.\d{4}",
    re.IGNORECASE,
)

# 4. Forma consolidată. Eticheta e obligatorie; VALOAREA ei poate fi și o negare
#    explicită (NU am citit forma consolidată), fiindcă e o stare onestă și des
#    întâlnită — adesea citim actul modificator, nu codul consolidat. A o respinge
#    ar împinge spre afirmația falsă că am citit-o.
RE_CONSOLIDAT = re.compile(r"form[ăa]\s+consolidat", re.IGNORECASE)

# 5. Data verificării NOASTRE. Pe ea se măsoară prospețimea — vezi mai jos.
RE_VERIFICAT = re.compile(r"[Vv]erificat\s+(\d{2}\.\d{2}\.\d{4})")


# ============================================================
#                 PRAGUL DE PROSPEȚIME
# ============================================================

# 12 LUNI. Argumentul, în ambele direcții, fiindcă e un cadran, nu un adevăr:
#
# PENTRU MAI SCURT (6 luni): legislația fiscală RO se mișcă în sezoane — pachetul de
#   sfârșit de an (OUG în decembrie, în vigoare 1 ianuarie) și cele de mijloc de an
#   (OG 16/2022 în iulie, Legea 141/2025 în iulie, OUG 8/2026 în februarie). Un prag de
#   6 luni ar prinde fiecare sezon. Eșecul de la care a pornit tot auditul — regula
#   veche de plafon TVA, unde legea s-a mutat la 01.09.2025 (OG 22/2025) și nimeni
#   n-a observat până în august 2026 — ar fi fost prins cu vreo 5 luni mai devreme.
#   (Sintagma exactă a regulii vechi NU se scrie aici: un gardian dedicat
#   — `tests/test_vat_plafon_sursa_unica.py` — o interzice în tot `app/`, tocmai ca
#   să nu poată fi reintrodusă ca sfat curent. Istoria ei stă în `vat_plafon_msg.py`.)
#
# PENTRU MAI LUNG, și de ce a câștigat: un test de prospețime care cade se „repară"
#   EDITÂND O DATĂ. Iar editarea datei fără re-verificare e exact minciuna pe care
#   gardianul o previne. Un prag agresiv nu produce verificări — produce date false.
#   Ăsta e singurul gardian din proiect al cărui mod de eșec se rezolvă cu o apăsare
#   de tastă, și asta trebuie să-i aleagă cadranul.
#   12 luni = un ciclu legislativ complet, plus un ritual anual plauzibil
#   (re-verificare în ianuarie, după ce pachetul de sfârșit de an a aterizat). La 8
#   definiții înseamnă ~8 verificări pe an: muncă reală, dar care încape într-o ședință.
#
# ⚠️ PRAGUL ĂSTA E O PLASĂ DE REZERVĂ, NU DETECTORUL PRINCIPAL.
#   Detectorul de schimbări legislative e `app/ai/fiscal_monitor.py`: rulează lunar
#   (job programat în `scheduler.py`), caută activ modificări în Monitorul Oficial și
#   pe ANAF, și raportează. ACOLO se prinde o lege care s-a mutat.
#   Pragul de aici nu caută nimic. El doar spune „temeiul ăsta n-a mai fost privit de
#   prea mult timp" — prinde ce a scăpat de detector, nu ține locul detectorului.
#
#   DE CE CONTEAZĂ DISTINCȚIA: cineva care vede o lege mutată nesemnalată va fi tentat
#   să coboare pragul, crezând că așa o prinde mai repede. N-o va prinde — pragul nu
#   citește legea, citește un calendar. Tot ce va obține e ca testul să cadă mai des,
#   iar căderile să se „repare" prin împingerea datei, adică DATE EDITATE FĂRĂ
#   VERIFICARE. Ar strica exact instrumentul pe care încearcă să-l ascută.
#   Dacă detectorul ratează ceva, se repară DETECTORUL (prompt, surse, frecvență),
#   nu plasa de dedesubt.
#
# SE MUTĂ DE AICI, nu din test. Dacă se coboară la 6, se coboară cu ochii deschiși:
# va cere de două ori mai des o muncă pe care nimeni n-o poate face repede.
PRAG_PROSPETIME_LUNI = 12


# ============================================================
#              LISTA ÎNGHEȚATĂ — datorie, nu scutire
# ============================================================

# Definițiile care la 13.09.2026 NU poartă temei. Măsurat, nu presupus.
#
# ⚠️ E O DATORIE CONSEMNATĂ, NU O SCUTIRE PERMANENTĂ.
# Lista poate DOAR SĂ SCADĂ. Nu se adaugă nimic în ea, niciodată: o definiție NOUĂ fără
# temei trebuie să pice gardianul, fiindcă ăsta e chiar rostul lui — să oprească
# hemoragia, nu să certifice starea de fapt. Backfill-ul celor de mai jos e planificat
# DUPĂ LANSARE, în ordinea severității din `docs/INVENTAR-PROZA-FISCALA.md`; busola o
# spune la §5 F2: gardianul oprește hemoragia, backfill-ul curăță trecutul.
#
# Când una primește temei, se ȘTERGE de aici — iar gardianul cade dacă uiți s-o ștergi,
# ca lista să nu devină o ficțiune care rămâne în urma realității.
LISTA_INGHETATA = frozenset({
    "D100_634",   # inventar #1  — termenul lunar, nerezidenți
    "D301",       # inventar #12 — decontul special TVA
    "D390",       # inventar #17 — recapitulativa VIES
    "D300",       # inventar #21 — decontul TVA
    "D212",       # inventar #25 — Declarația Unică
})


# ============================================================
#                     ANALIZA UNUI TEMEI
# ============================================================

@dataclass(frozen=True)
class RaportTemei:
    """Ce s-a găsit într-un bloc de comentarii, element cu element."""
    are_articol: bool
    are_citat: bool
    are_stare_act: bool          # act+MO · SAU nemodificat · SAU NEGĂSIT motivat
    are_consolidat: bool
    data_verificarii: Optional[date]

    @property
    def elemente_lipsa(self) -> List[str]:
        lipsa = []
        if not self.are_articol:
            lipsa.append('1. articol + alineat (ex. "art. 317 alin. (1) lit. c)")')
        if not self.are_citat:
            lipsa.append(
                '2. citat literal din lege, intre ghilimele romanesti '
                '(minim 10 caractere)'
            )
        if not self.are_stare_act:
            lipsa.append(
                '3. starea actului: (act + Monitorul Oficial) SAU '
                '"nemodificat de la publicare" SAU NEGASIT insotit de '
                '"cautat <zz.ll.aaaa>"'
            )
        if not self.are_consolidat:
            lipsa.append(
                '4. forma consolidata (eticheta e obligatorie; valoarea poate fi si '
                'o negare explicita)'
            )
        if self.data_verificarii is None:
            lipsa.append('5. "verificat <zz.ll.aaaa>"')
        return lipsa

    @property
    def e_complet(self) -> bool:
        return not self.elemente_lipsa


def analizeaza(text: str) -> RaportTemei:
    """
    Citește un bloc de comentarii și spune ce elemente ale formei canonice conține.

    NU judecă dacă temeiul e ADEVĂRAT — vezi antetul modulului. Doar dacă e complet.
    """
    stare_act = bool(
        (RE_ACT.search(text) and RE_MO.search(text))
        or MARCA_NEMODIFICAT.lower() in text.lower()
        or RE_NEGASIT_MOTIVAT.search(text)
    )
    return RaportTemei(
        are_articol=bool(RE_ARTICOL.search(text)),
        are_citat=bool(RE_CITAT.search(text)),
        are_stare_act=stare_act,
        are_consolidat=bool(RE_CONSOLIDAT.search(text)),
        data_verificarii=cea_mai_veche_verificare(text),
    )


def cea_mai_veche_verificare(text: str) -> Optional[date]:
    """
    Data verificării. Când sunt mai multe, o ia pe CEA MAI VECHE — conservator:
    un temei e proaspăt cât e proaspătă cea mai veche parte a lui.
    """
    gasite = []
    for m in RE_VERIFICAT.finditer(text):
        zz, ll, aaaa = m.group(1).split(".")
        try:
            gasite.append(date(int(aaaa), int(ll), int(zz)))
        except ValueError:
            continue        # 32.13.2026 — dată imposibilă, o ignorăm
    return min(gasite) if gasite else None


def luni_de_la(d: date, azi: date) -> int:
    """Vechimea în luni întregi, fără dependențe externe."""
    luni = (azi.year - d.year) * 12 + (azi.month - d.month)
    if azi.day < d.day:
        luni -= 1
    return luni


def e_expirat(data_verificarii: Optional[date], azi: date,
              prag_luni: int = PRAG_PROSPETIME_LUNI) -> bool:
    """
    Prospețimea se măsoară pe data VERIFICĂRII, nu pe cea a consolidării — vezi
    `docs/FORMA-TEMEI-LEGAL.md`, secțiunea despre elementele 4 și 5.
    """
    if data_verificarii is None:
        return False        # lipsa datei e alt eșec (elementul 5), raportat separat
    return luni_de_la(data_verificarii, azi) >= prag_luni
