# PLAN CONIAR — Contabil AI complet pentru PFA

> **Viziune:** cel mai complet și profesional contabil AI pentru PFA din lume, nu doar din România. Pornim de la ridesharing (activitatea-pilot), extindem la toate activitățile. Motorul fiscal comun se refolosește; fiecare activitate adaugă doar specificul ei.
>
> **Metodă de lucru (regulă permanentă):** pentru FIECARE pas → research avansat adânc (inclusiv multi-AI: Claude + Kimi + Gemini + Perplexity, triangulat) → ABIA APOI construim. Nu construim nimic fără research pe acel pas. Acest fișier e busola + memoria: se actualizează continuu; la repornirea conversației se citește întâi.
>
> **Status legend:** ⬜ neînceput · 🔬 în research · 🔄 în construcție · ✅ complet · ⏸️ amânat conștient · ❓ decizie de business deschisă
>
> 📋 **Fișierul ăsta spune CE AM DECIS. Pentru CE FACE produsul azi → [`INVENTAR-CONIAR.md`](INVENTAR-CONIAR.md)** (citit din cod: comenzi, butoane, rute, gating). Sunt întrebări diferite — nu le amesteca. Busola acoperă deciziile mari și feliile fiscale, dar NU e o listă completă a funcțiilor livrate.

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

**Model business pe tiere (triangulat):** Start ~99-149 lei (❓preț intrare de testat A/B: 99 armă agresivă vs 129-149 vinde-ROI) = Bolt+D212+estimare live+bot+rezervă taxe. Pro ~179-199 lei (peste SOLO, sub PFA Ride 299) = + depunere auto D390/D301/D100 + feed bancar AI + reconciliere + asistent + garanție. Max ~289-349 lei (sub Stradex 490) = + plătitori TVA D300/D394 (segment SOLO REFUZĂ) + optimizare predictivă + review uman anual. Poziționare: CATEGORIE NOUĂ "AI care automatizează" vs "digital cu oameni", NU "SOLO mai scump".

---

## FAZA 1 — RIDESHARING COMPLET (activitatea-pilot)

### 1.1 Declarații ridesharing — INVENTAR REAL (audit intern iulie 2026)

**DECIZIE SCOPE (research triangulat + verdict PFA-TVA):** Un PFA ridesharing NU atinge plafonul TVA 395.000 lei (limitat legal la 1 șofer, ~120-216k lei brut/an). Deci:
- ✅ Profil A (neplătitor TVA, cod art. 317) = TOT ce construim la ridesharing — acoperă 100% șoferi
- ⏸️ Profil B (plătitor TVA, D300/D394) = AMÂNAT la FAZA 2 (e-commerce/IT, unde plafonul se atinge) — NU la ridesharing
- Plafonul se calculează pe încasări BRUTE (nu net) — relevant doar teoretic

**Regulă transversală arhitectură:** generatoarele produc XML pt DUKIntegrator (userul rulează local → PDF depozabil) + ghid text. NU produc PDF direct. By-design (Drumul B), nu gaură.

**STARE PER DECLARAȚIE (audit cod, iulie 2026):**
- ✅ D212 (Declarația Unică) — COMPLET (regim auto, motor CAS/CASS/impozit). Anuală 25 mai. Baza fiscală a tot restului. (detaliat în §0)
- ✅ D301 (decont special TVA) — COMPLET. XML v1, reverse-charge 21% din sursă unică, luna-zero în 3 straturi. Etichetă nr_doc corectă per brand (UBER-/BOLT-).
- ✅ D390 (VIES) — COMPLET. XML v3 OPANAF 705/2020, tip "S", luna-zero ok. Orchestrare per-brand: operator corect Bolt(EE)/Uber(NL) din sursă unică, split proporțional cu invariant Σ baze==baza. Brand neatribuit → oprește cu mesaj (nu depune incomplet).
- ✅ D100 (impozit nerezidenți) — COMPLET. XML v2, 2% Bolt / 0% Uber din sursă unică, certificat Bolt integrat, suta mărită 16% fără certificat. (Infra per-brand acum partajată cu D390/D301.) Gaură minoră rămasă: certificat doar Bolt, nu Uber.
- ✅ D207 (informativă anuală nerezidenți) — COMPLET. XML mfp:anaf:dgti:d207:declaratie:v2 construit contra XSD OFICIAL descărcat (d207_20025020.xsd v1.02, byte-cu-byte). Structura reală: sect_II + benef frați în secvență (nu imbricat), legați prin tip_venit. Agregare anuală 12 luni × vat_out_by_brand cu reconciliere garantată D207_anual==Σ 12× D100 (A2). Bolt cod 04/EE, Uber cod 25/NL scutit (imp1=0, dar OBLIGATORIU declarat). Brand neatribuit → oprește (opțiunea b). De confirmat la validare: Tscutit vs Tbaza pt cod 25 (structura confirmată, semantica prin DUKIntegrator). + buton UI (bot + dashboard).
- ✅ D700 / art. 317 — REZOLVAT (fix comutator + ghid). BUG REAL reparat: userul care introducea codul rămânea NEPLATITOR → D700 îl bătea la cap permanent + D301 era ascuns. Fix _comuta_regim_intracom() în update_profile (punct unic): NEPLATITOR+cod→SPECIAL_INTRACOM (D700 se stinge, D301 apare), gardat pe PLATITOR_21 (nu retrograda plătitor), simetric la ștergere. Ghid D700 pas-cu-pas (7 pași: semnătură+SPV→Form 700 B.VI 1.23.1 bifa 3→upload→recipisă→ridicare cert→VIES→cod în Coniar) pt cine nu s-a înregistrat. D700 NU e generator (înregistrare web SPV, fără XSD/XML). D301/D390 neatinse (ortogonale).
- ✅ Plafon TVA 395.000 — COMPLET ca alertă. VAT_THRESHOLD_RON=395_000, status OK/APROAPE(≥80%)/DEPĂȘIT, pe venit brut YTD. Monitorizare, nu blocare.

**GĂURI DE BUILD (ordine recomandată):**
1. ✅ FĂCUT — orchestrare Uber (D390+D301+etichetă) — 15 teste noi, 833 total verzi, branch fix/orchestrare-uber-d390-d301
2. ✅ FĂCUT — D207 (generator + agregare anuală + XSD oficial) — 13 teste noi, 846 total verzi, branch feat/d207-generator
3. ✅ FĂCUT — D700/317 fix comutator + ghid — 8 teste noi, 854 total verzi, branch fix/regim-intracom-switch
4. ✅ FĂCUT — wire-up UI D207 (rută + handler bot + buton inline + dashboard) — 7 teste noi, 861 total verzi, branch feat/d207-ui-button

✅ §1.1 COMPLET 100% — set declarații ridesharing Profil A: toate generate ȘI accesibile userului (bot + dashboard). Creierul fiscal complet cu brațele de acces.

### 1.2 Depunere automată în SPV — DECIS: traseu D→A (mapat pe tiere)

**CERT (triangulat 4 surse: Claude + Kimi + Gemini + Perplexity, iulie 2026):**
- ✅ Modelul împuternicit e LEGAL (art. 18 Cod procedură fiscală) și FĂRĂ limită de clienți per certificat (Ordinul ANAF 2213/2025: "titularul unui certificat calificat poate fi împuternicit ... de către mai mulți contribuabili")
- ✅ NU există API ANAF pentru depunere declarații (doar e-Factura/e-Transport au API)
- ✅ DAR depunerea se automatizează server-side: DUKIntegrator (validare+semnare) + upload mTLS pe e-guvernare + poll recipisă. SAGA/Nexus/iSpv o fac deja comercial
- ✅ Răspunderea fiscală rămâne la PFA (art. 18); "plătim amenda" = clauză contractuală de despăgubire, NU transfer de răspundere
- ✅ Granița CECCAR = riscul principal (art. 348 Cod penal)

**3 DESCOPERIRI cheie:**
- 🔑 A. Procura notarială NU mai e obligatorie pt ANAF — OPANAF 2213/2025 acceptă înscris sub semnătură privată semnat electronic → onboarding 100% DIGITAL (SOLO ține notarial doar fiindcă face și ONRC)
- 🔑 B. D212 se depune din SPV-PF cu USER/PAROLĂ, fără certificat calificat → "pregătim tot, tu apeși Upload" = aproape 1-click, ZERO expunere CECCAR, ZERO împuterniciri
- 🔑 C. Art. 12(1) OG 65/1994: expert contabil ANGAJAT nu poate presta pt clienții angajatorului → nu "angajăm contabil", ci firmă CECCAR PARTENERĂ separată

**DECIZIE — traseu în 2 faze, mapat pe tiere:**
- FAZA 1 (lansare acum, risc ZERO): generăm tot, userul apasă upload în SPV-ul lui (user/parolă, fără certificat). Zero F150, zero CECCAR, TTM imediat. → tiere 40-80 RON "pregătim, tu depui" (model D/C)
- FAZA 2 (premium, după venituri): împuternicit full-service + firmă CECCAR parteneră + poliță E&O + avocat. → tier 100-130 RON "depunem noi" (model A)

**⚠️ De validat cu avocat înainte de Faza 2:** granița exactă CECCAR/CCF (2 surse zic parteneriat obligatoriu, 1 zice model SOLO suficient; SOLO NU e la CECCAR, operează CAEN 6210 — interpretare curajoasă, nu blindată). LECȚIE SOLO: consimțământ explicit documentat PER document, nu semnătură aplicată mecanic (SOLO a avut scandal public cu asta).

**Research necesar (la construcție Faza 2):** procedura DUKIntegrator + upload e-guvernare exact; structura firmă CECCAR parteneră.

### 1.3 e-Factura — ✅ DECIS (research #8, ultima piesă research Faza 1)
- ✅ **DECIS (research #8).** TREI FLUXURI clarificate: (1) Coniar→șofer abonament = ÎL construiești (Stripe webhook→wrapper→SPV); (2) platformă→șofer comision = ingestie PORTAL-FIRST (CSV/PDF autoritativ, SPV secundar pt autofacturi RO Bolt emergente nov 2025, cu deduplicare); (3) șofer→pasager = NU EXISTĂ, platforma emite (OUG 49/2019 art.7 lit.l), zero muncă Coniar, fără casă de marcat.
- **BUILD vs WRAPPER: WRAPPER Oblio** (SDK Python oficial, 29€/an e-Factura inclusă gratuit, fără taxă/factură) — NU build ANAF direct (2-4 luni + risc conformitate). Alt: SmartBill (scump, tier), FGO. e-Factura ARE API real (OAuth2, UBL 2.1 CIUS-RO) dar wrapper insulează.
- TVA: Coniar neplătitor sub 395k (fără linie TVA); peste → 21%. Șoferii nu deduc → rămâi neplătitor la început. Obligație șofer: PRIMIRE e-Factura (Coniar arhivează 10 ani); emitere N/A (nu facturează pasager). Atenție 15 ian 2026: CNP-identificați se înregistrează (formular 082). Termen depunere 5 zile lucrătoare (OUG 89/2025).

### 1.4 Conectare bancară (Open Banking PSD2) — ✅ DECIS (research #6)
- ✅ **DECIS (research #6, agregatori PSD2).** Verdict: GoCardless/Nordigen (opțiunea free clasică) ÎNCHISĂ pt înscrieri noi. Agregator ales: **Salt Edge** (Partner Program fără licență proprie, acoperire RO completă BT/ING/BCR/Raiffeisen/CEC/BRD/Revolut, românesc). Alt: Enable Banking (dar produsul principal cere licență proprie). LICENȚĂ AISP: NU proprie dacă Coniar e "data recipient" (date bancare = INPUT pt fiscalitate/reconciliere, NU ecran "vezi-ți conturile") — EBA Q&A 2018_4098. Capcană: afișarea datelor consolidate sub brand propriu → poate cere înregistrare agent/AISP. NECESITĂ AVOCAT pt fluxul specific. Cost: ~150-500€/lună (doar la cerere). Fricțiune SCA: 180 zile (relaxat de la 90). **DECIZIE BUILD: NU feed automat acum — extinde PDF manual (ING/Revolut, zero cost/risc), pilot Salt Edge paralel, scalează când se justifică. Pas 2 reconciliere (axa bancară) se deblochează cu PDF manual extins, NU necesită agregator.**
- Citire tranzacții → categorizare AI venituri/cheltuieli (obiectivul feature-ului, indiferent de sursă)

### 1.5 RECONCILIERE ⭐ ARMA SECRETĂ (inovație, niciun competitor) — COMPLETĂ (3 axe)
- ✅ **pas 1 + pas 2 FĂCUTE (arma secretă COMPLETĂ, 3 axe).** Reconciliere three-way pe sursele controlate de șofer (Bolt API ↔ declarat ↔ bancă): (4a) prezență, (4b) sumă brut↔declarat pas 1, (4c) bancar cumulativ net↔net pas 2. Pas 2: axa bancară CUMULATIVĂ (YTD, nu lunară — payout săptămânal nu respectă luna; cumulativ timingul se spală). Capcana cash rezolvată (net_bancabil exclude curse cash — Bolt depune doar card în bancă). Toate 3 axe ortogonale (constante distincte RECON_TOL_ABS=5 vs BANK_RECON_TOL_ABS=50). Poziționat "previi verificările ANAF". Uber = imposibil azi (fără API). Extindere ING/Revolut (parser PDF) = follow-up când există fixture-uri reale.
- 📌 **NOTĂ (corectură la „Uber = imposibil azi"):** axa **4c (bancă↔platformă) funcționează ȘI FĂRĂ API**, fiindcă banca e o sursă INDEPENDENTĂ — nu ai nevoie de API-ul platformei ca să compari ce a intrat în cont cu ce a declarat șoferul. Doar 4a și 4b cer API. Blocantul real pentru Uber nu e lipsa API-ului, ci **clasificatorul: `classify.py:157` caută literal `"bolt"` în descrierea tranzacției** → încasările Uber nu nimeresc niciun bucket de venit. Un bucket de venit parametrizabil per platformă deblochează 4c pentru Uber, fără nicio integrare.
- Context istoric: REFRAME (D397 INACCESIBIL șoferului — intern ANAF; nici DAC7 nu-i accesibil PFA) → reconciliem ce controlează șoferul.
- Context (de ce contează): Ordinul ANAF 382/2025 — platformele raportează lunar fiecare cursă/km/CNP/încasare per șofer (D397, dar e al platformei, nu al șoferului) → presiune reală de conformare pe care reconcilierea o transformă în beneficiu.

### 1.6 Ingestie date platformă (REFRAME: import + AI, NU API live) — ✅ DECIS
- 🔴 NU există API oficial șofer nici Bolt, nici Uber (Uber "limited access" practic închis; Bolt zero; SDK-uri neoficiale = ToS violation, fragile)
- Strategie realistă (layered): D397 (1.5) + parsare extrase/CSV săptămânal + ingestie e-Factura comision + foto extras cu AI extraction (fallback universal)
- ✅ **DECIS — ÎNTREBAREA DESCHISĂ SE ÎNCHIDE. RITMUL PRODUSULUI = RITMUL PAYOUT-ULUI:** săptămânal + alerte inteligente. Timpul real NU EXISTĂ TEHNIC la nicio platformă (nu e o limitare a noastră, e o limitare a pieței) — deci nu-l promitem și nu construim după el. Ce contează pentru șofer nu e latența datelor, ci să nu rateze un termen și să nu aibă surprize; alea se rezolvă cu alerte, nu cu streaming.
- **Research necesar:** cele mai bune metode de extracție AI din documente financiare

### 1.7 Plată — ✅ DECIS (Stripe+Billing) · 🎉 Feliile 1 + 2 (2a+2b+2c) + 4a + 4b FĂCUTE — LANȚUL DE PLATĂ COMPLET (rămâne doar Felia 3 Oblio)
- 🔨 **Felia 1 FĂCUTĂ (fundația abonament).** Câmpuri User (stripe_customer_id/_subscription_id/_status/_tier, oglinda triadei Bolt) + migrarea 023 + config stripe_* (Optional) + subscription.py (tiere FREE/START/PRO/MAX din decizia #4 + is_subscribed/user_tier/has_tier_at_least). INERT prin construcție (userii existenți = NULL = FREE, zero schimbare; gating neaplicat încă).
- 🔨 **Felia 4a FĂCUTĂ (mecanism reverse trial).** Câmp User trial_ends_at + migrarea 024 + user_tier() trial-aware (prioritate: abonat activ→stripe_tier / în trial→PRO / altfel→FREE — plata primează, nu penalizează MAX luat în trial) + is_in_trial/trial_days_left + setare 30 zile la onboarding (idempotent). Rezolvă GAP-ul (reverse trial n-avea unde sta). now injectabil (teste deterministe). INERT — gating încă NEaplicat.
- ✅ **Felia 4b FĂCUTĂ (gating aplicat + teaser = FREE "Radar" real).** gating.py nou (sursă unică: hartă feature→tier + copy + teaser + require_tier). Bot: interceptare router înainte de try (FREE apasă depunere→upgrade, handler neatins) + gardieni _trimite_declaratie_noua + execute_fisa_d207. Web: _require_tier→403 upgrade_required. TEASER arma secretă: bolt_amount_reconcile + bolt_bank_reconcile_cumulative NEatinse — doar afișajul ramifică (FREE=suma+copy liniștitor "posibilă nepotrivire ~X lei, rezolvarea în PRO"; PRO/trial=verdict complet). Verdictul pozitiv "API confirmă X" rămâne pt toți (liniștire, nu armă). Ton: "tu" + emoji prietenos. GATING REAL (nu cosmetic): închise și sync nocturn _daily_sync_one + buton Bolt (altfel FREE primea sync automat). Alertele termene = FREE (util singur, neatinse). 32 teste noi, 949 verzi.
- 🔨 **Felia 2 — Brick 2a FĂCUT (fundația plății Stripe).** SDK `stripe>=15.0,<16.0` (validat local 15.4.0) + config `stripe_price_start/_pro/_max` (Optional, degradare grațioasă) + `set_subscription`/`clear_subscription` în users.py (scriere DIRECTĂ + flush, None=lasă neschimbat; clear păstrează customer_id/subscription_id/tier pt istoric + reabonare fără client duplicat) + `app/services/stripe_config.py` (price_id_for_tier + tier_for_price_id invers pt 2c + tiers_configurate + is_payment_configured, hartă citită la APEL nu la import). CAPCANĂ REZOLVATĂ: `update_profile` are allowlist fără câmpurile Stripe → `update_profile(stripe_status='active')` ar fi fost silent no-op (bug-ul vehicule_repo.update/regim_utilizare) — setter dedicat + test-gardian care CADE dacă cineva adaugă câmp Stripe în allowlist. ZERO Stripe API live, testabil fără chei, diff strict aditiv +72/-0. 22 teste noi, 971 verzi.
- 🔨 **Felia 2 — Brick 2b FĂCUT (checkout Stripe).** `app/services/stripe_checkout.py` nou: `create_checkout_session(user, tier)→url` (SDK lazy — import + api_key la APEL, `client_reference_id=user_id` + metadata pe sesiune ȘI pe abonament pt 2c, `mode=subscription`, refolosește `stripe_customer_id` la reabonare). Flux bot în DOI TIMPI: buton gating callback „💳 Activează PRO" → creează sesiunea la INTENȚIE REALĂ → buton URL „🔒 Plătește PRO" spre checkout.stripe.com (NU URL direct în gating: sesiunile expiră + ar fi apel de rețea la FIECARE blocare, inclusiv pt cine nu apasă). Pagini `/stripe/success` + `/stripe/cancel` (cosmetice, zero DB, zero auth — redirectul Stripe n-are initData Telegram). DECIZII: webhook (2c) e SINGURA scriere în DB — 2b nu scrie, garanție STRUCTURALĂ (funcția n-are `session` în semnătură, dovedit pe AST: zero import repository/db/models, zero `.set_subscription/.commit/.flush/.add`); buton URL nu WebApp (3DS + redirect bancar + Apple/Google Pay nu merg în containerul WebApp); butonul duce la tier-ul CERUT de feature. CTA cu sursă unică (`cta_label` alimentează și textul, și butonul → nu pot diverge; 1 linie de copy din `upgrade_text` atinsă ca mesajul să nu trimită la un buton inexistent). Fără chei/price → cade pe „Deschide Dashboard" (4b), degradare grațioasă. 31 teste noi, 1002 verzi.
- ✅ **Felia 2 — webhook Stripe COMPLETĂ (2a+2b+2c).** 🎉 **LANȚUL DE PLATĂ COMPLET: gating → checkout → plată → webhook → abonament activ.** 2c: `app/services/stripe_webhook.py` nou (`verifica_semnatura` + `proceseaza`→PROCESAT/IGNORAT, commit la apelant) + rută `POST /stripe/webhook` (PRIMA rută fără `_require_user` — auth = semnătura Stripe; raw body prin `get_data()`, nu `get_json`: Stripe semnează byte-cu-byte). 4 EVENIMENTE: `checkout.session.completed` (tier din `metadata`, doar dacă `payment_status='paid'` — `line_items` nu vine în payload) · `customer.subscription.updated` (comută pe STATUS, tier din `items.data[0].price.id`; `cancel_at_period_end=true` NU taie accesul — omul a plătit până la finalul perioadei) · `customer.subscription.deleted` (`clear_subscription`) · `invoice.paid` (IGNORAT, 200 — n-are cale de identificare, reînnoirile vin prin `updated`). COD RĂSPUNS anti-retry: 400 semnătură invalidă/lipsă; 200 procesat SAU ignorat intenționat (stări permanente — retry n-ar repara); 500 DOAR eroare tranzitorie (DB picat), unde retry-ul chiar ajută. SEMNĂTURI REALE în teste (HMAC ca Stripe, nu mock) → prinde upgrade-pe-furiș (corp modificat după semnare→400) și replay (semnătură veche→400). 2c respectă prioritatea 4a: scrie doar starea Stripe, `user_tier` decide tier-ul (deleted lasă trial-ul valabil să dea PRO). 30 teste noi, 1032 verzi.
- ⏳ **FOLLOW-UP pre-lansare** (lângă backfill trial): apărare ordine evenimente Stripe — un `.deleted` întârziat poate ajunge după un `.updated` mai nou (compară `event.created` cu un timestamp pe user). Risc 0 acum (niciun user în producție).
- 🔨 **Felia 3 — Brick 3a FĂCUT (fundația facturării).** Config `oblio_email/_secret/_cif/_serie_factura` (Optional) + `app/services/oblio_config.py` (`is_oblio_configured` + `campuri_lipsa` — citite la APEL, tiparul stripe_config; toate 4 obligatorii). Migrarea 025: tabel `factura_abonament` (user_id **ON DELETE RESTRICT** — factura emisă e DOCUMENT FISCAL cu arhivare 10 ani, NU dispare cu userul; `stripe_invoice_id` **NOT NULL UNIQUE** = anti-factură-dublă la nivel de BAZĂ, fiindcă webhook-urile se livrează repetat iar două facturi pt o plată = problemă reală la ANAF; status pending/emisă/eroare + eroare_text pt reluare) + `adresa_strada`/`cod_postal` pe users (factura cere stradă+nr, aveam doar județ/localitate). Checkout: `billing_address_collection="required"`. Webhook `checkout.completed`: salvează `customer_details.address` DOAR în golurile existente (ce a declarat userul în onboarding bate formularul de plată); adresa lipsă NU blochează activarea abonamentului. ZERO apeluri Oblio (verificat pe AST). 21 teste noi, 1053 verzi. Rămâne 3b: emiterea propriu-zisă (cere DATE CONIAR furnizor — CUI/reg.com./sediu/IBAN, LIPSESC).
- ✅ **DECIS (research #7, Stripe vs Netopia).** Ales: **STRIPE + Stripe Billing** pentru lansare. CORECTURĂ MIT: Stripe e RON-nativ pt SRL RO (încasezi RON, payout RON la IBAN românesc, ZERO FX — mitul "Stripe=EUR scump" e doar pt entități US/Atlas). Comision 1.5%+1 RON +0.7% Billing. Stripe Billing = motor abonamente COMPLET (scheduler, retry, dunning, SCA/MIT, portal) → build minim. Netopia mai ieftin pe comision (1.24%+0.3 RON+TVA) DAR doar token, construiești TU tot motorul (săptămâni cod fragil) → nu merită la început. Alt local: Twispay/xMoney (motor gestionat RON-nativ, dar pivot crypto — verifică). La sume mici comisionul fix domină: Stripe+Billing ~5.5% vs Netopia ~2.7% la 30 RON. Diferență ~85 RON/lună la 100 abonați (mică), ~850 RON la 1000. PRAG MIGRARE: ~1000+ abonați. DECIZIE: Stripe+Billing lansare; reevaluezi la 1000 abonați.
- 🔗 **LEGĂTURĂ §1.7↔§1.3:** niciun procesator NU emite factura fiscală. După încasare → webhook → generezi factură (SmartBill/Oblio/FGO API) → trimiți la ANAF e-Factura. e-Factura B2C OBLIGATORIE din 1 ian 2025. Deci pipeline-ul de plată are nevoie de e-Factura ca pas următor — §1.7 și §1.3 se leagă.
- Plată taxe la ANAF (feature separat): DOAR deep-link către ghișeul.ro/SPV (NU există API terți) → calculăm suma exactă + un tap

### 1.8 Model abonament pe etape → vezi §1 (integrare tehnică: Stripe subscriptions + gating funcționalități pe tier)
- Fundația de gating (is_subscribed/user_tier/has_tier_at_least) construită în Felia 1 §1.7; aplicarea pe features = Felia 4b ✅ FĂCUTĂ.

⚠️ **FOLLOW-UP LANSARE:** la deploy public, userii existenți/de la lansare cad pe FREE (trial_ends_at NULL — 4a pune trial doar la onboarding nou). Pt lansare = backfill trial pentru userii existenți (setare trial_ends_at retroactiv). Acum irelevant (fără useri în producție, doar owner-testing). De făcut ÎNAINTE de lansarea publică.

**✅ MODEL DE INTRARE — DECIS (research #9, freemium/trial).** REVERSE TRIAL: 30 zile PRO complet la înscriere (FĂRĂ card) → cade pe FREE "Radar" permanent. Durată 30 zile (sau până la următorul termen declarație — să prindă un ciclu fiscal complet + un "aha moment"; arma secretă are nevoie de date acumulate). Precedent: Toggl (reverse trial 30 zile → dublat venitul premium). Concurenți: SOLO = card obligatoriu, fără trial/free; cei mai buni din nișă (Indy 400k, Norman, Accountable) = tracking gratis + DEPUNERE/automatizare plătită ("gratis să urmărești, plătești să depui"). Facturarea = gratis peste tot în RO → NU monetiza vizualizarea, monetizează automatizare+reconciliere+depunere.

**MAPARE FREE→PLĂTIT:**
- FREE "Radar" (permanent post-trial): vizualizare read-only (Bolt/bancă/declarat) + ALERTE termene cu sume + TEASER discrepanță ("există nepotrivire X lei" — arată CĂ, blochează detaliile+rezolvarea) + provocări ("sync Bolt", "importă BT") + estimare aproximativă (detalii blocate).
- START (99-149): Bolt sync + D212 + estimare live + bot + rezervă taxe.
- PRO (179-199, FLAGSHIP "recomandat"): + auto-depunere D390/D301/D100 + feed bancar AI + ARMA SECRETĂ COMPLETĂ (aici se rezolvă teaser-ul) + asistent + garanție.
- MAX (289-349): + plătitori TVA D300/D394 + optimizare + review uman.

**CÂRLIGUL DE AUR:** arma secretă = TEASER BLOCAT (nu black-box, nu gratis) — anunță discrepanța (frica ANAF + loss aversion 2.25x), blochează rezolvarea în PRO. Copy LINIȘTITOR ("te ajutăm s-o rezolvi în PRO") ca să nu creeze anxietate.
**CONVERSIE:** țintă 5-10% (peste norma freemium 2-5%, datorită reverse trial + urgență termene + frica ANAF). CHEIA = activare (% care conectează Bolt+bancă în săpt. 1). Împinge ANUAL (retenție 92% vs 68% lunar), discount 15-20% la termen fiscal. FĂRĂ card la înscriere (challenger → volum+încredere; SOLO cere card dar noi optimizăm volum întâi).
**NOTĂ:** 5-10% e proiecție, nu măsurătoare (fără benchmark gig RO); teaser discrepanță fără precedent → testează A/B.

---

## FAZA 2 — EXTINDERE MULTI-ACTIVITATE

> Motorul comun (CAS/CASS/impozit/TVA/declarații) se refolosește. Fiecare activitate = un modul nou (ca ridesharing.py) cu specificul ei: categorii cheltuieli, reguli deductibilitate, coduri CAEN.

- ⬜ 2.1 Ordinea extinderii (CERT triangulat): Ridesharing (acum) → CURIERAT/delivery (Glovo/Wolt/Tazz — mecanică fiscală ~identică, extindere aproape gratuită) → IT/freelancing B2B (segment mare cu bani, CAEN 6201/6202 scoase de la normă→sistem real, toleranță premium; bătălia cu SOLO pe merit) → profesii liberale → chirii (produs-lite, volum mare ARPU mic). E-commerce EVITAT până există resurse gestiune/stocuri. Fiecare pas refolosește ≥80% din motor.
- ⬜ 2.2 IT / software / freelancing digital (piață mare, e-Factura B2B relevant)
- ⬜ 2.3 E-commerce (OSS, TVA, specificul vânzărilor online)
- ⬜ 2.4 Consulting / profesii liberale
- ⬜ 2.5 Chirii / venituri din cedarea folosinței
- ⬜ 2.x Arhitectura de "activitate plug-in" — ce se refolosește vs ce e nou (design de generalizat)

---

## FAZA 3 — TOP WORLD (diferențiatori — triangulat 4 surse: Claude+Kimi+Gemini+Perplexity, consens puternic)

### 3.0 Diagnostic competitiv (CERT)
- Piața RO NU are contabil AI real. 3 categorii: (1) digital-cu-oameni (SOLO, Keez — app-fațadă + procesare umană "cutie neagră"); (2) facturare (SmartBill/FGO/Oblio — nu fac contabilitate PFA); (3) self-service (ContApp/Saga — userul depune singur; ContApp NU implementează D390/D301/D100 = inutilizabil ridesharing cap-coadă).
- SOLO = liderul de bătut. Slăbiciuni EXPLOATABILE: procesare umană (latență zile), fără feed bancar, fără AI real, fără bot, doar Android; REFUZĂ plătitori TVA + numerar/casă marcat + producători (segmente libere). DOVADĂ durere: erori documentate public — decizie impunere de la 3.000€ corect → 10.000€ greșit (cutie neagră fără validare încrucișată).
- 🆕 **ETERNIS (eter.app)** — jucător de urmărit, categorie DIFERITĂ. Parent polonez, **12.000+ șoferi declarați** în RO. E un **hub de administrare a muncii pe multiple platforme** (Bolt + Uber + livrări la un loc), NU un contabil dedicat: acoperă partea de „gestionează-ți munca", nu declarațiile și calculul fiscal. Relevant din două motive — (1) are deja distribuția pe care noi o construim (12.000 de șoferi = canal, nu doar concurent), (2) dacă adaugă un strat fiscal, devine concurent direct peste noapte. Poziționarea noastră rămâne „contabilul", nu „hub-ul de ture".
- Ancore preț servicii umane ridesharing: PFA Ride 299 lei/lună, Stradex ~490 lei/lună, **SOLO 229 lei/lună preț complet (verificat aug 2026)**. Piața plătește 230-500 lei/lună pt liniște.
- Date piață: 56.000+ șoferi fără formă legală conformă (de convertit); ~44.000 PFA noi 2025 (+63%), transport #1 la înmatriculări; ANAF fraude 35M€ + D397 = presiune conformare → reconcilierea = "te aperi de ANAF".

### 3.1 CELE 4 DIFERENȚIATOARE GOL-DE-PIAȚĂ (unic RO, CERT)
1. Estimare fiscală LIVE la fiecare încasare Bolt (impozit 10% + CAS/CASS pe plafoane + TVA 21% comision) — nimeni în RO
2. Reconciliere THREE-WAY Bolt↔bancă↔ANAF/SPV — GENUIN NOU, unic mondial în combinație (nici Found nu o face)
3. Categorizare AI cheltuieli din extras bancar (PSD2) + separare business/personal
4. Asistent fiscal conversațional Telegram (LLM explică, motor determinist calculează — anti-halucinație)
+ Rezervă taxe (2 niveluri: NOTIFICARE devreme/ușor "pune deoparte X"; BaaS-cu-IBAN-virtual târziu/greu, cere partener bancar) + alertă proactivă plafon TVA 395.000 lei (pe încasări BRUTE)

### 3.2 PRINCIPII DE ÎNCREDERE (CERT — lecții din eșecuri globale)
- Fiecare cifră din motorul determinist, NU din LLM (anti-halucinație)
- "Human approves, AI files" — preview + confirmare la fiecare depunere (validat Keeper/FlyFin)
- AI învață din corecțiile userului per-cont (anti-Kontist: AI care nu învață distruge încrederea)
- Garanție amendă (SOLO o are; Accountable până la 10.000€) — minim de egalat
- Billing transparent lunar fără lock-in (antidot plângere #1 Keeper/FlyFin: trial→facturare anuală surpriză)
- Explainable AI: arată formula din spatele fiecărei categorizări (confort psihologic vs cutia neagră SOLO)

### 3.3 IDEI AVANSATE (notate, nu pt început)
- ✅ **Foaia de parcurs MANUALĂ e CONSTRUITĂ și livrată** (buton „🛣️ Foaie parcurs" + `/sterge_tura` + export Excel): ture, km, litri — DOVADĂ la control, nu calcul (comutatorul deductibilității e regimul vehiculului, vezi 5A/5B). Ce rămâne idee amânată e doar versiunea AUTO-GENERATĂ de mai jos.
- ⏳ [idee amânată] Foaie de parcurs auto-generată (GPS + date Bolt) — dificil + ❓INCERT legal, validează cu consultant
- Arhitectură microservicii + retry asincron pt SPV (XML ANAF se schimbă des, SPV instabil)
- Optimizare fiscală predictivă ("dacă treci normă→real economisești Y"; timing înregistrare TVA; stopaj 2% Bolt cu certificat rezidență Estonia)

### 3.4 DE EVITAT (gimmick/ROI slab)
- ⛔ Mileage GPS ca feature fiscal (valoare ZERO în RO — sistem real deduce costuri reale 50/100, NU km)
- Insights demand "unde să conduci" (Gridwise-style — nu ține de contabilitate, date indisponibile Bolt API)
- Chatbot generic fără acces la datele contului (ChatGPT o face gratis)
- E-commerce/stocuri + multi-țară înainte de a domina RO

---

## §2. ÎNTREBĂRI DESCHISE & DECIZII DE BUSINESS

> **Numerele sunt ID-uri de decizie, nu poziții** — nu se renumerotează, ca trimiterile din jurnal să rămână valide. **#2** (ritmul datelor) și **#4** (prețul) au fost scoase de aici: #2 e închis în §1.6 (ritmul produsului = ritmul payout-ului), #4 trăiește ca blocantul 13 din §5, unde contează la lansare.

1. ✅ #1 REZOLVAT — traseu D→A, vezi §1.2
3. ✅ #3 e-Factura build vs wrapper — REZOLVAT: WRAPPER Oblio (SDK Python, 29€/an, e-Factura inclusă). Build ANAF direct = 2-4 luni, evitat.
5. ✅ #5 Ordine extindere — REZOLVAT (ridesharing→curierat→IT→profesii→chirii, vezi 2.1)
6. ✅ #6 Structură juridică CECCAR — REZOLVAT (research triangulat 4 surse: Claude+Perplexity+Gemini+cel intern). VERDICT: minimul CECCAR pentru ridesharing = ZERO. PFA are drept legal să depună singur (Legea 82/1991 art.1(5)+10(4¹)); nicio certificare D212 obligatorie; reprezentarea (împuternicit) NU e rezervată profesiei. Model A (software + user depune din SPV-ul lui) = zero CECCAR, cost zero, inatacabil (art.348) — se mapează pe traseu D. Model B (reprezentare) = tot zero-CECCAR-rezervat. Plătești CECCAR doar dacă vinzi serviciul contabil în sine (premium opțional Faza 2). SOLO confirmă modelul (firmă software CAEN 6210, NU firmă CECCAR, depune ca împuternicit).
   - CAPCANĂ contabil angajat (art.12 OG 65/1994): expertul angajat pe SRL NU poate presta pentru clienții SRL-ului. Soluție: reziliezi CIM, ea face PFI/cabinet propriu, contract B2B cu Coniar (audit algoritmic general, nu per-client → cost per-user zero). NECESITĂ AVOCAT: T&C exonerare + structura contabilului + statusul art.348 (înăsprire Senat oct 2025 spre 6luni-5ani).
   - AVERTISMENT (din Gemini): modelul BPO-mascat (platforma preia semnătura clientului, ca SOLO) e riscant — raport Incorpo.ro acuză SOLO de mii de falsuri (semnături generate cu mouse-ul). Dacă mergem spre depunere de către noi, userul trebuie consimțământ REAL informat, nu semnătură auto.

---

## §3. RESEARCH-URI DE FĂCUT (coadă, în ordine)

1. ✅ Research depunere SPV (triangulat 4 surse) — FĂCUT, vezi §1.2
2. ✅ Research competitiv top-world (triangulat 4 surse) — FĂCUT, vezi FAZA 3
3. 🔬 **URMĂTORUL — la construcția fiecărui subpas Faza 1: research adânc pe acel subpas ÎNAINTE de build** (ex. e-Factura API, PSD2 agregator, DUKIntegrator upload)
4. ⬜ Per pas, la construcție: research adânc pe acel subpas înainte de build (regulă permanentă)

---

## §5. PÂNĂ LA LANSARE

> **Dacă întrebi „ce mai e până la lansare?", răspunsul e AICI. Nu în §1.x, nu în jurnal, nu în capul modulelor de cod.**

### SCARA DE TIERE — principiul

Logica treptelor nu e „câte funcții primești", ci **cât de multă muncă îi luăm de pe umeri**:

- **START** — *înregistrează și vede.* Bonuri, facturi, venituri prin poză; afișare vizuală. **NU** generează registrul, **NU** generează declarațiile — doar le vede.
- **PRO** — *generează registrul și declarațiile, le depune SINGUR, cu îndrumarea noastră* (DUK Integrator + Java, pas cu pas).
- **MAX** — *depunem noi în SPV.* Toată treaba.

Fiecare treaptă mută o bucată de muncă de la om la noi. Gating-ul de azi trebuie aliniat la scara asta (vezi blocantul 11).

### BLOCANTE — CORECTITUDINE FISCALĂ

> **Principiu:** orice calcul fiscal incomplet e blocant. Un impozit greșit distruge încrederea o singură dată și definitiv.
> Fiecare punct de mai jos se **verifică întâi dacă mai e deschis** — unele s-ar putea să fi fost închise deja în feliile 5A/5B.

1. **RCA/CASCO pe comodat** — azi deduce 50%, ar trebui 0% nedeductibil.
2. **CASS** — liniar vs. tranșe fixe pentru PFA. *Verificare în cod.*
3. **TVA** — declanșarea „la data depășirii", nu „10 zile".
4. **Amortizare** — logica de plafon.
5. **Casă de marcat** — verifică dacă sfatul dat azi de bot e corect pentru transport alternativ.

### BLOCANTE — PRODUS

6. **Ingestia Uber** — research format raport → parser → `Document` cu `platforma="Uber"` (brut/comision/tva/net/cash/banca). **NU** prin `BankTxn` (ăla e format de tranzacție bancară, ar pierde exact câmpurile care contează fiscal).
7. **Clasificatorul bancar recunoaște depunerile Uber** — azi caută literal `"bolt"` (`classify.py:157`), deci încasările Uber nu nimeresc niciun bucket de venit.
8. **Reconciliere parametrizată per platformă** — bucket venit, sursă de adevăr, regula cash, praguri.
9. **Oblio 3b + 3c** (emiterea propriu-zisă + e-Factura) — *blocat pe:* cont Oblio + serie facturare + datele I-SHTEF ca furnizor.
10. **Loturile de voce aprobate și neaplicate** + cele 3 locuri rămase cu „Contai".
11. **ALINIEREA GATING-ULUI cu scara de tiere** — azi registrul, exporturile CSV, foaia de parcurs și certificatul sunt FREE, dar registrul trebuie la PRO. **De făcut ACUM, cât nu ai useri cărora să le iei ceva.**
12. **Modulul casă de marcat + declarația F4109** (neutilizare lunară) — azi doar semnalăm „ai nevoie de AMEF", fără să acoperim obligația care urmează. **SOLO REFUZĂ explicit segmentul numerar/casă de marcat** (vezi §3.0) — deci nu e doar un gol de conformitate, e un segment liber, cu concurență zero.

### BLOCANTE — COMERCIAL

13. **PREȚUL FINAL pe fiecare treaptă** — azi sunt intervale. *Fără cifre nu se pot crea Products/Prices în live.*
    📌 **Ancoră verificată (aug 2026): SOLO costă 229 lei/lună la preț complet**, după emiterea codului de TVA. Susține grila din §1 (99-149 / 179-199 / 289-349) — **nu** prețuri mai mici. Liderul de bătut e la 229 cu procesare umană și cutie neagră; nu intrăm sub el din reflex.
14. **Juridic** — termeni și condiții, politică de confidențialitate, temei de prelucrare, retenție. *Stocăm CNP, CUI, venituri.*
15. **Suport** — cine răspunde, în cât timp, pe ce canal.
16. **Brand** — OSIM clasele 9/35/36/42 + domeniile coniar.ro/.com. **Înainte de orice reclamă.**

### BLOCANTE — LANSARE

17. **Călirea Stripe** — fallback pe `stripe_customer_id` când `metadata.user_id` lipsește · alerte admin pe ramurile tăcute · ordinea evenimentelor · backfill trial pentru userii existenți · șters `STRIPE_PUBLISHABLE_KEY` (declarată, nefolosită).
18. **Proba de foc în sandbox** — plată reală, userul devine PRO, adresa ajunge în DB.
19. **Test cap-coadă cu USER NOU** — de la `/start` la prima declarație și prima plată, fără ajutor din partea ta.
20. **Trecerea pe live Stripe** — cont activat · Products/Prices live · endpoint webhook nou cu secret nou · chei live · plată reală + stornare.
21. **Prezentare + marketing** — *sursa textelor e* `docs/INVENTAR-CONIAR.md` (ce face produsul azi), nu busola.

### BLOCANT DOAR PENTRU TREAPTA MAX

22. **§1.2 depunere automată în SPV** — rațiunea de a exista a lui MAX. *Necesită înainte:* research pe împuternicirea ANAF (cum depui legal în numele altuia, la scară) + cine răspunde dacă o depunere eșuează sau întârzie.
    **DECIZIE DE LUAT:** lansăm cu 3 trepte și MAX „în curând" (listă de așteptare), sau cu toate 4?

### AMÂNATE DELIBERAT (după lansare)

§1.4 Salt Edge (axa bancară merge cu PDF importat manual) · §3.3 idei avansate · momentele PRIMA-DATĂ · cei 2 diferențiatori neconstruiți din §3.1 · cod mort intern · pereții 🟡 din T2 · felia B web (regim pe dashboard).

### P10/P11 — ce este și unde se încadrează

**Nu e în busolă deloc** — vine din auditul T2 (trecerea 2, flux cap-coadă), notat doar în memoria de lucru. Pe scurt: **motorul D212 din CHAT e regim-orb** (`app/domain/declaratie_unica.py` — zero mențiuni de regim/normă, calculează mereu sistem real), pe când cifra corectă, regim-aware, e pe dashboard + alerte (`tax_engine.compute_d212_anual`). Reparația: fie unifici estimarea din chat pe `compute_d212_anual`, fie pui un avertisment „ești pe normă → vezi dashboard" + setter de normă în chat (azi setterul e doar web).

**⚠️ Verdictul s-a SCHIMBAT față de audit — fereastra e DESCHISĂ ACUM.** La T2, concluzia a fost „latent, impact ≈0", pe motiv că norma pentru CAEN 4933 e permisă **doar de la venitul 2026** (OMF 1960/2025 Art. III, gardian în `norma_venit.py`), iar pentru 2025 ridesharing era sistem real OBLIGATORIU pentru toți. Dar suntem ÎN 2026: un șofer care alege acum norma pentru venitul 2026 și cere o estimare în chat primește un calcul de sistem real. Divergența nu e mică (exemplu din audit: ~28.000 vs. ~8.000 lei, de 3,5×).

**Atenuări reale:** estimarea din chat e etichetată „estimare orientativă", nu declarație depozabilă · norma e opt-in și se alege doar din web · dashboard-ul și alertele dau cifra corectă.

**Încadrare — de decis de Stefan.** Nu e o eroare de calcul (motorul de sistem real e corect), e un motor care nu întreabă în ce regim ești. Dar, după principiul de la capul secțiunii („orice calcul fiscal incomplet e blocant"), un număr de 3,5× mai mare arătat unui om pe normă e exact genul de lucru care distruge încrederea o singură dată.

**REPARAȚIA: pentru userii pe normă, NU afișa cifra deloc.** Nu „cifra + avertisment" — *omul citește numărul, nu nota de subsol*. Un avertisment lângă o cifră greșită lasă cifra să facă dauna oricum: ăsta e numărul pe care și-l notează, pe care îl pune deoparte, pe care îl repetă la telefon. În estimarea din chat, dacă regimul e normă: mesaj („ești pe normă de venit — cifra ta se calculează altfel, o vezi în dashboard") + buton spre dashboard. **Zero cifre în mesaj.** Ieftin (o ramură în afișaj, nu unificarea motoarelor) și onest: nu ascunde nimic, doar trimite unde e adevărul.

---

## §4. JURNAL (cronologic — pentru continuitate la repornire)

- **2026-07 (iulie):** Faza fiscală COMPLETĂ (regim auto D212 + audit general 3 treceri + reparații pre-lansare N1 IBAN/N2 categorie/N3 buton, PR #88-104, 818 verde). Stefan a oprit lansarea: Coniar trebuie contabil COMPLET (toate declarațiile + integrări), nu doar D212. Audit intern făcut → diagnostic "creier fără brațe". Research azi (Claude, comprehensive): e-Factura fezabil, SPV via împuternicit (model SOLO), Open Banking via agregator, NO Bolt/Uber API (reframe la import+AI), Stripe+ghișeul.ro plată, D397=armă secretă. Plan v0.1 scris. URMĂTORUL: research avansat multi-AI pe depunere declarații. Research #2 (depunere SPV, triangulat 4 surse) COMPLET → DECIS traseu D→A mapat pe tiere. CERT: împuternicit legal fără limită clienți, depunere automatizabilă server-side (fără API, via DUKIntegrator), răspundere rămâne la PFA. Descoperiri: procura notarială nu mai obligatorie (onboarding digital), D212 din SPV-PF cu user/parolă (model C ~1-click zero-CECCAR), art.12(1) OG 65/1994 cere firmă CECCAR parteneră nu angajat. De validat cu avocat: granița CECCAR pt Faza 2. Research #3 (competitiv top-world, triangulat 4 surse Claude+Kimi+Gemini+Perplexity) COMPLET. Consens masiv: SOLO=cutie neagră cu procesare umană (erori documentate 3k→10k€), fără feed bancar/AI/bot. 4 diferențiatoare gol-de-piață (estimare live, reconciliere three-way ANAF unic-mondial, categorizare AI PSD2, asistent conversațional). Principii încredere (motor determinist nu LLM, human-approves-AI-files, învață din corecții). Ordine extindere: ridesharing→curierat→IT→profesii→chirii. Prețuri 3 tiere 99/199/349. Anti-pattern: mileage GPS=zero valoare RO. FAZA 3 busolă completată. Scheletul plan complet informat de research → gata de umplut pas cu pas (fiecare pas: research adânc → build).
- **[iulie 2026] BUILD 1.1 pas 1:** orchestrare Uber D390/D301 — reparată gaura reală (șofer Uber primea furnizor Bolt/EE greșit în D390). Infra per-brand (deja folosită de D100) extinsă la D390/D301: operator corect per platformă din sursă unică, split proporțional cu invariant Σ==baza, brand neatribuit oprește cu mesaj (opțiunea b, nu depune incomplet). 15 teste noi, 833 total verzi. Rămâne: D207, D700.
- **[iulie 2026] BUILD 1.1 pas 2:** D207 generator — construit contra XSD OFICIAL ANAF (descărcat d207_20025020.xsd v1.02, confirmare byte-cu-byte, nu inferență). PAS 0 a corectat o presupunere: sect_II+benef sunt frați în secvență, nu imbricați. Agregare anuală 12 luni cu reconciliere garantată cu Σ D100 (A2). Bolt 04/EE impozabil, Uber 25/NL scutit-dar-obligatoriu-declarat (motivul D207). Opțiunea b (neatribuit oprește). 13 teste noi, 846 verzi. Wire-up UI separat. Rămâne: D700/317, buton D207.
- **[iulie 2026] BUILD 1.1 pas 3:** D700/art.317. Recon a descoperit un BUG REAL de deconectare: has_cod_special_tva=regim_tva==SPECIAL_INTRACOM, dar niciun flux nu seta SPECIAL_INTRACOM (doar testele) → user cu cod rămânea NEPLATITOR → D700 permanent + D301 ascuns (declarația lunară obligatorie!). Fix _comuta_regim_intracom() gardat în update_profile (punct unic): cod→SPECIAL_INTRACOM, garda PLATITOR_21 (nu retrograda plătitor, art.317 irelevant pt plătitor complet), simetric. + ghid D700 7 pași (nu generator — înregistrare web SPV). 8 teste noi, 854 verzi, D301/D390 neatinse. Rămâne: buton D207. SET DECLARAȚII RIDESHARING COMPLET.
- **[iulie 2026] BUILD 1.1 pas 4 (ultimul):** wire-up UI D207 — buton în bot (meniu TVA, callback d207|{year}) + dashboard (genD207 JS anual cu XML activ) + rută web + handler. Oglindește D212 (anual, fără month) + D390 (livrare XML). Zero logică fiscală nouă (generatorul face tot). 7 teste noi, 861 verzi, rutele lunare + D212 neatinse. §1.1 COMPLET 100% — set declarații ridesharing Profil A generat ȘI accesibil.
- **[iulie 2026] RESEARCH #4 (minimul CECCAR, triangulat 4 surse).** Verdict: minim CECCAR ridesharing = ZERO. PFA depune singur legal; Model A software+self-file = cost zero inatacabil; reprezentarea nu e rezervată. Contabil angajat blocat de art.12 → soluție PFI independent + contract B2B audit (cost per-user zero). Necesită avocat: T&C + structură + art.348. Deblochează Faza 2. Structura confirmă traseul D→A din busolă.
- **[iulie 2026] RESEARCH #5 + BUILD §1.5 (arma secretă, pas 1).** Research: D397 e depus de PLATFORMĂ (OPANAF 382/2025), INACCESIBIL șoferului (intern ANAF — nici SPV, nici dosar fiscal, nici precompletare D212). DAC7 (F7000) e proxy anual dar tot inaccesibil PFA din cod. REFRAME: arma secretă = reconciliem sursele controlate de șofer (Bolt API ↔ declarat ↔ bancă), poziționat "previi verificările ANAF" (durere reală: 56.000 șoferi prinși, 151M lei creanțe, plăți suspendate 100 flote sep 2025). Audit: 80% pre-alimentat (surse Bolt există). BUILD pas 1: bolt_amount_reconcile pe axa curată brut-API↔declarat (ortogonal de prezența existentă, prag max(5 lei,1%), nudge neutru la /bolt). 13 teste noi, 874 verzi, prezența neatinsă. Pas 2 (bancă) + Uber (fără API) + atașare (a) = follow-up corect separate.
- **[iulie 2026] RESEARCH #6 (agregatori PSD2 bancă).** GoCardless/Nordigen închis înscrieri noi. Ales: Salt Edge (Partner Program fără licență, acoperire RO completă, românesc); alt Enable Banking (cere licență). AISP: nu proprie dacă data recipient (date=input fiscal, nu ecran conturi; EBA Q&A 2018_4098); avocat pt flux. Cost ~150-500€/lună. SCA 180 zile. DECIZIE: extinde PDF manual (ING/Revolut) acum, pilot Salt Edge paralel, scalează la nevoie. Axa bancară reconciliere (pas 2) deblocabilă cu PDF manual.
- **[iulie 2026] BUILD §1.5 pas 2 (arma secretă COMPLETĂ).** Axa bancară cumulativă net↔net. Recon a prins 2 capcane în cod: #1 cash (Bolt depune doar card în bancă; summary["net"] include cash → false-alarmă la fiecare șofer cu cash) → rezolvat prin net_bancabil (payment_method != cash din bolt_orders); #2 timing (payout săptămânal traversează luni, nicio mapare cursă→payout) → rezolvat prin verdict cumulativ YTD (timingul se spală). bolt_bank_reconcile_cumulative ortogonal (nu atinge pas 1 nici prezența; summary["net"] neatins, pas 1 folosește ["brut"]). Prag larg max(50 lei, 2%). Nudge neutru "pe {an} banca ≈ Bolt net card". 16 teste noi (test cash crucial explicit), 890 verzi. Arma secretă = 3 axe complete. Uber (fără API) + ING/Revolut (fixture-uri) = follow-up.
- **[iulie 2026] RESEARCH #7 (plată Stripe vs Netopia).** Ales Stripe+Billing lansare (RON-nativ pt SRL RO — mitul FX fals; motor abonamente complet, DX Python). Netopia mai ieftin comision dar construiești tu motorul. Twispay/xMoney = alt local cu motor gestionat. Prag migrare ~1000 abonați. Descoperire: niciun procesator nu emite factura → webhook→SmartBill/Oblio→e-Factura (B2C obligatoriu 2025); §1.7 se leagă de §1.3. TVA 21% pe abonament dacă înregistrat (prag 395.000 lei, OG 22/2025).
- **[iulie 2026] RESEARCH #8 (e-Factura, ULTIMA piesă research Faza 1).** Descoperire legală: șoferul NU emite factură/bon pasagerului (OUG 49/2019 — platforma o face), fără casă de marcat → flux pasager dispare, produs mai simplu. Build vs wrapper: Oblio (SDK Python, 29€/an e-Factura inclusă) vs build ANAF direct (2-4 luni + risc) → wrapper. Comision Bolt/Uber = portal-first (CSV/PDF; SPV secundar pt autofacturi RO emergente nov 2025). Abonament Coniar: Stripe webhook→Oblio→SPV, neplătitor TVA sub 395k. Rezolvă #3. FAZA 1 RESEARCH COMPLET — toate deciziile luate.
- **[iulie 2026] BUILD §1.7 Felia 1 (fundația abonament)** — PRIMUL build din faza de construcție post-research. Greenfield dar oglindește șabloane mature (triada Bolt→triada Stripe, migrarea 019→023, HMAC Telegram→verificare Stripe pt Felia 2). 4 câmpuri User + migrarea 023 idempotentă + config stripe_* Optional + subscription.py (tiere FREE/START/PRO/MAX decizia #4, gating primitiv NEaplicat). Inert prin construcție (userii existenți FREE, zero schimbare comportament). Doar DATE — zero Stripe API, zero chei. 10 teste noi, 900 verzi. Felii rămase: 2 webhook (chei), 3 Oblio (DATE CONIAR lipsesc), 4 gating.
- **[iulie 2026] RESEARCH #9 (model freemium/trial — golul din decizia #4).** DECIS: REVERSE TRIAL 30 zile PRO → FREE "Radar" permanent (vizualizare+alerte+teaser discrepanță+provocări). Instinctul lui Stefan (probă la tot → vizualizare+alerte) = reverse trial, validat. 30 zile ca să prindă ciclu fiscal (arma secretă cere date acumulate). Arma secretă = teaser blocat (frica ANAF + loss aversion). Concurenți: gratis să urmărești, plătești să depui (Indy/Norman/Accountable). Fără card la înscriere. Țintă conversie 5-10% (activare = cheia). Împinge anual. Umple golul FREE din busolă → deblochează Felia 4 gating cu mapare completă.
- **[iulie 2026] BUILD §1.7 Felia 4a (mecanism reverse trial).** Câmp trial_ends_at + migrarea 024 + user_tier() trial-aware. Ordine prioritate: abonat activ→stripe_tier (plata primează, MAX în trial rămâne MAX) / în trial→PRO / altfel→FREE. is_in_trial/trial_days_left (now injectabil, teste deterministe). Onboarding setează +30 zile idempotent (re-onboarding nu resetează). Fără logică useri existenți (nu-s în producție). Rezolvă GAP-ul reverse trial. 17 teste noi, 917 verzi (1 test Felia 1 adaptat: "023 ultima"→"după 022", gardian păstrat nu slăbit). Gating NEaplicat (4b aplică). Următoarea: 4b (router tier + _require_tier + teaser blocat).
- **[iulie 2026] BUILD §1.7 Felia 4b (gating + teaser = FREE "Radar" real).** gating.py sursă unică. Gating pe features (depunere/D207→PRO, Bolt sync→START) via user_tier (trial-aware 4a). Teaser arma secretă: motoarele neatinse, doar afișajul ramifică (FREE=sumă+copy liniștitor, PRO/trial=complet). Verdictul pozitiv rămâne pt toți. Gating REAL nu cosmetic: închise sync nocturn + buton Bolt (altfel FREE primea sync). Alertele FREE (neatinse). Ton "tu"+emoji. 32 teste noi, 949 verzi (fixture-uri reparate + 1 test care trecea din motiv greșit făcut onest). Trial=PRO peste tot (test 6 leagă 4a-4b). FOLLOW-UP lansare: backfill trial useri existenți (acum irelevant, fără useri).
- **[august 2026] BUILD §1.7 Felia 2 / Brick 2a (fundația plății Stripe).** Primul brick din felia webhook — DOAR fundația: SDK + setter + mapare price ID→tier, zero Stripe API live (2b checkout, 2c webhook urmează). Testabil fără chei. `set_subscription` scrie DIRECT pe obiect + flush (NU prin update_profile, a cărui allowlist n-are câmpurile Stripe → ar fi fost silent no-op, exact bug-ul vehicule_repo.update/regim_utilizare); `clear_subscription` pune status='canceled' dar păstrează customer_id/subscription_id/tier (istoric + reabonare fără client duplicat). `stripe_config.py` citește harta la APEL nu la import (testabil prin monkeypatch pe settings). Anti-no-op dovedit în 2 straturi (valori pe obiect + recitire din sesiune nouă după commit) + gardian care cade dacă un câmp Stripe ajunge în allowlist. Cazuri acoperite: MAX în trial rămâne MAX (regula 4a), past_due nu dă tier, clear→FREE (sau PRO dacă trial valid), price străin→None, zero-import-stripe-în-logică. Neatinse: update_profile, _ensure_trial_started, subscription.py, migrările 015-024. Diff strict aditiv +72/-0. 22 teste noi, 971 verzi.
- **[august 2026] BUILD §1.7 Felia 2 / Brick 2b (checkout Stripe).** `stripe_checkout.py` (`create_checkout_session`, SDK lazy, `client_reference_id` + metadata pe sesiune ȘI abonament). Flux bot în DOI TIMPI: callback „Activează PRO" → creează sesiunea la intenție reală → buton URL „Plătește" → checkout.stripe.com. Pagini succes/cancel cosmetice (zero DB, zero auth). DECIZII ARHITECTURALE: webhook 2c = singura scriere (2b: garanție STRUCTURALĂ, fără `session` în semnătură, dovedit pe AST); buton URL nu WebApp (3DS + redirect bancar); butonul duce la tier-ul cerut de feature; identitatea la întoarcere prin `client_reference_id`→2c. METADATA PE ABONAMENT peste brief: `client_reference_id` apare DOAR în `checkout.session.completed`, iar reînnoirile/anulările poartă doar metadata abonamentului — fără ea 2c ar fi orb după prima plată. 1 linie de copy din `upgrade_text` atinsă (butonul zice „Activează PRO", textul zicea „Deschide Dashboard" — coerență afișaj==realitate, ca #97/#101). Degradare: fără chei → „Deschide Dashboard" (4b), cele 4 teste 4b rămân verzi neatinse. 31 teste noi (client_reference_id crucial, „2b nu scrie" pe AST, pagina de succes fără auth), 1002 verzi. Rămas: 2c webhook.
- **[august 2026] BUILD §1.7 Felia 2 / Brick 2c (webhook — 🎉 LANȚUL DE PLATĂ COMPLET).** `stripe_webhook.py` (`verifica_semnatura` + `proceseaza`, commit la apelant) + rută `/stripe/webhook` (prima fără `_require_user`, raw body, auth = semnătura Stripe). 4 evenimente: `checkout.completed` (tier din metadata, doar `paid`) · `updated` (comută pe status + tier din price + `cancel_at_period_end` NU taie) · `deleted` (clear) · `invoice.paid` (ignorat, 200). DESCOPERIRILE RECONULUI, aplicate: checkout n-are price ID (deci tier din metadata) · `invoice.paid` n-are cale de identificare, iar repo-ul n-are lookup după `stripe_customer_id` (deci ignorat; `updated` acoperă reînnoirile) · `cancel_at_period_end=true` sosește ca `updated` cu status ÎNCĂ active (a tăia accesul acolo = a fura zile plătite). COD RĂSPUNS anti-retry (200 pt stări permanente, 500 doar tranzitoriu — Stripe reîncearcă ~3 zile pe non-2xx). SEMNĂTURI REALE în teste (HMAC ca Stripe, nu mock peste verificare): prinde corp-modificat→400 (upgrade pe furiș), semnătură-veche→400 (replay), fără-whsec→400. 2c respectă 4a (deleted lasă trial valabil → PRO, nu FREE). 2 CORECTURI ONESTE: fixture-ul de test omitea `event.object` (stripe 15.x îl citește ca să distingă v1/v2) — bug în test, nu în cod; iar un test 2b a picat legitim (felia lui ajungea până la `run_flask`, acum include webhook-ul care TREBUIE să scrie) → granița mutată la `def stripe_webhook`, intenție păstrată + test nou explicit pe ambele blocuri. Peste brief: test upgrade de tier (START→MAX prin `updated`) + test deleted-cu-trial-valabil. 30 teste noi, 1032 verzi. FOLLOW-UP: apărare ordine evenimente (pre-lansare). Rămas: Felia 3 Oblio.
- **[august 2026] BUILD §1.7 Felia 3 / Brick 3a (fundația facturării).** Config `oblio_*` + `oblio_config.py` (`is_oblio_configured`/`campuri_lipsa`, citite la apel) + migrarea 025 (`factura_abonament` + adresă pe users) + `billing_address_collection="required"` la checkout + captarea adresei la webhook. DOUĂ GARANȚII ÎN SCHEMĂ, nu în cod: `stripe_invoice_id` UNIQUE (o plată = o singură factură — webhook-urile se livrează repetat) și FK **RESTRICT** nu CASCADE (factura emisă = document fiscal, arhivare 10 ani; ștergerea unui user cu facturi EȘUEAZĂ deliberat). Adresa: umple GOLURILE, nu suprascrie (onboarding-ul bate formularul de plată); lipsa ei nu blochează activarea (omul a plătit). Peste brief: salvez și `localitate`/`judet` din același payload, cu aceeași regulă. ZERO apeluri Oblio (verificat AST). ATINS NEPLANIFICAT: 4 teste asertau „024 e ULTIMA migrare" → rescrise pe ORDINE relativă (`index(024) == index(023)+1`), gardian păstrat nu slăbit — aceeași reparație ca la 4a („023 ultima"→„după 022"); capcana eliminată și din testul nou 025, ca 3b să nu-l spargă. 21 teste noi (al 21-lea = gardianul FK RESTRICT, adăugat la recenzie odată cu schimbarea CASCADE→RESTRICT; verifică ambele locuri, SQL-ul migrării ȘI modelul ORM), 1053 verzi. Rămas: 3b emiterea (blocat pe DATE CONIAR furnizor).

---

*Fișier viu. Actualizat la fiecare pas. Se citește PRIMUL la repornirea conversației.*
