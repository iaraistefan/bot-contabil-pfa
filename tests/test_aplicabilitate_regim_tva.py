"""
Aplicabilitatea obligațiilor pe axa regimului de TVA.

De ce există testul ăsta
------------------------
`_matches_forma_juridica` acceptă trei scrieri pentru forma juridică:

    "PFA"                                 → orice PFA, indiferent de TVA
    "PFA_platitor_TVA"                    → doar plătitor complet
    "PFA_neplatitor_TVA_cu_cod_special"   → doar neplătitor cu cod art. 317

Mecanismul e corect și e deja folosit de D300 / D301 / D390. D700 însă era scris
cu forma simplă `["PFA", "SRL_MICRO", "SRL_NORMAL"]`, deci se potrivea și unui
plătitor complet de TVA — care are cod pe art. 316, valid și pentru operațiuni
intracomunitare, și căruia art. 317 nu i se aplică deloc.

Rezultatul măsurat înainte de reparație: un `PFA PLATITOR_21` primea
`['D100 poz. 634', 'D207', 'D212', 'D300', 'D390', 'D700']` — D700 alături de
D300, adică i se cerea să se înregistreze special deși e deja înregistrat normal.

E o clasă sau un caz?
---------------------
Un caz. Auditul complet al celor 8 definiții arată că restul sunt:

  • corect indiferente de TVA — D100/D207 (impozit pe venitul nerezidenților),
    D212 (impozit pe venit), D101 (impozit pe profit). Niciuna nu depinde de
    regimul tău de TVA, deci forma simplă e alegerea potrivită.
  • deja conștiente de TVA — D300 (`_platitor_TVA`), D301
    (`_neplatitor_TVA_cu_cod_special`), D390 (ambele).

D700 era singura obligație a cărei aplicabilitate depinde REAL de regimul de TVA
dar care folosea forma simplă. Matricea de mai jos e forma executabilă a acelui
audit: dacă cineva schimbă o listă `forme_juridice`, matricea se mișcă și îl
obligă să se uite.
"""

from datetime import date

import pytest

from app.domain.fiscal_calendar import (
    DEFINITII_OBLIGATII,
    get_obligations_for_user,
    profil_califica_pentru,
)

TODAY = date(2026, 9, 5)
PRIMA_CURSA = date(2026, 3, 12)


def _coduri(forma, *, is_vat_payer=False, has_cod_special_tva=False,
            activitate="ridesharing"):
    obl = get_obligations_for_user(
        2026, 9, forma, activitate,
        today=TODAY, prima_activitate=PRIMA_CURSA,
        has_intracom_invoice=True, intracom_base_amount=700.0,
        is_vat_payer=is_vat_payer, has_cod_special_tva=has_cod_special_tva,
    )
    return {o.definitie.cod for o in obl}


# ══════════════════════════════════════════════════════════════
#  Reparația: D700 nu se aplică plătitorilor compleți
# ══════════════════════════════════════════════════════════════

def test_platitor_complet_nu_primeste_d700():
    """
    Art. 317 e procedura pentru cine NU e înregistrat normal (art. 316). Cine e
    plătitor complet are deja cod valid pentru intracomunitar.
    """
    coduri = _coduri("PFA", is_vat_payer=True)
    assert "D700" not in coduri
    # și chiar are declarațiile care i se cuvin — altfel testul ar trece fiindcă
    # lista e goală, nu fiindcă filtrul e corect
    assert "D300" in coduri
    assert "D390" in coduri


def test_platitor_complet_nu_primeste_nici_recomandarea_d700():
    """
    Calendarul și prevenția trec prin aceeași regulă (`_exclus_de_regimul_tva`).
    Dacă s-ar desincroniza, userul ar primi un sfat pentru o obligație care nu-i
    apare nicăieri — exact tiparul §ONRC.
    """
    assert not profil_califica_pentru(
        "D700", "PFA", "ridesharing", is_vat_payer=True,
    )
    assert profil_califica_pentru("D700", "PFA", "ridesharing")


def test_neplatitorul_fara_cod_primeste_in_continuare_d700():
    """Contra-proba: reparația restrânge, nu stinge."""
    coduri = _coduri("PFA")
    assert "D700" in coduri
    assert "D300" not in coduri
    assert "D301" not in coduri


def test_neplatitorul_cu_cod_special_nu_mai_primeste_d700():
    """Regula veche, păstrată intactă de refactorizare."""
    coduri = _coduri("PFA", has_cod_special_tva=True)
    assert "D700" not in coduri
    assert "D301" in coduri
    assert "D390" in coduri


# ══════════════════════════════════════════════════════════════
#  Matricea: forma executabilă a auditului
# ══════════════════════════════════════════════════════════════

MATRICE_PFA = [
    # (regim,               is_vat, cod_special, obligatorii,          interzise)
    ("NEPLATITOR",          False, False, {"D700"},            {"D300", "D301", "D390"}),
    ("SPECIAL_INTRACOM",    False, True,  {"D301", "D390"},    {"D700", "D300"}),
    ("PLATITOR_21",         True,  False, {"D300", "D390"},    {"D700", "D301"}),
]


@pytest.mark.parametrize(
    "regim,is_vat,cod_special,obligatorii,interzise", MATRICE_PFA,
    ids=[m[0] for m in MATRICE_PFA],
)
def test_matrice_pfa(regim, is_vat, cod_special, obligatorii, interzise):
    coduri = _coduri("PFA", is_vat_payer=is_vat, has_cod_special_tva=cod_special)
    assert obligatorii <= coduri, (
        f"{regim}: lipsesc {sorted(obligatorii - coduri)}"
    )
    assert not (interzise & coduri), (
        f"{regim}: apar obligații care nu i se aplică: "
        f"{sorted(interzise & coduri)}"
    )


def test_obligatiile_indiferente_de_tva_raman_indiferente():
    """
    D100/D207 (impozit pe venitul nerezidenților) și D212 (impozit pe venit) nu
    depind de regimul de TVA. Forma simplă e alegerea CORECTĂ pentru ele — testul
    ăsta există ca nimeni să nu „repare" și acolo, crezând că e aceeași lacună.
    """
    for is_vat, cod_special in ((False, False), (False, True), (True, False)):
        coduri = _coduri(
            "PFA", is_vat_payer=is_vat, has_cod_special_tva=cod_special,
        )
        assert {"D100 poz. 634", "D207", "D212"} <= coduri


def test_d700_e_singura_obligatie_dependenta_de_tva_cu_forma_simpla():
    """
    Gardianul de clasă. O obligație care folosește forma SIMPLĂ (fără sufixele
    `_platitor_TVA` / `_neplatitor_TVA_cu_cod_special`) e, prin construcție,
    indiferentă la regimul de TVA. Dacă apare una nouă care e de fapt dependentă,
    aici e locul unde se decide conștient — nu prin omisiune.

    Lista de mai jos e verdictul auditului, scris o dată. Când cineva adaugă o
    obligație, testul îl obligă să spună în care tabără e.
    """
    INDIFERENTE_DE_TVA = {"D100 poz. 634", "D207", "D212", "D101"}
    DEPENDENTE_DE_TVA = {"D300", "D301", "D390", "D700"}

    coduri_definite = {d.cod for d in DEFINITII_OBLIGATII.values()}
    assert coduri_definite == INDIFERENTE_DE_TVA | DEPENDENTE_DE_TVA, (
        "s-a adăugat/scos o obligație — decide dacă aplicabilitatea ei depinde "
        "de regimul de TVA și pune-o în tabăra potrivită"
    )

    for cheie, d in DEFINITII_OBLIGATII.items():
        foloseste_forma_simpla = not any(
            "_TVA" in f for f in d.forme_juridice
        )
        if d.cod in INDIFERENTE_DE_TVA:
            assert foloseste_forma_simpla, (
                f"{d.cod} e declarat indiferent de TVA dar folosește o formă "
                f"cu sufix de regim: {d.forme_juridice}"
            )
        elif d.cod == "D700":
            # Singura excepție justificată: forma simplă (D700 se aplică ORICĂREI
            # forme juridice), iar dependența de regim e exprimată explicit în
            # `_exclus_de_regimul_tva`, nu în datele definiției. Motivul: regula
            # „NU ești înregistrat pe art. 316" n-are o scriere în vocabularul
            # `_matches_forma_juridica`, care știe doar „platitor" și
            # „neplatitor_cu_cod_special" — nu și „neplatitor fără cod".
            assert foloseste_forma_simpla
            assert not profil_califica_pentru(
                "D700", "PFA", "ridesharing", is_vat_payer=True,
            ), "D700 cu formă simplă TREBUIE gardat explicit pe regimul de TVA"
        else:
            assert not foloseste_forma_simpla, (
                f"{d.cod} e declarat dependent de TVA dar folosește forma "
                f"simplă: {d.forme_juridice} — ori îi pui sufixul, ori îl "
                f"gardezi explicit ca D700"
            )


# ══════════════════════════════════════════════════════════════
#  DEFECT DESCHIS, înregistrat ca să nu se piardă
# ══════════════════════════════════════════════════════════════

@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT REAL ÎNTR-O TAXONOMIE DEVENITĂ INACCESIBILĂ. Două jumătăți, și "
        "amândouă contează:\n"
        "  (1) Defectul EXISTĂ: `_matches_forma_juridica` construiește sufixul din "
        "forma userului — pentru `SRL_MICRO` iese `SRL_MICRO_platitor_TVA`, dar "
        "datele scriu `SRL_platitor_TVA`. Un SRL plătitor de TVA n-ar primi NICIO "
        "declarație de TVA (nici D300, nici D390, nici D301).\n"
        "  (2) Nu mai poate fi ATINS: SRL_MICRO/SRL_NORMAL au fost retrase din "
        "ofertă (app/domain/forma_servita.py). Nu se mai pot alege din bot sau web, "
        "iar cele trei drumuri prin care forma se ATRIBUIE din CUI (onboarding bot, "
        "lookup web, reîmprospătare ANAF) se opresc înainte de a o scrie. Producția "
        "avea zero useri pe SRL la data retragerii — deci nimeni n-a pățit-o și "
        "nimeni nu poate ajunge acolo acum.\n"
        "NU-L REPARA crezând că e viu: ai repara o cale pe care n-o mai parcurge "
        "nimeni, și ai readuce în calendar obligații pentru o formă pe care motorul "
        "fiscal nu o servește oricum (D212 i-ar calcula CAS/CASS de persoană fizică). "
        "NU-L ȘTERGE crezând că e caduc: enum-ul a rămas intenționat complet, iar "
        "ziua în care cineva repune SRL-ul în FORME_SELECTABILE, ăsta e testul care "
        "spune ce mai e de reparat înainte. E memoria defectului, nu cererea lui.\n"
        "Dacă REINTRODUCEM SRL-ul în ofertă: repară întâi sufixul, apoi șterge "
        "marcajul. `strict=True` face testul să pice dacă începe să treacă, ca "
        "nimeni să nu repare tăcut."
    ),
)
def test_srl_platitor_tva_ar_trebui_sa_primeasca_d300():
    coduri = _coduri("SRL_MICRO", is_vat_payer=True)
    assert "D300" in coduri
    assert "D390" in coduri


def test_srl_platitor_tva_nu_mai_primeste_d700_gresit():
    """
    Ce ȘTIM că e reparat de PR-ul ăsta, chiar dacă defectul de mai sus rămâne:
    SRL-ul plătitor nu mai e trimis să depună D700. Înainte primea D700 și nimic
    altceva pe axa TVA — o obligație greșită în locul celor corecte.
    """
    assert "D700" not in _coduri("SRL_MICRO", is_vat_payer=True)
    assert "D700" not in _coduri("SRL_NORMAL", is_vat_payer=True)
