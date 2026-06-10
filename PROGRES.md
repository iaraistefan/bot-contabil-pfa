# PROGRES — Contai (bot contabil PFA ridesharing)

> Document de stare + handoff. Citește-l la începutul fiecărei sesiuni noi de
> dezvoltare (Claude Code nu păstrează memoria între sesiuni).
> Ultima actualizare: 2026-06-09.

---

## CE E PRODUSUL

**Contai** = bot Telegram (`@contabilPFA_bot`) + dashboard web (Flask) pentru
contabilitate PFA ridesharing (Bolt/Uber). Deploy pe Render
(`bot-contabil-pfa.onrender.com`), repo `iaraistefan/bot-contabil-pfa`.

Stack: Python 3.13, python-telegram-bot, OpenAI GPT-4o, SQLAlchemy, Postgres,
Flask, APScheduler. Multi-tenant (izolare pe `user_id`), activity-aware
(`BaseActivity` plug-in pentru multi-CAEN).

**Utilizator principal:** Stefan (PFA ridesharing Bolt, Bistrița). Are certificat
de rezidență fiscală de la Bolt → impozit nerezident 2% (nu 16%). Are token eToken
+ DUKIntegrator local pentru semnare/depunere declarații.

---

## CONTEXT FISCAL CONFIRMAT (nu schimba fără verificare)

- **CUI PFA** `53067338` → impozit (D100, D212)
- **Cod special TVA art. 317** `53148882` → D301, D390 (taxare inversă Bolt)
- Furnizor: BOLT OPERATIONS OU, Estonia (EE), VAT EE102090374
- **Cota TVA:** 21% din 01.08.2025; 19% până la 31.07.2025. Sursă unică în cod:
  `app/domain/tax_rules.cota_tva(data)`.
- **D100 nerezident (poz. 634):** OBLIGATORIU lunar pentru comisionul Bolt, cota 2%
  cu certificat de rezidență. Impozitul se plătește din buzunar, suplimentar față
  de comisionul Bolt (nu se scade din ce plătești la Bolt). Se depune doar lunile
  cu factură Bolt, termen 25 a lunii următoare. Plus D207 anual (28 feb).
- **Uber (Olanda) — DIFERIT:** scutit cu certificat (art. 7 CDI), dar se declară în
  D207. Relevant când extindem la Uber.

---

## PASUL ANAF — ÎNCHIS (validat empiric + semnat)

Toate cele 4 declarații funcționează end-to-end (dashboard + Telegram), o singură
sursă: `app/integrations/anaf/declaratii_service.py`. Validate în DUKIntegrator
și semnate cu eToken:

- **D390** (VIES): namespace v3. ✅
- **D301** (decont special TVA): namespace **v1** (confirmat empiric). Structură:
  fiecare factură Bolt scrie DOUĂ rânduri — tip_operatie=4 (S4) + tip_operatie=5
  (S4.1), ambele cu aceeași bază. ✅
- **D100** (impozit nerezident poz. 634): namespace **v2**. Element `<obligatie>`,
  atribut `d_anulare`, cod_bugetar `20470101`. ✅
- **D212** (Declarația Unică, calcul anual): doar în dashboard. ✅

> ⚠️ `d301_generator.py` și `d100_generator.py` sunt cod VALIDAT empiric în
> DUKIntegrator și semnat. NU modifica structura XML / namespace fără re-validare.

---

## PROBLEME CRITICE (Faza 0)

STATUS: ✅ FAZA 0 ÎNCHISĂ COMPLET (2026-06-04). Toate cele 3 probleme critice
rezolvate. 46 teste automate (15 TVA + 31 contribuții). Următor: Faza 1.

### ✅ #1 — D100 obligatoriu lunar (REZOLVAT, commit a8e66c5)
Avertismentul greșit „Bolt suportă 2% → plată 0" eliminat. Acum
`suma_de_plata = suma_datorata` mereu; param `suportat_de_bolt` DEPRECATED fără
efect; avertismente aliniate la realitate.

### ✅ #2 — TVA centralizat pe dată (REZOLVAT, commituri e258778 + 68abf4d)
Eliminat `0.21` hardcodat din TOATE locurile. Sursă unică
`tax_rules.cota_tva(data)`. Backend (`compute_period`) calculează cota o dată per
perioadă, o pune în payload; toți consumatorii o citesc → coerență bază↔TVA
garantată. 15 teste în `tests/test_cota_tva.py`, toate verzi. `d301_generator`
delegat fără a atinge structura XML (echivalență numerică verificată).
Lăsat intenționat: enunțul informativ din `prompts.py:33` („COTA TVA STANDARD: 21%").

### ✅ #3 — CAS/CASS sursă unică (REZOLVAT, commit 6b0910e)
Consolidat 5 locuri în app/domain/contributii.py (modul pur, params per an,
SMB 2026=4050 — valoarea de la 1 ian pentru plafoane PFA). Reparate 2 bug-uri
în tax_calculator: CASS sub 6 SMB (era 0, acum minim real) și escaladare CAS
la 24×. D212 real bit-identic (diff 0). 31 teste noi.

---

## DUPĂ FAZA 0 — PLAN STRATEGIC

Ordinea convenită cu Stefan (principiu: întâi produsul perfect pentru EL, apoi
extindere):

- **Faza 1 — Produsul perfect pentru Stefan (PFA ridesharing Bolt):**
  - Interfața web (dashboard) să-i placă 100% (design, flux, ce vede)
  - Extindere teste automate (regresii fiscale prinse automat)
- **Faza 2 — Pregătit pentru colegi Bolt (multi-tenant real):**
  - Recunoaște fiecare CUI + CAEN al fiecărui utilizator
  - Onboarding pentru un coleg nou de la zero
  - Fundația există deja: `activity_from_caen`, `BaseActivity` plug-in, izolare `user_id`
- **Faza 3 — Extindere:** alte activități / coduri CAEN / SRL-uri.

### Opționale notate (neconstruit)
- **D207** (informativă anuală nerezidenți, 28 feb) — nu există generator.
- Ghid pas-cu-pas în bot pentru fluxul DUKIntegrator → semnare → SPV.
- Cleanup exemple demo `__main__` din `d100_generator.py` (apelează cu
  `suportat_de_bolt=True`, acum ignorat — inofensiv, dar de curățat).

---

## FAZA 1 — REDESIGN DASHBOARD (în curs)

### Bucata #1 — Termeni pe românește (ÎNCHISĂ)
- `50c8fa7`: backend `labels_ro.py` (sursă unică etichete RO), `/transactions`
  trimite câmpurile `_ro`, 26 teste.
- `766935d`: frontend afișează `category_ro` în activitate + registru, fallback sigur.

### Bucata #2 — Cardul "Cât plătesc și când?" (ÎNCHISĂ)
- `8fdacc5`: card-erou full-width sus pe overview + termene reale (eliminat demo
  hardcodat); 4 stări (plată / restanță / declarative / gol).
- `6d84c01`: fix D700 fals pozitiv (gardă `has_cod_special_tva` în `_is_aplicabil`),
  4 teste.
- `d9a3459`: suma reală D212 din helper partajat `compute_d212_anual` (tax_engine)
  — card == declarație == declarația depusă; an = `termen.year − 1`; 3 cazuri
  (venit pozitiv / pierdere / an gol → "estimare în curs"); echivalență diff-0 pe
  `/declaratie-unica`; `conftest.py` env dummy; 6 teste.

### Bucata #3 — Finalizare (ÎNCHISĂ)
- `0ef43ba`: badge "Calendar fiscal" real (nr. obligații urgente ≤7 zile, roșu la
  restanță, ascuns la 0); brand "Contai" pe texte user-facing (welcome onboarding +
  status); fix card D100 pe pagina TVA (din "posibil 0, suportat de Bolt" — model
  greșit ce contrazicea Faza 0 — în "de depus" + sumă reală 2% × comision + text
  corect). Nume afișat bot ("CONTABIL PFA" → "Contai") se schimbă manual din BotFather.

Suita: **82/82** teste verzi (la închiderea Fazei 1).

---

## FAZA 2 — ARHIVĂ DOCUMENTE (Cloudflare R2) — ÎNCHISĂ

Bucket privat **`cantai-arhive`** (atenție: „cantai" cu A; env `R2_*` în Render).
Uploadurile noi se arhivează în R2; istoricul pre-R2 e pierdut (disk efemer pe
Render). R2 = S3-compatible (boto3 cu endpoint custom). Confirmat end-to-end în
prod (bon Lukoil doc 107 → `cantai-arhive/user_1/2026/06/<sha>.jpg`). 5 pași:

- `fcade4d` (PAS 1): `storage.py` backend R2 + fallback disk + `get_bytes`
  (boto3 lazy; `_r2_enabled` din `os.environ`, nu Settings). 7 teste (R2 mock).
- `c7f09d5` (PAS 2): aprindere R2 — `register_source_file` pasează `user_id`+`dt`;
  cheie `user_<id>/<an>/<lună>/<sha>.<ext>` (data upload). Dedup (în DB înainte de
  save) + procesarea AI (pe bytes din memorie) NEATINSE. 2 teste integrare.
- `d9b6c6e` (PAS 3): `boto3>=1.34,<2.0` + pin `pydantic>=2.7,<2.12` în requirements.
- `eeb7f10` (PAS 4): rută download `/api/v1/documents/<id>/file` — ownership STRICT
  (filtru `user_id`), stream din R2, 404 prietenos. 5 teste Flask.
- `d6a8eef` (PAS 5): pagina Documente — arhivă grupată pe an/lună (din `data_doc`)
  + buton download per document (doar dacă `has_file`), pattern authFetch→blob.

Suita: **97/97** teste verzi.

**Grupare cheie R2 vs afișaj:** cheia R2 e pe **data upload** (`created_at`, singura
known la save); gruparea în pagina Documente e pe **data fiscală** (`data_doc`).

---

## FAZA 3 — FUNCȚII AVANSATE (în curs)
Direcție: „cel mai complex tool" (concurăm cu Pick/SOLO).

### Sumar lunar automat pe Telegram (ÎNCHIS)
Job nou care, **ziua 2 la 09:00**, trimite fiecărui user cu activitate **bilanțul
lunii ÎNCHEIATE** (`format_report_message`) + linia „💳 De plătit acum" (obligații
cu sumă > 0, din `get_obligations_for_user`; perioada = luna încheiată → termenul
cade în luna curentă). 5 pași:
- `7efdf79` (PAS 1): tabel `summary_sent` (gardă anti-dublură, unicitate DB pe
  user/an/lună) + migrația `010_monthly_summary` (idempotentă).
- `1459028` (PAS 2+3): `luna_precedenta` (wrap ian→dec) + `run_monthly_summary`
  (izolare per-user, gardă verificată înainte / scrisă DOAR după trimitere reușită,
  skip lună goală, linie de plată robustă). `_send_telegram_message` → bool (aditiv).
- `ca5292d` (PAS 4): înregistrare job în `start_scheduler` (day=2, hour=9,
  `id="monthly_summary"`); cele 5 joburi existente neatinse.
- `06495be` (PAS 5): comanda **`/sumar_test`** owner-only (preview DOAR owner-ului,
  NU atinge `summary_sent`, repetabil) + `build_summary_for_user` = **sursă unică** a
  mesajului (job + comandă produc EXACT același text).

### Corecții cifre fiscale (sumar + /raport) — ÎNCHISE
Verificarea pe telefon a scos 2 probleme (cifre fiscale = critic), ambele rezolvate
prin **sursă unică `compute_d212_anual`** (aceeași ca dashboard-ul + declarația):
- `18c0d3d` (#1): `/raport` + sumarul afișau CAS/CASS dintr-o proiecție 1-lună×12
  (absurd: „CASS 2430 anual lângă profit lunar 182"). Acum secțiunea fiscală e pe
  **realizat YTD** (`format_report_message(totals, d212=)` + `_format_d212_section`:
  separator + „Venit net realizat ian–{lună}" + impozit/CAS/CASS + caveat). Cei 2
  apelanți (`execute_raport`, `build_summary_for_user`) pasează `d212`. Bilanțul
  lunar neatins. **Confirmat pe telefon: sumar == dashboard == D212.**
- `4c72366` (#2): D212 apare acum în linia „💳 De plătit acum" — DOAR în fereastra
  termenului (status ≤ PROXIM, ≤30 zile/overdue) → ~2 sumare/an. Suma reală din
  `compute_d212_anual(an=termen.year−1)`; DEPASIT marcat ca restanță.

Suita: **127/127** teste verzi.

### Alerte „aproape de plafon" (TVA + CAS 12/24 + CASS 60) — COMPLETE
Avertizare PROACTIVĂ înainte de a trece praguri fiscale (ce Pick/SOLO nu fac), în
jobul zilnic existent. Sursă unică `compute_d212_anual` + `vat_threshold_status` +
`prag_cas_status`. 3 pași:
- `865ac0f` (PAS 1): `contributii.prag_cas_status(venit_net, an)` — status față de
  pragul CAS 12 SMB (48.600) + `remaining_ron` + message. Aceeași formă ca
  `vat_threshold_status`. 10 teste.
- `12a8cb5` (PAS 2): pre-check ieftin `_ytd_income_brut` (un SUM, NU 12×
  `compute_period`); gate `PLAFON_PRECHECK_RON = 38.880` (0.8 × CAS 12 SMB). 4 teste.
- `26b131a` (PAS 3): `_check_plafon_alerts` în `_process_user_alerts` (după
  obligații, în try/except per-user). Pre-check → `compute_d212_anual` → TVA (doar
  neplătitor) + CAS. Anti-spam `fiscal_alert_sent` (PLAFON_TVA/PLAFON_CAS, an,
  `period_month=0`, `prag_80`/`prag_depasit`): marcat DOAR pe succes; escaladare
  80%→100% = alertă nouă. Mesaje cu suma rămasă + caveat uniform. 10 teste.

- `e134813` (extensie): `_prag_core` (matematica comună, DRY) + `prag_cas24_status`
  (97.200, 24 SMB — baza CAS se DUBLEAZĂ, mesaj „rău" 🔴) + `prag_cass60_status`
  (243.000, 60 SMB — CASS plafonat, mesaj informativ ℹ️ „rămâne de plată integral,
  nu mai crește"; NU felicitare). `prag_cas_status` refactorizat pe core (cele 10
  teste verzi, echivalență). `_check_plafon_alerts` +2 alerte (PLAFON_CAS24/CASS60,
  anti-spam independent). Gate 38.880 (cel mai mic prag) acoperă toate. 23 teste.

**Toate cele 4 praguri fiscale relevante PFA acoperite: TVA 300k + CAS 12 SMB
(obligatoriu) + CAS 24 SMB (baza dublă) + CASS 60 SMB (plafonare).** Sistemul de
alerte de plafon e COMPLET — ceva ce Pick/SOLO nu fac.

Suita: **180/180** teste verzi.

⚙️ **De setat în Render:** `OWNER_TELEGRAM_ID` = telegram_id-ul lui Stefan (din
@userinfobot). Nesetat → `/sumar_test` e inert pentru toți (fail-safe).

---

### Import extras bancar BT (PDF) — FELIA 1 ÎNCHISĂ
Userul încarcă extrasul BT (PDF) → botul recunoaște tranzacțiile și le afișează.
Felia 1 = doar parsing + preview (ZERO scriere registru / clasificare / match).
Ceva ce Pick/SOLO nu fac. 2 pași:
- `8f1405e` (PAS 1): parser determinist BT. `app/integrations/imports/bank_statement.py`
  — format NEUTRU `BankTxn {data, suma, directie IN/OUT, descriere}` + `BankStatementError`
  (granița curată: conducta vede doar `BankTxn`; bancă nouă = parser nou). `bt_parser.py`
  — `parse_bt_pdf(bytes) -> list[BankTxn]`: extracție pe COORDONATE (suma clasificată după
  banda x a coloanei Debit/Credit; zgomotul din descriere → ignorat) + grupare multi-linie
  + stop la `RULAJ TOTAL CONT` + carry-forward dată. **AUTO-CHECKSUM**: sum(OUT)/sum(IN) vs
  RULAJ TOTAL CONT; nepotrivire/lipsă → `BankStatementError` (NU date parțiale tăcut).
  Determinist pe bani, fără AI. Fixture anonimizat (re-plasare la coordonate originale →
  benzi x neschimbate; zero scurgeri) + utilitar generare. 15 teste golden (count 34,
  OUT 769.77 / IN 1.019,45 = checksum, spot-check, negativ zgomot+solduri). `+pdfplumber`.
- `92a9fad` (PAS 2): handler `handle_bank_statement_wrapper` pe `filters.Document.PDF`
  (izolat, înainte de PHOTO → foto/text bit-identice). Gărzi: onboarding/PDF/mărime 10 MB/
  ensure_user. Download → `register_source_file(kind="bank_statement")` → `parse_bt_pdf` →
  preview (`_format_bank_preview`+`_fmt_ron`, format RO): count + încasări/plăți + „verificat
  cu totalul extrasului" + primele tranzacții + disclaimer „doar afișare". Eroare → mesaj
  clar, fără date parțiale. 4 teste preview.

Suita: **199/199** teste verzi.

**TODO viitor (felia 1 — extensie multi-bancă):** detecție automată bancă + registru
parsere + profil bancă per user (acum doar BT; granița `BankTxn` e pregătită).

---

### Import extras bancar BT — FELIA 2 ÎNCHISĂ (clasificare + preview grupat)
Peste preview-ul feliei 1, botul **clasifică** fiecare tranzacție într-un bucket de
nivel-extras și afișează un mini-raport grupat. **DETERMINIST, ZERO AI / ZERO scriere
registru** (clasificarea pe „ce e clar"; ce e ambiguu → `DE_VERIFICAT`, userul decide).
3 commituri (PAS 1 + hotfix + PAS 2):
- `038b3ad` (PAS 1): `app/integrations/imports/classify.py` — strat separat peste `BankTxn`
  (parserul rămâne pur). `BankTxnClasificat {txn, bucket, categorie, deductibil, incredere,
  eticheta}`. `classify_bt(txn, activity)` pur, determinist, **6 buckete** cu precedența
  `RETURNARE → PLATA → COMISION → BOLT(IN) → BUSINESS(OUT) → DE_VERIFICAT` (direcția IN/OUT
  dezambiguizează returnare↔plată). **Reutilizează** `activity.detect_expense_category` +
  `get_deductibility_pct` (classmethod, identic cu `posting.py` — NU clasificator paralel).
  Etichete RO corecte fiscal (hint obligație TVA/Impozit+lună). Vocabular separat: bucket
  (ce e) ≠ `incredere` SIGUR/INCERT (cât de sigur). 19 teste.
- `621ac5f` (hotfix): **fals-pozitiv prins pe extrasul REAL** — BT scrie zgomotul lipit
  („comision tranzactie 0.00RON", fără spațiu), denoise cerea `\s+ron` → „comision"
  supraviețuia → 6 plăți POS către persoane fizice marcate fals `platform_commission`
  deductibil 100%. Fix `\s+→\s*`. Testul sintetic mințea („0.00 RON" cu spațiu) → corectat
  la formatul real + test regresie pe string-ul exact + **golden pe FIXTURE REAL**
  (3 Bolt/8 plăți/8 returnări/9 comisioane/0 business/6 de verificat=34). Lecție: testul
  sintetic mințea, datele reale au spus adevărul. 23 teste.
- `e2bc1de` (PAS 2): integrare preview. Handler → `get_activity_for_user(user_id)` (sursă
  unică, ca `post_document`) → `classify_bt` → `_format_bank_preview(list[BankTxnClasificat])`
  (rămâne PUR). Mini-raport grupat pe buckete (sume+count, grupuri goale sărite); **Venit
  Bolt SEPARAT de returnări**; linia **„net 0" CONDIȚIONATĂ** (doar când returnări==plăți;
  altfel neutru „nu venit nou" — pe bani nu afirmăm fals). Disclaimer păstrat. Randat pe
  extrasul real = design aprobat. 9 teste preview.

Suita: **227/227** teste verzi.

---

### Import extras bancar BT — FELIA 3 ÎNCHISĂ (postare cheltuieli în registru)
Extrasul scrie EFECTIV în registru — dar DOAR cheltuielile business, cu confirmare
per-tranzacție și anti-dublură. Prima cale de SCRIERE din import. 6 commituri (1+2+3+4a+4b):
- `5494e6d` (PAS 1): params aditivi keyword-only în `post_document` + `tx_repo.create`:
  **`category_override`** (onorează clasificarea felia 2, NU re-clasifică pe text brut →
  fals-pozitivul „0.00RON" devine STRUCTURAL imposibil pe scriere) + **`import_fingerprint`**.
  Threadati EXCLUSIV în `_post_cheltuiala` → ramurile VENIT/FACTURA zero modificări → foto+Bolt
  bit-identice. +coloană `Transaction.import_fingerprint` + migrația `011`. 8 teste.
- `04cf0c8` (PAS 2): `dedup.py` pur — `normalize_descriere` (FROZEN, independent de
  `classify._denoise` — fingerprint = contract persistent) + `fingerprint(txn, ocurenta)` +
  `compute_fingerprints` (tiebreaker pe linii identice) + `exists_fingerprint`. SAFE-BY-DEFAULT:
  REF/RRN NU în hash (neverificate ca stabile). Golden 34→34 unice pe fixture real. 9 teste.
- `e451673` (PAS 3): `post_bank.py` — `post_bank_expenses` orchestrare pură (nu comite).
  **Gardă structurală** `_POSTABILE={CHELTUIALA_BUSINESS, DE_VERIFICAT}` — VENIT_BOLT (dublează
  sync) / PLATA / RETURNARE / COMISION refuzate STRUCTURAL, chiar dacă UI le-ar cere. Per linie:
  fingerprint → skip dublură : Document + `post_document(override, fingerprint)`. 5 teste.
- `663c3f5` (PAS 4a): `bank_import_ui.py` logică PURĂ — state machine (anti-stale) + text
  builders + `build_decisions` (gardă: categorie doar pe `POSTABLE_BUCKETS`, sursă unică din
  post_bank). UI filtrează, garda serviciului = backup (defense-in-depth). 10 teste.
- `92748d0` (PAS 4b): glue async + commit. **Gaura orfană** găsită+reparată: `post_document`
  înghite excepții→`[]`→Document orfan; `post_bank_expenses` tratează `[]` ca eșec→raise
  (`post_document` NEATINS). **`finalize_bank_post`** (sync, testabil): UN commit la final /
  rollback pe orice excepție = **TOT-SAU-NIMIC**, zero scriere parțială. Handler aditiv
  (`_format_bank_preview` neatins) + buton + router `bankpost`. 6 teste.

Suita: **265/265** teste verzi.

Flux: extras PDF → parser (felia 1) → clasificare (felia 2) → buton „Adaugă cheltuielile" →
confirmare per `DE_VERIFICAT` (business+categorie / personală / sari) → postare TOT-SAU-NIMIC
cu dedup. Doar `CHELTUIALA_BUSINESS` + `DE_VERIFICAT`-confirmat; venit Bolt/decontări excluse.

---

### Import extras bancar BT — FELIA 4 ÎNCHISĂ (reconciliere de prezență venit Bolt)
Reconul a scos verdictul ONEST: „anti-dublură" e nume impropriu — dublura de venit e DEJA
imposibilă (felia 3 exclude `VENIT_BOLT` din postare; venitul vine exclusiv din sync). Și
reconcilierea PE SUMĂ e o capcană: depunerile bancare Bolt sunt NETE, sync-ul postează pe
BRUT (diferă cu comisionul) + payout săptămânal ≠ lună calendaristică → potrivirea de sume
ar da false-alarme dese. Deci felia 4 = reconciliere de PREZENȚĂ (factuală, nu pe sumă).
2 commituri:
- `7f76990` (PAS 1): `bolt_reconcile.py` — `bolt_months_in_statement` (pur: lunile cu
  `VENIT_BOLT` din extras) + `bolt_reconcile_nudge` (nudge dacă o lună are Bolt în extras dar
  fără venit sincronizat; None = tăcere când tot sincronizat). **Refactor sursă unică:** filtrul
  de prezență Bolt extras din `_remove_existing_bolt_income` inline într-un `has_bolt_income`
  partajat (folosit de AMBELE: înlocuire re-`/bolt` ȘI reconciliere). Text NEUTRU („nu apar încă
  sincronizate") + notă „depunerile bancare sunt nete, nu brute". 9 teste (+2 regresie
  `_remove_existing_bolt_income` neschimbat). Edge fals-pozitiv timing payout acceptat conștient.
- `142f15b` (PAS 2): wiring în handler — `safe_reconcile_nudge` (gardă try/except defensivă:
  reconcilierea e BONUS, o eroare DB NU strică preview-ul) + `append_nudge` la preview DOAR dacă
  ≠None. `_format_bank_preview` NEATINS (preview identic). 4 teste (append aditiv, regresie
  None→bit-identic, gardă defensivă ×2).

Suita: **278/278** teste verzi.

---

### Import extras bancar BT — FELIA 5a ÎNCHISĂ (compensare plată↔returnare taxe)
Prima felie din felia 5 (match plată↔obligație). Reconul a scos verdictul + cazul de aur:
`PLATA_TAXA`/`RETURNARE_TAXA` din extras sunt decontări de obligații (D301/D100), NU venit/
cheltuială. Riscul DOMINANT (dovedit pe extrasul real): **toate cele 8 plăți de taxe au fost
RESPINSE** (returnare-pereche, net 0) → obligațiile NU sunt achitate. Un match naiv „plată →
marchez achitat" ar fi marcat FALS obligații achitate = eroare fiscală. Deci felia 5a =
compensare ÎNAINTE de orice match. 2 commituri (pur, ZERO model/scriere):
- `8c646ce` (PAS 1): hint obligație STRUCTURAT din classify — `ObligatieHint` dataclass
  (tip/declarație/lună-int/an) + câmp `oblig` aditiv pe `BankTxnClasificat`. Refactor sursă
  unică `_oblig_hint` → `_oblig_label` (etichetă, format vechi) + `_oblig_parts` (structurat),
  o singură regex/call site. Etichetă BIT-IDENTICĂ (23 teste felia 2 verzi). 5 teste.
- `8042170` (PAS 2): `tax_payments.py` — `compensate(clasificate)` → plăți REALE. Grupare pe
  `(tip, declarație, lună, an, sumă)` (suma în cheie: 138 compensează doar 138); per grup
  `max(0, n_plăți − n_returnări)` (count-based, plăți fungibile; re-plată 2+1→1, NU „anulează
  tot"; returnări>plăți→0). Determinist. **Cazul de aur: pe fixture 8+8 → `[]`** (toate
  respinse → nimic achitat = adevărul fiscal). 8 teste.

Suita: **291/291** teste verzi.

### Import extras bancar BT — FELIA 5 (b→c) ÎNCHISĂ (match plată↔obligație + „achitat")
Restul feliei 5: persistă plățile reale + afișează „achitat". Obligația rămâne EFEMERĂ
(calculată on-the-fly); modelul stochează DOAR faptul plății. „Match-ul" = egalitatea cheii
`(cod, an, lună)` rezolvată de `has_payment` la afișare (nu algoritm separat). Decizie de UX
fermă: marcarea cere CONFIRMAREA userului (afirmație fiscală — nu auto). 4 commituri:
- `d048beb` (5b): model `ObligationPayment` + migrația `012` (CREATE TABLE idempotent). Schema:
  `(user, cod scurt, an, lună NOT NULL DEFAULT 0 sentinel anual, suma, data, sursă,
  import_fingerprint, source_file_id)`. UNIQUE `(user, fingerprint)` → anti-dublură re-import +
  permite tranșe. Float pe sumă (consistent cu tot sistemul). repo `create_payment` (check-then-
  insert) + `has_payment`. Fundație, ZERO consumator. 5 teste.
- `d12ce1e` (5c-a): serviciu PUR `record_tax_payments(clasificate, confirmed_fingerprints)`.
  Cheia = FINGERPRINT (stabil, nu index/id). **Garda compensare PESTE confirmare:** înregistrează
  doar `confirmed ∩ plăți REALE`; o plată respinsă confirmată din greșeală → refuzată structural.
  Refactor sursă unică `real_payment_indices` (compensate = wrapper, identic). 5 teste.
- `0225759` (5c-b): „✅ achitat" în sumarul „De plătit acum" (`scheduler._plata_line_text` +
  `_is_oblig_platita` gardă defensivă comprehensivă). Bază BYTE-IDENTICĂ; match pe `o.perioada_an/
  luna`; cod scurt `split()[0]`. 14 teste monthly_summary neatinse. 5 teste.
- `2be4f68` (5c-c-1) + `1aedaab` (5c-c-2): UI confirmare — `bank_tax_ui.py` (pur+sync:
  `format_tax_propose`/`format_tax_result`/`finalize_tax_recording` tot-sau-nimic) + glue async
  (`banktax|*`) + buton „Marchează taxele achitate (N)" condiționat `has_real_tax`. State
  `bank_tax_pending` separat. `build_preview_keyboard` — pe extrasul real (toate respinse →
  `has_real_tax=False`) e **bit-identic** cu butonul de cheltuieli → felia 5c-c INVIZIBILĂ. 14 teste.

Suita: **320/320** teste verzi. **Felia 5 COMPLETĂ** (compensare → model → serviciu → afișare → UI).

> **Pe extrasul real al lui Stefan: toate plățile de taxe au fost RESPINSE → 0 obligații
> marcate achitate = adevărul fiscal.** Tot lanțul (felii 1-5) îl produce corect; compensarea
> de-riscă scrierea (nu marchează achitat ce a fost respins).

**IMPORTUL EXTRAS BANCAR BT — COMPLET cap-coadă (felii 1-5):** PDF → parser determinist +
checksum (1) → clasificare deterministă pe buckete (2) → postare cheltuieli business cu dedup
fingerprint (3) → reconciliere prezență venit Bolt (4) → match plată↔obligație fiscală + „achitat" (5).

**Felii viitoare (opțional):** afișare „achitat" și în `/calendar` + dashboard web (5c-b a
țintit doar sumarul); D212 anual (perioada_luna sentinel cere normalizare); extensie multi-bancă
(detecție automată; granița `BankTxn` e pregătită).

---

## TODO HYGIENE (neurgent, transversal)
- ✅ Pin `pydantic` (`>=2.7,<2.12`) — FĂCUT (Faza 2 PAS 3, `d9b6c6e`).
- Centralizare cote pentru afișaj: D100 `baza*0.02` (dashboard) + duplicarea
  `COTA_TVA_STANDARD` din `fiscal_calendar.py` → o sursă unică de cote inclusiv
  pentru display (doar afișaj, nu calcul real).
- `datetime.utcnow()` (`bot_contabil.py:295`, din Faza 2 PAS 2) dă
  `DeprecationWarning` → de înlocuit cu `datetime.now(datetime.UTC)`.
- ✅ **Cache `compute_d212_anual` — FĂCUT** (`56fb4b9`). Cache in-memory validat prin
  FINGERPRINT `(count, max_id, sum(amount_brut))` pe filtrul identic cu `compute_period`.
  HIT doar dacă datele neschimbate → **zero stale** (orice add/delete/lock/edit-sumă mută
  fingerprint-ul → recompute automat, fără hooks, fără TTL). Wrapper transparent peste
  `_compute_d212_anual_uncached`; thread-safe (lock; bot+scheduler+Flask = thread-uri în
  același proces). Per-proces (se pierde la restart Render = doar recompute, zero risc de
  corectitudine). La HIT: 1 query ieftin în loc de 12× `compute_period`.

---

## WORKFLOW DE LUCRU

- **Arhitect/strategie:** Claude din chat (are memoria proiectului) — scrie
  prompturi exacte cu context complet.
- **Execuție:** Claude Code pe PC (`C:\bot-contabil-pfa`), accesat de Stefan de pe
  telefon prin remote. Citește/scrie/rulează direct în repo + git.
- **Disciplină:** prompt → (plan dacă e zonă sensibilă) → execuție → teste →
  review diff ÎNAINTE de commit → commit convențional → push → Render deploy auto.
- Pe zone de calcul de bani: ÎNTÂI plan + teste, abia apoi aplicare.

## NOTĂ DE MEDIU
Drift pydantic/pydantic_settings (`ImportError: Secret from pydantic`) la importul
lanțului `config`. **Rezolvat local** cu `pydantic 2.11.10` (`>=2.7` pt `Secret`,
`<2.12` pt aiogram); `requirements.txt` NEATINS → prod (Render) neafectat.
Testele care importă `config` (ex. `tax_engine`) rulează prin `tests/conftest.py`
(env dummy). `pydantic` e acum pinat în `requirements.txt` (Faza 2 PAS 3) → prod și
local aliniate, drift-ul `Secret` nu mai poate reapărea.

## COMMITURI CHEIE (sesiunea 2026-06-03)
- `a8e66c5` fix(d100): impozit nerezident Bolt obligatoriu lunar, plata reala
- `e258778` fix(tva): centralizeaza cota TVA intr-o sursa unica pe data
- `68abf4d` refactor(tva): consolideaza cele 3 locuri ramase la sursa unica cota_tva
- `9929722` docs: adauga PROGRES.md
- `6b0910e` refactor(contributii): sursa unica CAS/CASS, repara bug-uri estimare

## COMMITURI CHEIE (sesiunea 2026-06-05 — Faza 1)
- `50c8fa7` feat(labels): etichete RO pentru tranzactii (sursa unica labels_ro)
- `766935d` feat(dashboard): afiseaza etichete RO categorii in activitate + registru
- `8fdacc5` feat(dashboard): card "Cat platesc si cand" + termene reale pe overview
- `6d84c01` fix(calendar): D700 apare doar pentru neinregistrati (fals pozitiv)
- `d9a3459` feat(dashboard): suma reala D212 pe card din sursa unica
- `0ef43ba` feat(dashboard): badge calendar real + brand Contai + fix card D100 fiscal (bucata #3)

## COMMITURI CHEIE (sesiunea 2026-06-07 — Faza 2 arhivă R2)
- `fcade4d` feat(storage): backend R2 + fallback disk + get_bytes (PAS 1)
- `c7f09d5` feat(storage): aprinde R2 pentru uploaduri noi (PAS 2)
- `d9b6c6e` chore(deps): boto3 pentru R2 + pin pydantic (PAS 3)
- `eeb7f10` feat(api): ruta download document autentificata, stream din R2 (PAS 4)
- `d6a8eef` feat(dashboard): pagina Documente — arhiva pe luni + download din R2 (PAS 5)

## COMMITURI CHEIE (sesiunea 2026-06-08 — Faza 3 sumar lunar)
- `7efdf79` feat(db): tabel summary_sent pentru sumar lunar (PAS 1)
- `1459028` feat(scheduler): sumar lunar automat pe Telegram (PAS 2+3)
- `ca5292d` feat(scheduler): inregistreaza jobul sumar lunar (PAS 4)
- `06495be` feat(bot): comanda /sumar_test owner-only + helper unic (PAS 5)
- `18c0d3d` fix(raport): estimare fiscala pe realizat YTD (nu proiectie 1 luna x12)
- `4c72366` feat(sumar): D212 in linia "de platit acum", doar in fereastra termenului

## COMMITURI CHEIE (Faza 3 — alerte „aproape de plafon" TVA+CAS)
- `865ac0f` feat(contributii): prag_cas_status pentru alerte aproape-de-plafon (PAS 1)
- `12a8cb5` feat(plafon): pre-check ieftin _ytd_income_brut (PAS 2)
- `26b131a` feat(plafon): alerte aproape-de-plafon TVA+CAS in jobul proactiv (PAS 3)
- `e134813` feat(plafon): extensie — CAS 24 SMB (dublare baza) + CASS 60 SMB (plafonare)

## COMMITURI CHEIE (Faza 3 — performanță)
- `56fb4b9` perf(d212): cache cu fingerprint pentru compute_d212_anual (zero stale)

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 1)
- `8f1405e` feat(import): parser determinist BT (PDF) cu auto-checksum (PAS 1)
- `92a9fad` feat(import): handler extras BT + preview (PAS 2)

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 2)
- `038b3ad` feat(import): clasificator determinist extras BT (felia 2 PAS 1)
- `621ac5f` fix(import): denoise prinde 0.00RON lipit (fals-pozitiv comision pe plati POS)
- `e2bc1de` feat(import): preview clasificat grupat pe buckete (felia 2 PAS 2)

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 3: postare in registru)
- `5494e6d` feat(import): override categorie + fingerprint in post_document (PAS 1)
- `04cf0c8` feat(import): helper dedup fingerprint stabil (PAS 2)
- `e451673` feat(import): serviciu postare cheltuieli extras + garda buckete (PAS 3)
- `663c3f5` feat(import): UI logica pura postare extras (PAS 4a)
- `92748d0` feat(import): UI postare extras + commit tot-sau-nimic (PAS 4b)
- `9417cb1` docs: PROGRES.md - felia 3 INCHISA

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 4: reconciliere prezenta Bolt)
- `7f76990` feat(import): reconciliere prezenta venit Bolt (logica) + refactor sursa unica (PAS 1)
- `142f15b` feat(import): wiring nudge reconciliere Bolt in preview (PAS 2)
- `2afa729` docs: PROGRES.md - felia 4 INCHISA

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 5a: compensare plata<->returnare)
- `8c646ce` feat(import): hint obligatie structurat din classify (PAS 1)
- `8042170` feat(import): compensare plata<->returnare taxe (PAS 2)
- `a13a8c5` docs: PROGRES.md - felia 5a INCHISA

## COMMITURI CHEIE (Faza 3 — import extras bancar BT, felia 5 b->c: match plata<->obligatie)
- `d048beb` feat(import): model persistent plata obligatii (schema+repo) (5b)
- `d12ce1e` feat(import): serviciu inregistrare plati taxe (pur) (5c-a)
- `0225759` feat(import): afisare "achitat" in sumarul lunar (5c-b)
- `2be4f68` feat(import): UI confirmare plati taxe - logica pura (5c-c-1)
- `1aedaab` feat(import): wiring UI confirmare plati taxe - felia 5 COMPLETA (5c-c-2)
