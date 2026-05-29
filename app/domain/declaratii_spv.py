"""
Generator FISA DE COMPLETARE pentru Decontul special de TVA (D301).

NU genereaza PDF-ul inteligent ANAF (acela necesita programul de asistenta
ANAF). In schimb produce o fisa clara cu valorile EXACTE pe care
contribuabilul le transcrie in formularul oficial - elimina calculul manual.

Caz acoperit: PFA neplatitor de TVA, inregistrat special art. 317, care
primeste servicii intracomunitare (ex. comision Bolt din Estonia). Pentru
aceste servicii se aplica taxarea inversa: se datoreaza TVA 21% pe valoarea
comisionului, fara drept de deducere (fiind neplatitor) - deci TVA datorata
= TVA de plata.
"""

LUNI = {
    1: "Ianuarie", 2: "Februarie", 3: "Martie", 4: "Aprilie",
    5: "Mai", 6: "Iunie", 7: "Iulie", 8: "August",
    9: "Septembrie", 10: "Octombrie", 11: "Noiembrie", 12: "Decembrie",
}

# Cota TVA aplicabila incepand cu 1 august 2025 (Legea 141/2025)
COTA_TVA_CURENTA = 0.21


def construieste_fisa_d301(an: int, luna: int, baza_servicii_intra: float,
                           cota: float = COTA_TVA_CURENTA) -> dict:
    """
    Construieste datele fisei D301 pentru o luna.

    baza_servicii_intra = valoarea serviciilor intracomunitare primite
    (comisionul retinut de platforma in luna respectiva).
    """
    baza = round(baza_servicii_intra, 2)
    tva_datorata = round(baza * cota, 2)
    return {
        "an": an,
        "luna": luna,
        "luna_nume": LUNI.get(luna, str(luna)),
        "cota_pct": round(cota * 100),
        "baza": baza,
        "tva_datorata": tva_datorata,
        "tva_deductibila": 0.0,        # neplatitor - fara drept de deducere
        "tva_de_plata": tva_datorata,  # = TVA datorata
        "termen": f"25 {LUNI.get(luna % 12 + 1, '')}",
    }


def cota_tva_pentru(an: int, luna: int) -> float:
    """Cota TVA aplicabila: 21% de la 1 august 2025, 19% inainte."""
    if an > 2025 or (an == 2025 and luna >= 8):
        return 0.21
    return 0.19


def construieste_fisa_d301_din_tva(an: int, luna: int, tva_de_plata: float) -> dict:
    """
    Construieste fisa pornind de la TVA-ul deja calculat de bot
    (vat_out_total), derivand baza cu cota corecta a perioadei.
    """
    cota = cota_tva_pentru(an, luna)
    baza = round(tva_de_plata / cota, 2) if cota else 0.0
    d = construieste_fisa_d301(an, luna, baza, cota=cota)
    # pastram exact TVA-ul venit din bot (evitam diferente de rotunjire)
    d["tva_datorata"] = round(tva_de_plata, 2)
    d["tva_de_plata"] = round(tva_de_plata, 2)
    return d


def format_fisa_d301(d: dict) -> str:
    """Formateaza fisa de completare pentru un mesaj Telegram (Markdown)."""
    linii = []
    linii.append(f"📋 *Fisa completare D301 - {d['luna_nume']} {d['an']}*")
    linii.append("-----------------------------------")
    linii.append("*Decont special de TVA (formular 301)*")
    linii.append("_Operatiune: achizitie intracomunitara de servicii,_")
    linii.append("_taxare inversa, art. 317 Cod fiscal._")
    linii.append("")
    linii.append("*Valori de completat in formular:*")
    linii.append(f"• Baza impozabila: *{d['baza']:.2f}* lei")
    linii.append(f"• Cota TVA: *{d['cota_pct']}%*")
    linii.append(f"• TVA datorata (colectata): *{d['tva_datorata']:.2f}* lei")
    linii.append(f"• TVA de plata: *{d['tva_de_plata']:.2f}* lei")
    linii.append("")
    linii.append(f"💰 *DE PLATA catre ANAF: {d['tva_de_plata']:.2f} lei*")
    linii.append(f"🗓️ Termen depunere si plata: pana pe {d['termen']} {d['an'] if d['luna'] < 12 else d['an']+1}")
    linii.append("")
    linii.append("_Aceste valori se trec in PDF-ul inteligent D301 din "
                 "programul de asistenta ANAF. Reaminteste: cu D301 se "
                 "coreleaza si D390 (recapitulativa VIES), cod S._")
    return "\n".join(linii)
