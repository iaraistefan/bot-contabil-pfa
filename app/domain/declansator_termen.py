"""
Tripwire pentru DECLANȘATORUL termenelor lunare (D100 / D301 / D390).

Modul PUR (fără I/O, fără DB, fără import din aplicație). Se cablează în
`app.services.posting`, la ingestia facturii de comision.

═══════════════════════════════════════════════════════════════════════
DE CE EXISTĂ ACEST MODUL
═══════════════════════════════════════════════════════════════════════

Luna în care sistemul semnalează D100 / D301 / D390 se ia din DATA FACTURII:
`posting.post_document` derivă `period_year`/`period_month` din `data_doc`, iar
`fiscal_calendar._is_aplicabil` decide apariția obligației pe `has_intracom_invoice`
(= „există factură în luna asta").

Legea NU leagă însă termenul de factură. Îl leagă de altce, diferit pe declarație:

  • D100 — Cod fiscal art. 224 alin. (5): termenul curge de la PLATA VENITULUI —
    „până la data de 25 inclusiv a lunii următoare celei în care s-a plătit venitul".
  • D301 — Cod fiscal art. 324 alin. (2): termenul curge de la EXIGIBILITATE —
    „a lunii următoare celei în care ia naștere exigibilitatea operațiunilor".
  • D390 — Cod fiscal art. 325, modificat la 01-07-2024 prin OUG 70/2024: termenul
    nu mai stă în Codul fiscal, ci în OPANAF 6.073/2024 (MO 771/07.08.2024), tot pe
    exigibilitate.

Trei declanșatoare legale distincte; unul singur implementat („factura").

CE FACE COINCIDENȚA SĂ ȚINĂ AZI — DOUĂ VERIGI, NU UNA
─────────────────────────────────────────────────────
VERIGA 1, TARE — MECANISMUL DE REȚINERE.
Bolt NU încasează comisionul la scadența unei facturi: îl REȚINE din fiecare cursă,
pe parcursul perioadei. Factura reală o confirmă negru pe alb — „De plătit: 0,00 lei",
taxare inversă, TVA 0%: nu e o cerere de plată, e decontul unei plăți deja făcute
prin reținere. Deci venitul către nerezident e plătit ÎN TIMPUL lunii acoperite, iar
exigibilitatea se naște tot acolo.
Asta e temelia: coincidența dintre plată, exigibilitate și perioada acoperită e
CONSECINȚA MECANISMULUI, nu o convenție de datare. Cât timp comisionul se reține din
curse, plata nu POATE cădea în altă lună decât cea în care s-au făcut cursele.

VERIGA 2, SLABĂ — DATAREA.
Ce leagă mecanismul de ceea ce calculăm noi e o a doua verigă, mult mai fragilă:
faptul că Bolt datează factura în ULTIMA ZI a perioadei acoperite. Doar asta ne
permite să echivalăm „luna lui `data_doc`" cu „perioada acoperită" — fiindcă noi NU
captăm perioada, doar data. Când factura e datată 31.08 pentru 01.08–31.08, cele trei
declanșatoare cad în august și dau același termen: 25 septembrie.

Veriga 2 se poate rupe fără ca veriga 1 să se schimbe: mecanismul poate rămâne
identic, iar Bolt să înceapă să emită pe 03.09 pentru august. În ziua aceea
`period_month` devine septembrie → D100 semnalat pe 25 octombrie, în timp ce venitul
a fost reținut în august → termenul legal era 25 septembrie. O lună de ÎNTÂRZIERE,
apărută în tăcere. De asta tripwire-ul RĂMÂNE, deși veriga 1 e solidă: el păzește
veriga 2.

Modulul nu repară declanșatorul și nu mută nicio lună. Face doar ca ziua în care
datarea se schimbă să fie ZGOMOTOASĂ: o abatere de la tipar lasă urmă în log și în
`audit_logs`, ca s-o aflăm de la cea dintâi factură atipică, nu de la prima amendă.

═══════════════════════════════════════════════════════════════════════
CE E CONFIRMAT LA SURSĂ — ȘI CE A RĂMAS LIMITĂ
═══════════════════════════════════════════════════════════════════════

Măsurat pe baza de producție (2026-09-12): TOATE facturile de comision existente,
n = 5, decembrie 2025 – aprilie 2026. `data_doc` = ultima zi calendaristică a lunii
acoperite în 5 din 5 cazuri (31.12 · 31.01 · 28.02 · 31.03 · 30.04), zero abateri,
zero date neparsabile. Tranzacțiile derivate au primit `period_month` = luna
acoperită, 5/5.

✅ CONFIRMAT PE FACTURA TIPĂRITĂ (Bolt RO1126-158556, august 2026).
   Prima versiune a acestui modul avertiza că perioada acoperită nu e citită de pe
   factură, ci dedusă de extracția AI din aceeași poză din care vine și data — deci
   un martor, nu doi, și 5/5 ar fi putut fi tautologie. VERIFICAT PE FACTURA REALĂ:
   avertismentul NU se susține. Factura poartă „Perioada: 01.08.2026 - 31.08.2026"
   ca RÂND PROPRIU, repetat și în descrierea liniei. Perioada acoperită e un fapt
   tipărit de furnizor, nu o inferență a modelului, iar tiparul „data = ultima zi a
   perioadei" e confirmat LA SURSĂ. Limita a căzut; 5/5 e tipar, nu consecvență de
   extracție.

⚠️ LIMITA 1 — TRIPWIRE-UL E UN PROXY CONSERVATOR, NU SEMNALUL EXACT.
   Ce ar rupe cu adevărat termenul e ca `data_doc` să cadă în AFARA perioadei
   acoperite. Noi nu putem verifica asta: perioada e tipărită pe factură, dar NU o
   captăm în nici un câmp (`documents` are doar `data_doc`). Predicatul „ultima zi a
   lunii" e deci un proxy — și asta e alegerea corectă despre modul de eșec: cât timp
   data e ultima zi a lunii sale, echivalarea „lună a datei = perioadă acoperită" se
   susține pe tiparul confirmat; în orice alt caz nu mai avem cum s-o susținem, deci
   sunăm. Va suna și pentru o factură de mijloc de lună inofensivă (fals pozitiv
   ieftin: un rând de audit), dar nu va tăcea pentru una periculoasă.
   Semnalul exact ar cere captarea intervalului tipărit. Nu o facem acum — ar fi
   extracție nouă + migrare, pentru o problemă care azi nu se manifestă.

⚠️ LIMITA 2 — DRUMUL UBER E NETESTAT CU DATE REALE.
   Măsurătoarea NU acoperă ambele platforme. În producție nu a intrat NICIODATĂ o
   factură Uber: zero documente (pe orice status), zero tranzacții cu `counterparty`
   Uber, zero `vat_id` olandez — toate cele 5 facturi sunt Bolt (`EE102090374`).
   Un user are `regim_nerezident_uber` configurat, dar fără nicio factură.
   Codul are drumul Uber cablat (split D100 per-brand, Uber B.V. / NL), însă cum
   DATEAZĂ Uber facturile de comision nu știm din date — doar din cod. Nici măcar
   veriga 1 nu e verificată la Uber: nu știm dacă Uber reține comisionul din curse
   la fel ca Bolt sau facturează pentru plată separată. Confirmarea de mai sus e pe
   o factură BOLT; nu o extinde la Uber. Dacă Uber emite în luna următoare celei
   acoperite, scenariul de întârziere devine real la cea dintâi factură Uber, iar
   acest tripwire e singurul care o va spune.

⚠️ LIMITA 3 — TEXTELE DIN UI MINT ÎN CONTINUARE, CU BUNĂ ȘTIINȚĂ.
   „Doar lunile cu factură de comision" apare în ~20 de locuri (`fiscal_calendar`
   câmpurile `conditie_extra`/`cand`/`cui_se_aplica`, `MONTHLY_DEADLINES`,
   `dashboard.html`). NU le-am aliniat la lege: n-are rost să promitem în text un
   declanșator pe care codul nu-l urmează. Se aliniază când se repară declanșatorul
   — ceea ce acum e POSIBIL (perioada e tipărită pe factură, deci captabilă), dar
   rămâne o decizie separată: extracție nouă + migrare.

═══════════════════════════════════════════════════════════════════════
CÂMPURI PE FACTURA REALĂ CARE NU EXISTĂ LA NOI — CONSEMNATE, NECAPTATE
═══════════════════════════════════════════════════════════════════════

Văzute pe Bolt RO1126-158556 (august 2026). NU le captăm acum, dinadins — azi n-au
efect. Scrise aici ca să nu fie redescoperite ca noutate:

  • „Perioada: 01.08.2026 - 31.08.2026" — intervalul acoperit, rând propriu. Ar fi
    declanșatorul EXACT pentru D301/D390 (exigibilitatea se leagă de prestare, nu de
    emitere) și ar transforma tripwire-ul din proxy în verificare reală (vezi LIMITA 1).

  • „Data scadentă" — la 7 zile după emitere. Emiterea fiind în ultima zi a perioadei,
    scadența cade MEREU în luna URMĂTOARE celei acoperite. Azi fără efect, fiindcă
    „De plătit" e 0,00 lei: comisionul e deja reținut, scadența e formală. Ar conta la
    o factură cu sumă reală de plătit — acolo scadența (nu emiterea) ar fi momentul
    plății, deci declanșatorul D100 — și ar cădea în ALTĂ lună decât cea pe care o
    calculăm noi. Adică exact ruptura pe care o păzim, pe o altă cale.

  • „Taxe restante pe zi 0,5%" — penalitatea contractuală a furnizorului pentru
    întârziere. Distinctă de majorările ANAF (0,02%/zi, în `penalty_info` la D100).
    Azi inaplicabilă (nimic de plătit). Dacă apare vreodată o factură cu sumă reală,
    e un cost pe care userul ar trebui să-l vadă.

Nota comună a celor trei: toate devin relevante ÎN ACELAȘI CAZ — o factură de comision
cu „De plătit" > 0. Cât timp Bolt reține din curse, niciuna nu are efect fiscal.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional

# Motivele unei abateri — string-uri stabile, ca să fie interogabile în audit_logs.
MOTIV_NU_E_ULTIMA_ZI = "NU_E_ULTIMA_ZI_A_LUNII"
MOTIV_DATA_LIPSA = "DATA_FACTURII_LIPSA"

# `action` scris în audit_logs. Interogare pentru „a tras vreodată?":
#   SELECT * FROM audit_logs WHERE action = 'DECLANSATOR_FACTURA_ATIPIC';
ACTIUNE_AUDIT = "DECLANSATOR_FACTURA_ATIPIC"


@dataclass(frozen=True)
class AbatereDeclansator:
    """
    O factură de comision care NU respectă tiparul pe care se sprijină coincidența
    dintre luna facturii și luna plății/exigibilității.

    `nota` e gata de pus în log și în `audit_logs.note` (max 500 car. la scriere).
    """
    motiv: str
    data_factura: Optional[date]
    ultima_zi_a_lunii: Optional[int]
    nota: str


def este_ultima_zi_a_lunii(d: date) -> bool:
    """
    True dacă `d` e ultima zi calendaristică a lunii sale.

    Folosește `calendar.monthrange` — corect pe februarie bisect (29.02.2024 = ultima
    zi) și nebisect (28.02.2026 = ultima zi), fără tabel de zile scris de mână.
    """
    return d.day == calendar.monthrange(d.year, d.month)[1]


def verifica_factura_comision(
    occurred_on: Optional[date],
) -> Optional[AbatereDeclansator]:
    """
    Tripwire-ul. `None` = tiparul ține, nu spunem nimic. `AbatereDeclansator` =
    presupunerea a căzut pentru factura asta, lăsăm urmă.

    NU blochează, NU corectează, NU mută nicio lună — doar raportează. Motivul e în
    docstring-ul modulului: declanșatorul implementat („factura") diferă de cel legal
    (plata venitului / exigibilitatea), iar cele două coincid doar cât timp furnizorul
    datează factura în ultima zi a perioadei.

    Două feluri de abatere:
      • `MOTIV_NU_E_ULTIMA_ZI` — data există dar e în interiorul lunii (sau în luna
        următoare celei acoperite). Aici se rupe coincidența.
      • `MOTIV_DATA_LIPSA` — n-avem dată deloc (extracție eșuată / format neparsat de
        `posting._parse_occurred_on`). Atunci `period_year`/`period_month` rămân None
        și obligația nu apare în NICIO lună — o tăcere mai gravă decât o lună greșită,
        deci tot o vrem zgomotoasă.
    """
    if occurred_on is None:
        return AbatereDeclansator(
            motiv=MOTIV_DATA_LIPSA,
            data_factura=None,
            ultima_zi_a_lunii=None,
            nota=(
                "Factură de comision fără dată utilizabilă: perioada fiscală "
                "(period_year/period_month) rămâne NULL, deci D100/D301/D390 nu apar "
                "în nicio lună. Verifică extracția și data_doc."
            ),
        )

    ultima = calendar.monthrange(occurred_on.year, occurred_on.month)[1]
    if occurred_on.day == ultima:
        return None

    return AbatereDeclansator(
        motiv=MOTIV_NU_E_ULTIMA_ZI,
        data_factura=occurred_on,
        ultima_zi_a_lunii=ultima,
        nota=(
            f"Factură de comision datată {occurred_on.strftime('%d.%m.%Y')}, care NU e "
            f"ultima zi a lunii ({ultima}). Tiparul pe care se sprijină luna alertei "
            f"s-a rupt: luna facturii nu mai garantează luna plății (D100, art. 224 "
            f"alin. 5) sau a exigibilității (D301/D390, art. 324 alin. 2). Verifică "
            f"dacă termenul semnalat e cel legal."
        ),
    )
