# PLAN CONIAR — Contabil AI complet pentru PFA

> **Viziune:** cel mai complet și profesional contabil AI pentru PFA din lume, nu doar din România. Pornim de la ridesharing (activitatea-pilot), extindem la toate activitățile. Motorul fiscal comun se refolosește; fiecare activitate adaugă doar specificul ei.
>
> **Metodă de lucru (regulă permanentă):** pentru FIECARE pas → research avansat adânc (inclusiv multi-AI: Claude + Kimi + Gemini + Perplexity, triangulat) → ABIA APOI construim. Nu construim nimic fără research pe acel pas. Acest fișier e busola + memoria: se actualizează continuu; la repornirea conversației se citește întâi.
>
> **Status legend:** ⬜ neînceput · 🔬 în research · 🔄 în construcție · ✅ complet · ⏸️ amânat conștient · ❓ decizie de business deschisă

---

## §0. STARE ACTUALĂ (din auditul intern, iulie 2026)

**Ce e SOLID — motorul de calcul + evidență (fundația refolosibilă):**
- ✅ D212 (Declarația Unică) — calcul + PDF + regim auto configurabil (MIXT/EXCLUSIV, RCA/CASCO comodat, gardian ANAF)
- ✅ Motor comun CAS/CASS/impozit/TVA — praguri 2026, versionat pe an
- ✅ Generatoare parțiale: D300, D301, D390, D394, D100
- ✅ Calendar fiscal + alerte proactive (termene)
- ✅ Evidență: venituri, cheltuieli (12 categorii), comisioane reverse-charge TVA
- ✅ Interfețe: bot Telegram (principal) + dashboard web
- ✅ 818 teste verzi; deploy live pe Render

**Ce e GOL sau embrionar — stratul de integrare/automatizare (viziunea):**
- ⬜ e-Factura (zero: nici model Factură, nici XML UBL, nici API ANAF)
- ⬜ Depunere automată SPV (zero: generează PDF, userul depune manual)
- ⬜ Open Banking / conectare bancă (zero: doar import manual CSV/text)
- ⬜ API platformă Bolt/Uber (NU EXISTĂ oficial — vezi 1.6)
- ⬜ Plată card / abonament (zero: nici Stripe/Netopia, nici model Abonament)
- ⬜ D397 reconciliation (zero — dar e ARMA SECRETĂ, vezi 1.5)

**Diagnostic:** creier fiscal excelent, fără brațe. Calculează corect, dar nu citește banii singur, nu depune singur, nu încasează. Tot stratul de automatizare e de construit.

---

## §1. VIZIUNE, PRINCIPII & MODEL DE BUSINESS

**Pentru cine:** PFA-uri din România. Pilot: șoferi ridesharing (Bolt/Uber). Apoi: IT, e-commerce, consulting, chirii, alte activități independente.

**De ce mai bun decât SOLO/competiția (diferențiatori — de aprofundat în research):**
- Ridesharing-native: D397 reconciliation, TVA intracomunitar comision auto, CAEN 4933, regim auto configurabil
- Telegram-first (șoferii trăiesc pe telefon — niciun competitor nu conduce cu un bot)
- AI-driven: categorizare inteligentă cheltuieli, extracție din extrase/foto
- Automatizare completă: ingerează → categorizează → calculează → generează → depune → reamintește plata

**Model de business pe etape (validat vs piață — SOLO 121-229 lei/lună):**
- ❓ ~40 RON/lună (Basic): evidență + calcul + calendar + reminder, intrare date manuală
- ❓ ~80 RON/lună (Pro): + generare automată declarații + e-Factura + bancă + AI categorizare
- ❓ ~100-130 RON/lună (Full): + depunere automată SPV + D397 reconciliation + deep-link plată
- ❓ tier TVA (~150-180 RON): pentru șoferi plătitori de TVA (D300/D301/D390 lunar)

---

## FAZA 1 — RIDESHARING COMPLET (activitatea-pilot)

### 1.1 Declarații fiscale complete
- ✅ D212 (Declarația Unică) — complet
- 🔄 D300 (decont TVA) — generator există, de verificat completitudine
- 🔄 D301 (achiziții intracomunitare) — parțial
- 🔄 D390 (recapitulativă VIES) — parțial
- 🔄 D394 — parțial
- 🔄 D100 — generator există, de verificat
- ⬜ Verificare: pentru un șofer NEplătitor TVA cu comision Bolt/Uber (achiziție intracom serviciu), ce set exact e obligatoriu? (cod art. 317, D390, D301, D100)
- **Research necesar:** setul complet + termene, per profil (plătitor/neplătitor TVA)

### 1.2 Depunere automată în SPV ❓ DECIZIE DE BUSINESS
- **3 modele (din research):**
  - Model A (împuternicit): certificatul calificat Coniar + procură notarială/client. Depunem în numele lor. E modelul SOLO. Răspundere legală reală + graniță CECCAR/CCF.
  - Model C (confirmare-user): pregătim tot, userul confirmă cu un click în SPV-ul lui. Zero răspundere, automatizare mai slabă.
  - Model B (certificat propriu user): userul își conectează certificatul. Fallback power-user.
- **Recomandare Claude:** A ca flagship + C ca fallback (ce face SOLO).
- ❓ DECIZIE STEFAN: îți asumi modelul împuternicit (răspundere + "greșim, plătim amenda")?
- **Research necesar (URMĂTORUL, adânc):** legalitate împuternicit la scară, graniță CECCAR/CCF, cum face SOLO exact, răspundere, ce se automatizează 100% vs per-user

### 1.3 e-Factura (ingestie comisioane, nu emitere în masă)
- Rol pentru șofer: ingerează facturile de comision Bolt/Uber + gestionează TVA intracom (NU emite facturi pasageri — platforma o face, OUG 49/2019)
- ❓ Neclar legal: trebuie șoferul să emită/transmită și el factura către pasager? → opinie ANAF scrisă
- API ANAF documentat: OAuth2 + UBL 2.1 CIUS-RO + sandbox real
- Build vs buy: în casă (~2-4 luni) vs wrapper (Mandato/Contazen) vs librărie open-source
- **Research necesar (la pas):** decizia build/buy + clarificare legală ridesharing

### 1.4 Conectare bancară (Open Banking PSD2)
- Via agregator licențiat (Salt Edge / GoCardless) — Coniar NU are nevoie de licență AISP proprie
- Citire tranzacții săptămânal → categorizare AI venituri/cheltuieli
- ❓ GoCardless free-tier posibil în închidere — de verificat
- **Research necesar (la pas):** care agregator (acoperire bănci RO + preț)

### 1.5 D397 RECONCILIATION ⭐ ARMA SECRETĂ (inovație, niciun competitor)
- Ordinul ANAF 382/2025: platformele raportează lunar la ANAF fiecare cursă/km/CNP/încasare per șofer
- Coniar reconciliază venitul declarat de șofer vs ce ANAF are deja → transformă datele de CONTROL în BENEFICIU
- Rezolvă parțial lipsa API-ului de platformă
- **Research necesar:** cum se accesează D397 (prin SPV al userului?), format, ce date exact

### 1.6 Ingestie date platformă (REFRAME: import + AI, NU API live) ❓
- 🔴 NU există API oficial șofer nici Bolt, nici Uber (Uber "limited access" practic închis; Bolt zero; SDK-uri neoficiale = ToS violation, fragile)
- Strategie realistă (layered): D397 (1.5) + parsare extrase/CSV săptămânal + ingestie e-Factura comision + foto extras cu AI extraction (fallback universal)
- ❓ DECIZIE STEFAN: accepți "săptămânal + inteligent" în loc de "timp real"?
- **Research necesar:** cele mai bune metode de extracție AI din documente financiare

### 1.7 Plată
- Abonament SaaS: Stripe (best pt recurent, EUR real) sau Netopia mobilPay (local, RON)
- Plată taxe la ANAF: DOAR deep-link către ghișeul.ro/SPV (NU există API terți) → calculăm suma exactă + un tap
- **Research necesar (la pas):** Stripe vs Netopia pentru cazul RO

### 1.8 Model abonament pe etape → vezi §1 (integrare tehnică: Stripe subscriptions + gating funcționalități pe tier)

---

## FAZA 2 — EXTINDERE MULTI-ACTIVITATE

> Motorul comun (CAS/CASS/impozit/TVA/declarații) se refolosește. Fiecare activitate = un modul nou (ca ridesharing.py) cu specificul ei: categorii cheltuieli, reguli deductibilitate, coduri CAEN.

- ⬜ 2.1 Ordinea extinderii — ❓ care activitate după ridesharing? (mărime piață PFA RO pe domenii — **research**)
- ⬜ 2.2 IT / software / freelancing digital (piață mare, e-Factura B2B relevant)
- ⬜ 2.3 E-commerce (OSS, TVA, specificul vânzărilor online)
- ⬜ 2.4 Consulting / profesii liberale
- ⬜ 2.5 Chirii / venituri din cedarea folosinței
- ⬜ 2.x Arhitectura de "activitate plug-in" — ce se refolosește vs ce e nou (design de generalizat)

---

## FAZA 3 — TOP WORLD (diferențiatori globali)

> Ce ne pune peste ORICINE, nu doar peste SOLO. De definit prin research pe cele mai bune tool-uri din lume.

- ⬜ 3.1 Research: cele mai bune tool-uri fiscale/freelancer din LUME (QuickBooks Self-Employed, FreshBooks, gig-economy US/UK) — ce inovații importăm
- ⬜ 3.2 Ce lipsește la TOȚI (RO + world) = oportunitatea de aur
- ⬜ 3.3 AI-native features (dincolo de categorizare): predicție taxe, optimizare fiscală legală, asistent conversațional fiscal
- ⬜ 3.4 (de completat din research)

---

## §2. ÎNTREBĂRI DESCHISE & DECIZII DE BUSINESS

1. ❓ Model depunere SPV: A (împuternicit, răspundere) vs C (confirmare-user)? → **research următor decide**
2. ❓ Accepți reframe date "săptămânal + AI" în loc de "timp real API"?
3. ❓ e-Factura: build în casă vs wrapper?
4. ❓ Preț exact pe tiere?
5. ❓ Ordinea extinderii multi-activitate?
6. ❓ Structură legală firmă (SRL + certificat + graniță CECCAR/CCF)?

---

## §3. RESEARCH-URI DE FĂCUT (coadă, în ordine)

1. 🔬 **URMĂTORUL — Depunere declarații SPV la sânge** (model împuternicit, legalitate scară, CECCAR, cum face SOLO, răspundere) — multi-AI
2. 🔬 Ce ne duce peste SOLO + top world (competiție RO + tool-uri globale + inovații) — multi-AI
3. ⬜ Per pas, la construcție: research adânc pe acel subpas înainte de build

---

## §4. JURNAL (cronologic — pentru continuitate la repornire)

- **2026-07 (iulie):** Faza fiscală COMPLETĂ (regim auto D212 + audit general 3 treceri + reparații pre-lansare N1 IBAN/N2 categorie/N3 buton, PR #88-104, 818 verde). Stefan a oprit lansarea: Coniar trebuie contabil COMPLET (toate declarațiile + integrări), nu doar D212. Audit intern făcut → diagnostic "creier fără brațe". Research azi (Claude, comprehensive): e-Factura fezabil, SPV via împuternicit (model SOLO), Open Banking via agregator, NO Bolt/Uber API (reframe la import+AI), Stripe+ghișeul.ro plată, D397=armă secretă. Plan v0.1 scris. URMĂTORUL: research avansat multi-AI pe depunere declarații.

---

*Fișier viu. Actualizat la fiecare pas. Se citește PRIMUL la repornirea conversației.*
