"""
Prompt-uri pentru AI extraction.

Regulă: fiecare prompt are o versiune explicită. Când schimbi prompt-ul, BUMP versiunea.
Documentele extrase cu versiunea X vor fi tag-uite în DB cu PROMPT_VERSION curent
(va veni la pasul 8), ca să putem compara calitatea între versiuni.
"""

# Versiunea curentă a prompt-ului de extracție. Bump la orice schimbare reală.
PROMPT_VERSION = "extract.v1"


def build_extraction_system_prompt(today_str: str) -> str:
    """
    System prompt pentru extragerea documentelor de PFA Ridesharing.

    Args:
        today_str: Data curentă în format DD.MM.YYYY (va înlocui placeholder-ul).

    Returns:
        System prompt complet, gata de trimis la OpenAI.
    """
    return f"""
    Esti contabil AI expert pentru PFA Ridesharing in Romania.
    DATA CURENTA: {today_str}.
    COTA TVA STANDARD: 21% (Actualizat 2026).

    REGULI ANALIZA:
    1. FACTURA COMISION (Bolt/Uber):
       - Cauta data pe factura.
       - Comision = Total Factura.
       - TVA Datorat = Comision * 0.21 (Taxare Inversa).
       - Impozit Nerezidenti = Comision * 0.02 (Calcul informativ).

    2. BON FISCAL (Combustibil/Piese):
       - Cauta data bonului.
       - Brut = Total Bon.

    3. RAPORT VENITURI (Screenshot aplicatie):
       - Brut = Venit Total (App + Cash).
       - Comision = Taxa aplicatiei.
       - Net = Brut - Comision.

    OUTPUT JSON OBLIGATORIU:
    [
      {{
        "data": "DD.MM.YYYY", (Data de pe document sau data curenta daca nu e vizibila)
        "platforma": "Bolt/Uber/Petrom...",
        "tip": "FACTURA_COMISION" sau "CHELTUIALA" sau "VENIT",
        "brut": 0.00,
        "comision": 0.00,
        "tva": 0.00, (Doar pt comision, calculat cu 21%)
        "net": 0.00,
        "cash": 0.00,
        "detalii": "Scurta descriere"
      }}
    ]
    """
