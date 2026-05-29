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


def format_fisa_d301(d: dict, profil: dict = None) -> str:
    """
    Fisa de completare structurata EXACT ca formularul D301, sectiune cu
    sectiune, ca sa poata fi transcrisa 1:1 in PDF-ul oficial ANAF.

    Valorile din coloanele de baza/TVA se rotunjesc la leu (asa lucreaza
    formularul). Suma de control si Nr. evidenta platii se genereaza automat
    de PDF la validare - nu se completeaza manual.
    """
    p = profil or {}
    baza_r = round(d["baza"])
    tva_r = round(d["tva_datorata"])

    L = []
    L.append("📄 *DECONT SPECIAL DE TVA - 301*")
    L.append(f"*Pentru luna {d['luna']:02d}  anul {d['an']}*")
    L.append("(Declaratie rectificativa: NU)")
    L.append("===================================")
    L.append("")
    L.append("*1) DATELE DE IDENTIFICARE*")
    L.append(f"• Cod identificare fiscala: {p.get('firma_cui') or '—'}")
    L.append(f"• Denumire / Nume: {p.get('firma_nume') or '—'}")
    adr = p.get("adresa") or p.get("domiciliu") or "—"
    L.append(f"• Adresa: {adr}")
    L.append(f"• Telefon: {p.get('telefon') or '—'}")
    L.append(f"• Banca: {p.get('banca') or '—'}")
    L.append(f"• Cont (IBAN): {p.get('cont') or '—'}")
    L.append("")
    L.append("*2) TIP PERSOANA*")
    L.append("• [X] Persoane inregistrate conform art. 317")
    L.append("")
    L.append("*3) REZUMAT DECLARATIE*")
    L.append("• Suma de control: (auto, la validare)")
    L.append("• Nr. evidenta platii: (auto, la validare)")
    L.append("                    Baza imp.   TVA datorat")
    L.append("  Sectiunea 1          0           0")
    L.append("  Sectiunea 2          0           0")
    L.append("  Sectiunea 3          0           0")
    L.append(f"  Sectiunea 4        {baza_r:>4}        {tva_r:>4}")
    L.append(f"  Sectiunea 4.1      {baza_r:>4}        {tva_r:>4}")
    L.append("")
    L.append("*4) SECTIUNEA 4.1 - detaliu factura*")
    L.append("_Achizitii intracom. de servicii (taxare inversa)_")
    L.append(f"  1. Document Nr/Data: [nr. factura comision] / "
             f"{_ultima_zi(d['an'], d['luna'])}")
    L.append(f"  2. Valoare in valuta: {d['baza']:.2f}")
    L.append("  3. Tip valuta: RON")
    L.append("  4. Curs de schimb: 1")
    L.append(f"  5. Baza de impozitare: {baza_r}")
    L.append(f"  6. TVA datorat: {tva_r}")
    L.append("")
    L.append("  ⚠️ Apasa apoi butonul din formular:")
    L.append("  *Adauga facturi din sectiunea 4.1 in sectiunea 4*")
    L.append("")
    L.append("*5) DECLARATIE PE PROPRIA RASPUNDERE*")
    nume = (p.get("firma_nume") or "").upper()
    L.append(f"• Nume / Prenume: {nume or '—'}")
    L.append("• Functia: TITULAR PFA")
    L.append("")
    L.append(f"💰 *DE PLATA catre ANAF: {tva_r} lei*")
    L.append(f"🗓️ Termen depunere si plata: {d['termen']} "
             f"{d['an'] if d['luna'] < 12 else d['an']+1}")
    L.append("")
    L.append("_In PDF: completeaza, apasa VALIDARE, semneaza, depune in SPV. "
             "Se coreleaza cu D390 (cod S)._")
    return "\n".join(L)


def _ultima_zi(an: int, luna: int) -> str:
    """Ultima zi a lunii, format dd/mm/yyyy (data uzuala a facturii de comision)."""
    import calendar
    zi = calendar.monthrange(an, luna)[1]
    return f"{zi:02d}/{luna:02d}/{an}"
