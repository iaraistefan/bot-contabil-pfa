"""
Poarta de eligibilitate: „Ai PFA în România?"

INTREBAREA NU E DESPRE NATIONALITATE SI NICI DESPRE TARA DE RESEDINTA. Un
cetatean strain poate avea PFA in Romania si atunci Coniar ii e de folos; un
roman mutat in Spania, fara PFA aici, nu are ce face cu noi. Singurul lucru care
conteaza e daca exista (sau va exista) o entitate fiscala romaneasca de
administrat — de aceea intrebarea e formulata pe FAPT, nu pe identitate.

Trei raspunsuri, doua stari de trecere:

  DA     — are PFA. Trece.
  VREAU  — nu inca, dar vrea sa deschida. Trece: exact omul caruia ii e de folos
           ghidul de infiintare, si l-am pierde daca l-am opri.
  NU     — nu are si nu vrea. Blocat, DAR reversibil (vezi mai jos).

NULL = n-a raspuns inca. E starea in care se afla toti userii existenti dupa
migrare, deci poarta li se arata o data si atat.

BLOCAREA E REVERSIBILA, prin constructie: un clic gresit nu are voie sa excluda
permanent un client real. „NU" se poate sterge inapoi la NULL, iar mesajul de
blocare SPUNE cum. Un ecran-fundatura fara cale de intors ar transforma o
greseala de degete intr-un client pierdut.
"""

from typing import Optional

DA = "DA"
VREAU = "VREAU"
NU = "NU"

RASPUNSURI_VALIDE = (DA, VREAU, NU)

# Cine trece mai departe in wizard.
RASPUNSURI_CARE_TREC = (DA, VREAU)


def e_raspuns_valid(val: Optional[str]) -> bool:
    return val in RASPUNSURI_VALIDE


def trece_poarta(val: Optional[str]) -> bool:
    """True doar pentru DA/VREAU. NULL (neintrebat) si NU sunt oprite.

    Conservator DELIBERAT: lipsa raspunsului NU e o trecere. Daca ar fi, poarta
    ar fi ocolita de orice user care n-a vazut-o niciodata — adica de toti cei
    existenti.
    """
    return val in RASPUNSURI_CARE_TREC


# ============================================================
#                    TEXTUL DE BLOCARE
# ============================================================

TITLU_INTREBARE = "Ai PFA în România?"

OPTIUNI = [
    (DA, "Da, am PFA"),
    (VREAU, "Încă nu, dar vreau să deschid"),
    (NU, "Nu"),
]

# Ce vede cine a raspuns „Nu". Trei lucruri, in ordinea asta: ce e Coniar (ca sa
# stie ce refuza), de ce nu-i e de folos ACUM (fara sa sune a respingere), si cum
# revine daca a apasat gresit — calea de intors e explicita, nu ascunsa.
MESAJ_BLOCAT = (
    "Coniar ține contabilitatea PFA-urilor din România: îți citește bonurile "
    "din poză, îți ține Registrul de Încasări și Plăți și îți spune ce ai de "
    "depus la ANAF și până când.\n\n"
    "Fără un PFA în România n-am ce administra pentru tine — nu din cauza "
    "cetățeniei sau a țării în care stai (un străin cu PFA în România e "
    "binevenit aici), ci pentru că tot ce fac eu se leagă de o firmă "
    "înregistrată la ANAF.\n\n"
    "Dacă ai apăsat din greșeală, sau dacă între timp ți-ai deschis un PFA, "
    "revino cu butonul de mai jos și răspunde din nou — nimic nu e definitiv."
)

MESAJ_BLOCAT_EN = (
    "Coniar does the bookkeeping for Romanian sole traders (PFA). Without a "
    "PFA registered in Romania there is nothing for me to manage — this is "
    "about the business, not about your nationality or where you live: a "
    "foreign citizen with a Romanian PFA is very welcome here.\n\n"
    "Tapped this by mistake, or opened a PFA since? Use the button below to "
    "answer again — nothing is final."
)

ETICHETA_INAPOI = "Am apăsat greșit — întreabă-mă din nou"
ETICHETA_INAPOI_EN = "Ask me again"
