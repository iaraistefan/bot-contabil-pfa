"""
GARDIAN: orice filtru pe `Document.status` e ALLOWLIST, niciodată denylist.

De ce
-----
`Document.status` e `Column(String(20))` — fără enum la nivel de coloană, fără
constrângere în DB. Nimic nu oprește o a treia valoare să apară, și nimic n-ar
semnala-o.

Un filtru denylist (`!= "rejected"`) e o afirmație despre valorile care NU există.
Afirmația aia n-are cine s-o apere: în ziua în care apare o stare nouă, TOATE
denylist-urile o includ tăcut. Codul nu dă nicio eroare — doar începe să numere
altceva decât credea autorul.

Concret, ce era în joc înainte de PR: șapte interogări cu `!=`, dintre care trei
erau chiar logica de deduplicare. Una (`has_docs` pe `source_file_id`) păzește
SINGURA cale de recuperare când confirmarea se pierde la un redeploy — un denylist
acolo ar fi răspuns „poza asta e deja înregistrată" pentru ceva ce nu s-a
înregistrat niciodată.

Allowlist-ul n-are proprietatea asta: el numește ce vrei, deci o valoare nouă e
EXCLUSĂ implicit. Excluderea greșită se vede (lipsește ceva); includerea greșită nu.

Valorile se derivă, nu se scriu aici
------------------------------------
`app.enums.DOC_STATUSES_SCRISE` e sursa. Testul o importă; nu ține o a doua listă.
Dacă apare o valoare nouă, se adaugă ACOLO întâi — iar testul de mai jos o acceptă
automat, fără să fie atins.
"""

import re
from pathlib import Path

from app.enums import DOC_STATUSES_SCRISE, DocStatus

RADACINA = Path(__file__).resolve().parents[1]
APP = RADACINA / "app"
BOT = RADACINA / "bot_contabil.py"

# Orice comparație pe `Document.status`, cu operatorul și (dacă există) literalul.
# `[\s\n]*` fiindcă filtrele sunt des sparte pe mai multe rânduri.
_FILTRU_STATUS = re.compile(
    r"Document\.status\s*(==|!=|\.in_\(|\.notin_\(|\.not_in\()\s*\n?\s*(\"[^\"]*\"|'[^']*')?"
)
_OPERATORI_PERMISI = ("==", ".in_(")


def _fisiere():
    for p in APP.rglob("*.py"):
        if "__pycache__" not in p.parts:
            yield p
    if BOT.exists():
        yield BOT


def _gaseste_filtre():
    """[(fisier, linie, operator, literal_sau_None)] pentru tot codul de producție."""
    gasite = []
    for p in _fisiere():
        if p.name == "enums.py":
            continue                     # acolo se DEFINESC valorile, nu se filtrează
        txt = p.read_text(encoding="utf-8", errors="ignore")
        for m in _FILTRU_STATUS.finditer(txt):
            nr = txt[:m.start()].count("\n") + 1
            literal = (m.group(2) or "").strip("\"'") or None
            gasite.append((p.relative_to(RADACINA), nr, m.group(1), literal))
    return gasite


def test_exista_filtre_de_pazit():
    """
    Ancoră. Dacă regex-ul nu mai prinde nimic (filtrele s-au rescris altfel), testele
    de mai jos ar trece pe vid — un gardian verde care nu păzește nimic.
    """
    filtre = _gaseste_filtre()
    assert len(filtre) >= 8, (
        f"gardianul vede doar {len(filtre)} filtre pe Document.status — forma lor "
        "s-a schimbat, iar regexul a rămas în urmă"
    )


def test_niciun_filtru_denylist():
    vinovati = [
        f"{f}:{nr} → {op}" for f, nr, op, _ in _gaseste_filtre()
        if op not in _OPERATORI_PERMISI
    ]
    assert not vinovati, (
        "Filtre DENYLIST pe Document.status:\n  " + "\n  ".join(vinovati)
        + "\n\nUn denylist e o afirmație despre valorile care NU există — iar "
        "`status` n-are enum pe coloană, deci nimeni n-o apără. Scrie ce vrei "
        "(`== \"posted\"` sau `.in_((...))`), nu ce nu vrei.\n"
        "Valorile cunoscute: app/enums.py → DOC_STATUSES_SCRISE."
    )


def test_literalele_sunt_valori_care_chiar_se_scriu():
    """
    A doua greșeală tăcută, alta decât denylist-ul: o comparație cu o valoare care nu
    se scrie niciodată e veșnic falsă și pare corectă la citire.
    `DocStatus` conține patru valori aspiraționale („draft", „confirmed", …) scrise
    în avans pentru un pas care n-a venit — deci verificăm contra celor SCRISE, nu
    contra vocabularului.
    """
    necunoscute = [
        f"{f}:{nr} → {lit!r}" for f, nr, _, lit in _gaseste_filtre()
        if lit is not None and lit not in DOC_STATUSES_SCRISE
    ]
    assert not necunoscute, (
        "Comparații pe status cu valori pe care codul nu le scrie:\n  "
        + "\n  ".join(necunoscute)
        + "\n\nO astfel de comparație e veșnic falsă și nu dă nicio eroare. Dacă "
        "valoarea e nouă și reală, adaug-o ÎNTÂI în app/enums.py "
        "(DOC_STATUSES_SCRISE), lângă motivul pentru care există."
    )


def test_sursa_unica_e_precisa_nu_aspirationala():
    """
    `DOC_STATUSES_SCRISE` trebuie să rămână submulțimea REALĂ a lui `DocStatus`, nu
    o copie a lui. Dacă cineva o umple cu tot vocabularul, gardianul de mai sus
    încetează să prindă comparațiile veșnic false.
    """
    vocabular = {s.value for s in DocStatus}
    assert DOC_STATUSES_SCRISE <= vocabular, (
        "DOC_STATUSES_SCRISE conține valori care nu sunt în DocStatus"
    )
    assert DOC_STATUSES_SCRISE < vocabular, (
        "DOC_STATUSES_SCRISE a devenit egală cu tot vocabularul DocStatus. Dacă toate "
        "cele șase valori chiar se scriu acum, șterge acest test și nota din enums.py "
        "— dar verifică ÎNTÂI în DB, nu presupune."
    )
    assert "posted" in DOC_STATUSES_SCRISE and "rejected" in DOC_STATUSES_SCRISE
