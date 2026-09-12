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

CE FACE COINCIDENȚA SĂ ȚINĂ AZI
───────────────────────────────
Bolt datează factura de comision în ULTIMA ZI a lunii pe care o acoperă. Comisionul
e reținut din curse în timpul lunii, deci plata curge în interiorul aceleiași luni,
iar exigibilitatea se naște tot acolo. Când factura e datată 31.01, toate trei
declanșatoarele — factură, plată, exigibilitate — cad în ianuarie și dau același
termen: 25 februarie. De asta sistemul e corect azi, în ciuda declanșatorului greșit.

E un OBICEI DE FURNIZOR, nu o regulă. Nimic din codul nostru nu-l impune și nimeni
nu ne anunță dacă Bolt începe să emită pe 03.02 pentru ianuarie. În ziua aceea
`period_month` devine februarie → D100 semnalat pe 25 martie, în timp ce venitul a
fost plătit în ianuarie → termenul legal era 25 februarie. O lună de ÎNTÂRZIERE,
apărută în tăcere.

Modulul nu repară declanșatorul și nu mută nicio lună. Face doar ca ziua în care
presupunerea cade să fie ZGOMOTOASĂ: o abatere de la tipar lasă urmă în log și în
`audit_logs`, ca s-o aflăm de la cea dintâi factură atipică, nu de la prima amendă.

═══════════════════════════════════════════════════════════════════════
MĂSURĂTOAREA PE CARE SE SPRIJINĂ — ȘI LIMITELE EI
═══════════════════════════════════════════════════════════════════════

Măsurat pe baza de producție (2026-09-12): TOATE facturile de comision existente,
n = 5, decembrie 2025 – aprilie 2026. `data_doc` = ultima zi calendaristică a lunii
acoperite în 5 din 5 cazuri (31.12 · 31.01 · 28.02 · 31.03 · 30.04), zero abateri,
zero date neparsabile. Tranzacțiile derivate au primit `period_month` = luna
acoperită, 5/5.

⚠️ LIMITA 1 — NU SUNT DOI MARTORI, E UNUL.
   Perioada acoperită NU e citită de pe factură. Nu există în baza noastră nici un
   câmp cu intervalul facturat: `raw_json` e ecoul extracției (aceleași câmpuri care
   s-au scris în coloane), fără dată de început/sfârșit. „Comision Bolt ianuarie
   2026" este `detalii` — TEXT LIBER produs de modelul de extracție, citind ACEEAȘI
   poză din care a citit și `data_doc`. Cele două nu se confirmă reciproc: sunt o
   singură citire AI, raportată de două ori. Consecvența 5/5 dovedește că extracția
   e stabilă, NU că factura spune asta.
   Al doilea martor independent nu există: `source_files` n-are nume de fișier (doar
   `kind`/`telegram_file_id`/`sha256`/`mime`), iar pozele stau la Telegram, nu la noi.
   DE VERIFICAT cu facturile pe hârtie: există pe factura Bolt un interval tipărit
   („Period: 01.01.2026 – 31.01.2026")? Dacă nu, „ianuarie 2026" e inferența modelului
   din data facturii, și atunci 5/5 e tautologie, nu dovadă.

⚠️ LIMITA 2 — DRUMUL UBER E NETESTAT CU DATE REALE.
   Măsurătoarea NU acoperă ambele platforme. În producție nu a intrat NICIODATĂ o
   factură Uber: zero documente (pe orice status), zero tranzacții cu `counterparty`
   Uber, zero `vat_id` olandez — toate cele 5 facturi sunt Bolt (`EE102090374`).
   Un user are `regim_nerezident_uber` configurat, dar fără nicio factură.
   Codul are drumul Uber cablat (split D100 per-brand, Uber B.V. / NL), însă cum
   DATEAZĂ Uber facturile de comision nu știm din date — doar din cod. Dacă Uber
   emite în luna următoare celei acoperite, scenariul de întârziere de mai sus devine
   real la cea dintâi factură Uber, iar acest tripwire e singurul care o va spune.

⚠️ LIMITA 3 — TEXTELE DIN UI MINT ÎN CONTINUARE, CU BUNĂ ȘTIINȚĂ.
   „Doar lunile cu factură de comision" apare în ~20 de locuri (`fiscal_calendar`
   câmpurile `conditie_extra`/`cand`/`cui_se_aplica`, `MONTHLY_DEADLINES`,
   `dashboard.html`). NU le-am aliniat la lege: n-are rost să promitem în text un
   declanșator pe care codul nu-l urmează. Se aliniază când se repară declanșatorul,
   adică după ce știm intervalul tipărit pe factură (LIMITA 1).
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
