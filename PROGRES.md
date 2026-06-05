# PROGRES — Contai (bot contabil PFA ridesharing)

> Document de stare + handoff. Citește-l la începutul fiecărei sesiuni noi de
> dezvoltare (Claude Code nu păstrează memoria între sesiuni).
> Ultima actualizare: 2026-06-05.

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

Suita: **82/82** teste verzi.

**TODO hygiene** (separat, neurgent):
1. Pin `pydantic` în `requirements.txt` (`>=2.7,<2.12`) ca să nu reapară drift-ul
   `Secret` pe alt mediu.
2. Centralizare cote pentru afișaj: D100 `baza*0.02` (dashboard) + duplicarea
   `COTA_TVA_STANDARD` din `fiscal_calendar.py` → o sursă unică de cote inclusiv
   pentru display (e doar afișaj, nu calcul real).

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
(env dummy). De pinat `pydantic` în `requirements.txt` la un commit de hygiene.

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
