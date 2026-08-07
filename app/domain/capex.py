"""
Achiziții de mijloc fix — deocamdată autoturisme.

PROBLEMA rezolvată:
O factură de cumpărare de mașină cădea pe fallback-ul `other_expense`, care e
100% deductibil. Rezultatul: 48.500 lei se scădeau integral din venitul lunii,
deși o mașină nu se deduce dintr-o dată — se amortizează, în ani.

DE CE ÎNTREBĂM ÎN LOC SĂ CLASIFICĂM
Un gardian automat pe seria de șasiu ar cădea DESCHIS: poză proastă, factură
fără VIN, mașină luată de la o persoană fizică pe contract în loc de factură —
în toate cazurile documentul ar cădea înapoi pe `other_expense` = 100%, adică
exact gaura pe care o păzim. Un gardian al cărui mod de eșec e chiar lucrul
păzit nu e gardian.
Un gardian care ÎNTREABĂ cade ÎNCHIS: costul maxim al unui declanșator fals e
o întrebare în plus.

ROLUL SUMEI
Suma NU e clasificator. Pe sumă nu deosebești nimic: o rablă costă 8.000 lei,
un motor refăcut 15.000. Suma e bună doar la a decide CÂND să întrebi, niciodată
la a decide CE e documentul. Decizia o ia omul, prin buton.
"""

from app.enums import DocType

# Codul categoriei. NU are keywords în `ridesharing.expense_categories` —
# e inaccesibilă scoring-ului semantic prin construcție. Singurul drum spre ea
# e alegerea explicită a userului.
CAT_ACHIZITIE_VEHICUL = "vehicle_acquisition"

# Categorii care NU sunt cheltuiala lunii: intră în patrimoniu și se scad prin
# amortizare, în ani. Sursă unică pentru separarea din tax_engine.
CATEGORII_CAPEX = frozenset({CAT_ACHIZITIE_VEHICUL})

# Pragul peste care botul întreabă ce e documentul, în loc să ghicească.
# 10.000 lei: sub el o cheltuială singulară de ridesharing e aproape sigur
# operațională (service mare, set de anvelope, reparație majoră), deci a întreba
# ar fi zgomot. Peste el, mizele unei clasificări automate greșite sunt mari și
# tăcute — merită o întrebare. Pragul reglează DOAR frecvența întrebării;
# mutarea lui nu poate clasifica greșit nimic, fiindcă nu el decide.
PRAG_INTREBARE_ACHIZITIE = 10000.0


def _suma_item(item) -> float:
    """Suma brută a unui item pending (dict din UI-ul de confirmare)."""
    try:
        return float(item.get("brut") or 0)
    except (TypeError, ValueError):
        return 0.0


def necesita_intrebare_achizitie(item) -> bool:
    """
    True dacă documentul e o cheltuială peste pragul de întrebare.

    NU spune „e o achiziție de mașină" — spune doar „nu ghici, întreabă omul".
    """
    if (item.get("tip") or "") != DocType.CHELTUIALA:
        return False
    return _suma_item(item) >= PRAG_INTREBARE_ACHIZITIE


def este_achizitie(category_code) -> bool:
    """True dacă o categorie e achiziție de mijloc fix (capitalizată)."""
    return (category_code or "") in CATEGORII_CAPEX
