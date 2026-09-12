"""
TAXONOMIE vs OFERTĂ — două lucruri pe care le confundam până acum.

`FormaJuridica` (app/domain/fiscal_profile.py) e o **TAXONOMIE**: lista formelor
juridice care există în dreptul român și pe care ANAF ni le poate întoarce. Ea
trebuie să rămână completă chiar și pentru formele pe care NU le servim — altfel
n-am avea cum să numim ce ne vine din registru, iar un rând de profil salvat
înainte ar deveni un cod brut fără etichetă.

`FORME_SELECTABILE` de mai jos e **OFERTA**: formele pe care Coniar chiar le
servește corect, cap-coadă. E o submulțime a taxonomiei, și e singura listă pe
care are voie s-o afișeze o suprafață care cere userului să ALEAGĂ.

Confuzia asta avea un cost măsurat. Motorul fiscal e construit pe PFA: D212,
CAS/CASS pe praguri de salarii minime, deducerile, registrul în partidă simplă.
Singurul calcul conștient de formă (`tax_calculator.compute_full_estimate`) nu e
afișat nicăieri, iar cel care alimentează dashboardul, alertele și generarea D212
(`tax_engine.compute_d212_anual`) citește doar `regim_impunere`, niciodată forma.
Un SRL ajuns până la capăt primea zero declarații de TVA și o Declarație Unică cu
contribuții de persoană fizică pe CNP-ul lui. Nu e o margine: e produsul greșit.

De ce nu ștergem SRL-ul din taxonomie: pentru că el EXISTĂ, și continuă să ne vină.
`anaf_lookup` întoarce SRL_MICRO/SRL_NORMAL pentru orice CUI de firmă, iar poarta
de mai jos are nevoie de codurile astea ca să le RECUNOASCĂ și să oprească. O
taxonomie ciuntită ar face predicatul orb exact pe cazul pe care-l păzește.

Atenție însă la ce NU știm: codurile alea sunt o ghicitură pe denumire (orice „SRL"
→ SRL_MICRO, orice „SA" → SRL_NORMAL), nu un fapt din registru — ANAF nu ne dă
regimul de impunere. Bune ca să decidem „firmă, nu PFA"; nu bune ca să-i spunem
omului cum se impozitează. Vezi `mesaj_forma_neservita`.
"""

from typing import Optional

from app.domain.fiscal_profile import FormaJuridica

# OFERTA. Ce schimbi aici schimbă și botul, și wizardul web — gardianul din
# tests/test_forma_juridica_lbl_dashboard.py pică dacă vreo suprafață rămâne în urmă.
FORME_SELECTABILE = frozenset({
    FormaJuridica.PFA,
    FormaJuridica.II,
    FormaJuridica.IF,
    FormaJuridica.PROFESIE_LIBERALA,
})

CODURI_SELECTABILE = frozenset(f.value for f in FORME_SELECTABILE)


def e_servita(forma: Optional[str]) -> bool:
    """Servim forma asta cap-coadă?

    `None` / gol → True: absența unei forme NU e o formă neservită. Un PFA pentru
    care ANAF întoarce câmpul oficial gol trece pe aici des, iar a-l opri ar fi
    exact greșeala inversă. Cine nu știe forma o întreabă, nu o respinge.
    """
    if forma is None:
        return True
    forma = str(forma).strip()
    if not forma:
        return True
    return forma in CODURI_SELECTABILE


def mesaj_forma_neservita(denumire: Optional[str] = None) -> str:
    """Ce-i spunem celui care a introdus CUI-ul unei firme.

    Trei lucruri, în ordinea în care omul le are nevoie: ce s-a întâmplat, DE CE
    ne oprim (motivul real — cifre greșite —, nu regula internă), și ce poate face
    mai departe. Ultimul e cel care contează: cine are și firmă și PFA e un caz
    des, iar dacă nu i-l numim explicit pleacă crezând că a fost respins.

    NU PRIMEȘTE FORMA, ȘI E DELIBERAT. La momentul mesajului nu ȘTIM dacă firma e
    microîntreprindere sau pe impozit de profit: `anaf_lookup` mapează ORICE „SRL"
    din denumire la SRL_MICRO și orice „SA" la SRL_NORMAL — o ghicitură, nu un fapt
    din registru (ANAF nu ne dă regimul de impunere). O propoziție de tipul „la o
    microîntreprindere impozitul se aplică pe cifra de afaceri" ar prezenta
    presupunerea noastră drept fapt, în chiar mesajul prin care ne lăudăm că nu dăm
    cifre nesigure. Deci spunem ce e adevărat pentru AMBELE: baza de impozitare e
    alta. Vag și corect bate precis și posibil fals.

    Ultima frază e teza produsului, nu o consolare: la un PFA chiar nu-ți trebuie
    contabil, la o firmă îți trebuie. De-aia există Coniar, și de-aia ne oprim aici.

    Fără Markdown: îl pun suprafețele (botul are nevoie de `*`, web-ul de HTML).
    """
    nume = (denumire or "").strip()
    cine = f"CUI-ul ăsta e al unei firme: {nume}." if nume else "CUI-ul ăsta e al unei firme."

    return (
        f"{cine}\n\n"
        "Nu merg mai departe cu el, și vreau să-ți spun de ce — nu e o formalitate.\n\n"
        "La o firmă impozitul se calculează pe cu totul altă bază decât la un PFA. "
        "Tot ce fac eu — deducerile, combustibilul, CAS-ul, CASS-ul, "
        "Declarația Unică — e construit pe felul în care se impozitează un PFA. "
        "Dacă aș continua cu CUI-ul ăsta, ți-aș da cifre greșite la fiecare pas, "
        "iar tu ai afla abia la depunere, când e târziu de reparat.\n\n"
        "Prefer să-ți spun acum.\n\n"
        "Ai și un PFA? Mulți au — firma pentru o parte din activitate, PFA-ul "
        "pentru alta. Dă-mi CUI-ul PFA-ului și pornim de acolo.\n\n"
        "Pentru o firmă chiar ai nevoie de un contabil. Eu exist tocmai fiindcă "
        "la un PFA nu ai."
    )
