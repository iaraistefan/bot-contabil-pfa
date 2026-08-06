"""
SURSĂ UNICĂ pentru mesajele de plafon TVA (art. 310 Cod fiscal).

De ce există modulul ăsta
-------------------------
Mesajul de plafon TVA apărea DUPLICAT în trei suprafețe, cu trei formulări
diferite, toate spunând o regulă care nu mai e în vigoare („ai 10 zile de la
sfârșitul lunii"). Aici e singurul loc din tot codul unde se scrie ce înseamnă
depășirea plafonului. Cele trei suprafețe consumă de aici:

  1. `fiscal_profile.vat_threshold_status()`  → câmpul `message`
  2. `proactive_alerts._tva_plafon_message()` → alerta zilnică Telegram
  3. `app.py` payload `vat.mesaj_scurt`       → banda de praguri din dashboard

Un test-gardian (`tests/test_vat_plafon_sursa_unica.py`) cade dacă textul se
duplică în altă parte sau dacă „10 zile" reapare undeva în `app/`.

TEMEIUL LEGAL — de ce „10 zile" a dispărut
------------------------------------------
Art. 310 alin. (6) Cod fiscal, în forma dată de OG nr. 22/2025 (M. Of. 806 din
29 august 2025), în vigoare de la 1 septembrie 2025 — verificat pe forma
consolidată legislatie.just.ro valabilă la 08.08.2026, unde art. 310 NU are
nicio modificare ulterioară lui 01-09-2025:

    „(6) Persoana impozabilă care aplică regimul special de scutire şi a cărei
    cifră de afaceri [...] depăşeşte plafonul de scutire prevăzut la alin. (1)
    trebuie să solicite înregistrarea în scopuri de TVA, conform art. 316,
    CEL TÂRZIU LA DATA DEPĂŞIRII PLAFONULUI. Regimul normal de taxare se aplică
    din data depăşirii plafonului [...], ÎNCEPÂND CU TRANZACŢIA CARE CONDUCE LA
    DEPĂŞIREA PLAFONULUI."

Ce s-a schimbat față de regula veche: până la 31.08.2025, alin. (6) dădea 10
zile, iar „data depăşirii" era prin ficţiune juridică prima zi a lunii
următoare — de unde „până pe 10 ale lunii următoare". OG 22/2025 a eliminat
ficţiunea. Termenul e ACUM chiar ziua depăşirii; nu mai există zile de graţie.

Consecinţe, tot din art. 310:
  - alin. (6^1) lit. b): dacă ANAF constată întârzierea, înregistrează din
    oficiu DE LA data depăşirii şi stabileşte obligaţii de plată constând în
    „DIFERENŢA dintre taxa pe care persoana impozabilă ar fi trebuit să o
    colecteze şi taxa pe care ar fi avut dreptul să o deducă". NU TVA brut —
    deducerile din perioadă (motorină, service, comision) se scad. De asta
    mesajul de stare DEPĂŞIT spune explicit „se datorează diferenţa": e partea
    din lege care lucrează în favoarea userului, şi ar fi necinstit s-o ascunzi
    într-un mesaj care oricum sperie.
  - alin. (6^2)-(6^3): dacă persoana constată singură, îşi cere înregistrarea de
    la data depăşirii şi înscrie diferenţa în primul decont.
  - art. 316 alin. (1^1) lit. b): înregistrarea e valabilă DE LA data depăşirii,
    nu de la data cererii.

De asta mesajele de mai jos spun „ești deja plătitor", nu „ai un termen".
"""

STATUS_OK = "OK"
STATUS_APROAPE = "APROAPE_PLAFON"
STATUS_DEPASIT = "DEPASIT_PLAFON"


def _lei(value: float) -> str:
    """12345.6 → „12.345" (separator mia punct, ca în restul produsului)."""
    return f"{value:,.0f}".replace(",", ".")


def build_vat_plafon_msg(status, cifra_afaceri, threshold_ron):
    """
    Textele canonice de plafon TVA pentru o stare dată.

    Args:
        status: STATUS_OK / STATUS_APROAPE / STATUS_DEPASIT.
        cifra_afaceri: cifra de afaceri realizată YTD (lei).
        threshold_ron: plafonul aplicabil (lei) — VAT_THRESHOLD_RON.

    Returns:
        dict cu:
        - „lung"  : paragraf pentru bot / alerte / câmpul `message` (Markdown
                    Telegram, cu emoji de stare).
        - „scurt" : o singură frază pentru banda de praguri din dashboard
                    (fără emoji — banda are deja glif propriu).

    Pur: fără I/O, fără sesiune, fără dependenţe de alte module de domeniu.
    Plafonul vine ca parametru tocmai ca să rămână o singură sursă şi pentru
    cifră (VAT_THRESHOLD_RON), şi pentru text (aici).
    """
    ca = float(cifra_afaceri or 0)
    thr = float(threshold_ron or 0)
    ramas = max(0.0, thr - ca)
    pct = (ca / thr * 100) if thr else 0.0

    if status == STATUS_DEPASIT:
        lung = (
            f"🔴 Ai depășit plafonul de TVA ({_lei(ca)} din {_lei(thr)} lei).\n\n"
            f"Ești deja plătitor de TVA — din chiar tranzacția care a rupt "
            f"plafonul. Nu de luna viitoare, nu de când depui cererea.\n\n"
            f"Ce ai de făcut, în ordine:\n"
            f"1️⃣ Depune *azi* cererea de înregistrare în scopuri de TVA "
            f"(formularul 700, prin SPV).\n"
            f"2️⃣ Data înregistrării va fi ziua în care ai depășit plafonul, "
            f"nu ziua în care depui cererea.\n"
            f"3️⃣ TVA-ul se datorează retroactiv, de la acea tranzacție "
            f"încoace — inclusiv pe facturile pe care le-ai emis între timp "
            f"fără TVA. Se datorează diferența: TVA-ul pe care trebuia să-l "
            f"colectezi, minus TVA-ul pe care ai dreptul să-l deduci din "
            f"aceeași perioadă (motorină, service, comision).\n\n"
            f"Nu e o catastrofă, dar nu o amâna: fiecare zi de întârziere "
            f"adaugă dobânzi și penalități la ce ai de plătit."
        )
        scurt = (
            "ai depășit plafonul — ești deja plătitor de TVA din tranzacția "
            "care l-a rupt; cererea de înregistrare se depune azi"
        )

    elif status == STATUS_APROAPE:
        lung = (
            f"🟡 Te apropii de plafonul de TVA: {pct:.0f}% "
            f"({_lei(ca)} din {_lei(thr)} lei).\n\n"
            f"Mai ai *{_lei(ramas)} lei* până la plafon.\n\n"
            f"Bine de știut acum, cât ai timp: în clipa în care îl depășești, "
            f"devii plătitor de TVA *pe loc* — chiar de la tranzacția care îl "
            f"rupe. Nu există zile de grație, iar cererea de înregistrare se "
            f"depune chiar în ziua depășirii.\n\n"
            f"Nu trebuie să faci nimic azi. Doar să știi ce urmează, ca să nu "
            f"te prindă pe picior greșit."
        )
        scurt = (
            f"mai ai {_lei(ramas)} lei — când îl depășești devii plătitor de "
            f"TVA pe loc, chiar din acea tranzacție"
        )

    else:  # STATUS_OK — neschimbat față de comportamentul de dinainte
        lung = (
            f"✅ Sub plafon TVA: {pct:.0f}% folosit "
            f"({_lei(ca)} din {_lei(thr)} lei)"
        )
        scurt = f"mai ai {_lei(ramas)} lei până devii plătitor de TVA"

    return {"lung": lung, "scurt": scurt}
