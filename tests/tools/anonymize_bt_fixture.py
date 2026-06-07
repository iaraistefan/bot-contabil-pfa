"""
Generator one-time pentru fixture-ul de test al parserului BT.

Anonimizează extrasul BT real RE-PLASÂND fiecare token la coordonatele lui
ORIGINALE (extrase din PDF-ul real), înlocuind doar datele personale (nume, CUI,
IBAN, REF, id-uri card/terminal). Sumele/datele/structura coloanelor + rândurile
de control (RULAJ/SOLD/TOTAL) rămân IDENTICE.

Garanție de coordonate: tokenii numerici sunt plasați right-aligned la x1-ul
original → benzile Debit (x1≈475) / Credit (x1≈573) NU se mișcă, indiferent de
lungimea textului anonimizat (care e left-aligned, independent).

Rulare: python tests/tools/anonymize_bt_fixture.py <input.pdf> <output.pdf>
NU face parte din suită — e un utilitar de generat fixture-ul.
"""
import re
import sys

import pdfplumber
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

AMT_RE = re.compile(r"^[0-9][0-9.,]*\.[0-9]{2}$")

# Substituții token-cu-token (datele personale → fictiv). Cheia = textul exact al
# tokenului din PDF; valoarea = înlocuitorul. Tokenii neenumerați rămân la fel.
WORD_SUBST = {
    "IARAI": "POPESCU",
    "STEFAN": "ION",
    "DB97466": "DB00000",
    "53067338": "00000000",
    "ANTHROPIC": "MERCHANTUS",
    "Netflix.com": "MERCHANTNL",
}

# Substituții pe substring (IBAN, REF, id-uri, telefon, card, RRN, TID, CIF, PID)
# — aplicate pe orice token care conține pattern-ul.
SUBSTR_SUBST = [
    (re.compile(r"RO88BTRLRONCRT0DB9746601"), "RO00BTRLRONCRT0XX0000001"),
    (re.compile(r"606RONCRT0DB9746601"), "000RONCRT0XX0000001"),
    (re.compile(r"RO82TREZ10120A1203000001"), "RO00TREZ00000A0000000001"),
    (re.compile(r"RO21CITI0000000000032018"), "RO00CITI0000000000000000"),
    (re.compile(r"42611000"), "00000000"),                 # C.I.F.
    (re.compile(r"P?ID2\d{8}"), lambda m: m.group(0)[:3] + "000000000"),
    (re.compile(r"42444688"), "00000000"),                 # card
    (re.compile(r"\+14152360599"), "+10000000000"),        # telefon
    (re.compile(r"RRN:\d+"), "RRN:000000000000"),
    (re.compile(r"TID:[A-Z0-9]+"), "TID:XXXXXXXX"),
    (re.compile(r"Q0RRUWQV26H30SO"), "XXXXXXXXXXXXXX"),
    (re.compile(r"\b0\d{2}NVPO[0-9A-Za-z]+"), "000XXXX000000XX"),
    (re.compile(r"606ZEXA[0-9A-Za-z]+"), "000XXXX000000X"),
    (re.compile(r"606a1ez[0-9A-Za-z]+"), "000XXXX000000"),
    (re.compile(r"\b0{6,}\d+"), "000000000000"),           # nr lungi gen 000000000204867
]


def anon(text: str) -> str:
    if text in WORD_SUBST:
        return WORD_SUBST[text]
    for pat, repl in SUBSTR_SUBST:
        text = pat.sub(repl, text)
    return text


def main(src: str, dst: str) -> None:
    pdf = pdfplumber.open(src)
    W, H = float(pdf.pages[0].width), float(pdf.pages[0].height)
    c = canvas.Canvas(dst, pagesize=(W, H))
    for pg in pdf.pages:
        for w in pg.extract_words():
            txt = anon(w["text"])
            size = max(6.0, round(w["bottom"] - w["top"]) - 1)
            y = H - w["bottom"]                       # baseline ≈ page_h - bottom
            c.setFont("Helvetica", size)
            if AMT_RE.match(w["text"]):
                c.drawRightString(w["x1"], y, txt)   # sume: right-aligned la x1 ORIGINAL
            else:
                c.drawString(w["x0"], y, txt)        # text: left-aligned la x0 original
        c.showPage()
    c.save()
    print(f"scris: {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
