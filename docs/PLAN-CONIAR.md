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
- **„Fă-o imposibilă, nu o verifica."** O verificare se uită într-un drum de cod nou; o imposibilitate nu. Precedente: `keywords=[]` la `vehicle_acquisition` (inaccesibilă scoring-ului **prin construcție**, nu prin filtru) · excluderea achizițiilor **la sursă** în `tax_engine`, nu prin scădere ulterioară · FK **RESTRICT** pe `factura_abonament` (ștergerea unui user cu facturi EȘUEAZĂ) · **UNIQUE** pe `stripe_invoice_id` (o plată = o factură, orice ar face retry-urile Stripe). Garanția stă în schemă sau în formă, nu în vigilența cuiva.
- **„SURSĂ UNICĂ PE VALOARE NU ÎNSEAMNĂ SURSĂ UNICĂ PE JUSTIFICARE."** Plafonul CASS de 72 avea o singură sursă și era **corect**; motivul lui — actul care l-a introdus — a fost copiat **greșit în nouă locuri**, iar disciplina de sursă unică **n-a prins nimic**, fiindcă acoperea *valoarea*, nu *atribuirea*. Când muți o cifră într-o constantă, **mută și temeiul ei acolo, sau lasă doar o trimitere — niciodată o copie a justificării**. (Dovedit la PR #127.)
- **Marcaj `TEMEI-NEVERIFICAT`** — convenție de urmărire: orice atribuire legală **nesusținută de forma consolidată** poartă șirul fix `TEMEI-NEVERIFICAT` în cod, ca lista lor completă să se obțină cu un `grep`, nu cu memorie sau cu un blocant separat. Se pune **o singură dată, la sursa atribuirii** (nu în fiecare loc care o consumă — vezi principiul de mai sus) și se scoate **doar** când temeiul primește data verificării pe forma consolidată. E perechea operațională a lui **F3**: gardianul oprește proza fiscală nouă fără temei datat, marcajul ține evidența celei vechi.
- **„UN GARDIAN CARE AFIRMĂ UN PARAMETRU FISCAL E EL ÎNSUȘI PROZĂ FISCALĂ."** La PR #128, valoarea venea din sursă unică, dar **aserția din test era o copie de mână**. Testele intră în lista locurilor unde se afirmă reguli — deci **ancorele se derivă din parametru, nu se scriu**.
- **„UN GARDIAN CARE APĂRĂ GREȘEALA E MAI RĂU DECÂT NICIUNUL, fiindcă arată a siguranță."** Cu ancoră literală, testul ar fi cerut păstrarea cifrei vechi și ar fi **picat exact pe cine o corecta**.
- **„PRIMA VERSIUNE A UNUI GARDIAN APĂRĂ INSTANȚA, NU CLASA DE GREȘEALĂ."** S-a repetat **de trei ori într-o singură sesiune** (august 2026):
  1. ancora de test scrisă literal `6` în loc de derivată din `cass_jos` — apăra **valoarea de atunci**, nu regula;
  2. temeiul cerut ca simplă referință în loc de referință **verificată cu dată** — apăra **prezența unei citări**, nu adevărul ei;
  3. gardianul de wiring verificând cele patru call-site-uri cunoscute în loc să scaneze repo-ul — apăra **locurile știute**, nu proprietatea „niciun call-site nearhivat".

  **CAUZA E STRUCTURALĂ, nu neglijență:** gardianul se scrie imediat după ce repari cazul concret, deci **cazul e ce ai în cap**. Instanța e vie, clasa e abstractă.
  **COROLAR:** după ce scrii un gardian, **NU** întreba „prinde ce tocmai am reparat?" — răspunsul e garantat *da* și nu spune nimic. Întreabă **„care e forma GENERALĂ a greșelii, și prinde o versiune pe care n-am văzut-o?"**
  **CÂND se pune întrebarea contează la fel de mult ca întrebarea însăși.** Toate trei incidentele au fost prinse la **REVIEW**, niciunul la scriere — exact ce prezice principiul. În minutul în care ai scris gardianul, **instanța e încă prea vie ca să vezi clasa**. Deci întrebarea se pune **la rece**: la review, sau după o pauză. Cine lucrează singur trebuie **s-o amâne deliberat**, nu s-o pună imediat.
  Și: **o intrare din lista albă poate purta propria condiție de expirare**, altfel excepțiile temporare devin permanente tăcut.
- **„Un gardian se judecă după modul lui de eșec, nu după cât e de deștept."** **Fail-closed bate fail-open.** Un gardian al cărui mod de eșec e chiar lucrul păzit **nu e gardian** — vezi de ce poarta de achiziție e o întrebare, nu detecție pe VIN (§4, august 2026). Înainte de orice detecție automată cu miză fiscală: scrie explicit ce se întâmplă când semnalul **lipsește**. Dacă răspunsul e „comportamentul de dinainte, adică bug-ul", reproiectează.

### 3.3 IDEI AVANSATE (notate, nu pt început)
- ✅ **Foaia de parcurs MANUALĂ e CONSTRUITĂ și livrată** (buton „🛣️ Foaie parcurs" + `/sterge_tura` + export Excel): ture, km, litri — DOVADĂ la control, nu calcul (comutatorul deductibilității e regimul vehiculului, vezi 5A/5B). Ce rămâne idee amânată e doar versiunea AUTO-GENERATĂ de mai jos.
- ⏳ [idee amânată] Foaie de parcurs auto-generată (GPS + date Bolt) — dificil + ❓INCERT legal, validează cu consultant
- Arhitectură microservicii + retry asincron pt SPV (XML ANAF se schimbă des, SPV instabil)
- Optimizare fiscală predictivă ("dacă treci normă→real economisești Y"; timing înregistrare TVA; stopaj 2% Bolt cu certificat rezidență Estonia)
- **Dosar de venit pentru bănci** — pachet exportabil (venituri dovedite + declarații depuse) pt credit/leasing. Șoferul PFA e refuzat des la bancă fiindcă nu-și poate proba venitul; noi avem deja datele.
- **SPV Inbox Manager** — citește și traduce mesajele din SPV („ce vrea ANAF de la mine?"). *Are sens DOAR după depunerea automată* (blocantul „§1.2 depunere automată în SPV", azi M1) — până atunci n-avem conexiunea.
- **Simulator PFA vs. micro-SRL** — extinde simulatorul de regim existent (normă vs. real) cu a treia formă juridică. Întrebarea apare natural la venituri mari.
- **Benchmark anonimizat între useri similari** („șoferii ca tine deduc în medie X") — *cere o bază de useri destul de mare ca anonimizarea să fie reală*. Nu înainte de lansare.

### 3.4 DE EVITAT (gimmick/ROI slab)
- ⛔ Mileage GPS ca feature fiscal (valoare ZERO în RO — sistem real deduce costuri reale 50/100, NU km)
- Insights demand "unde să conduci" (Gridwise-style — nu ține de contabilitate, date indisponibile Bolt API)
- Chatbot generic fără acces la datele contului (ChatGPT o face gratis)
- E-commerce/stocuri + multi-țară înainte de a domina RO
- ⛔ **„Diurnă automată" pentru fiecare zi lucrată** — art. 68 alin. (5) lit. i) cere deplasare **ÎN ALTĂ LOCALITATE**. Un șofer care conduce în orașul lui NU e în delegare. Automatizarea ar produce o deducere sistematic nelegală, la scară, pe toți userii — exact genul de „optimizare" care aduce controlul pe care noi promitem că-l previi.
- ⛔ **Generator de contract de comodat** — comodatul e pe cale să fie ELIMINAT din autorizarea transportului alternativ (vezi punctul de urmărire legislativă din §2). N-are sens să construim o unealtă pentru un mecanism care poate dispărea.
- ⛔ **Cont bancar propriu / BaaS / micro-credite / plata automată a taxelor în stil Hnry** — cer licență de instituție de plată. Mută produsul din contabilitate în fintech: alt cost, alt risc, alt regulator, altă echipă. (Seiful de taxe VIRTUAL — blocantul „Seiful de taxe v1", azi I4 — dă 80% din valoare cu 0% din licență.)

---

## §2. ÎNTREBĂRI DESCHISE & DECIZII DE BUSINESS

> **Numerele sunt ID-uri de decizie, nu poziții** — nu se renumerotează, ca trimiterile din jurnal să rămână valide. **#2** (ritmul datelor) și **#4** (prețul) au fost scoase de aici: #2 e închis în §1.6 (ritmul produsului = ritmul payout-ului), #4 trăiește ca blocantul „PREȚUL FINAL pe fiecare treaptă" din §5 (azi C1), unde contează la lansare.

1. ✅ #1 REZOLVAT — traseu D→A, vezi §1.2
3. ✅ #3 e-Factura build vs wrapper — REZOLVAT: WRAPPER Oblio (SDK Python, 29€/an, e-Factura inclusă). Build ANAF direct = 2-4 luni, evitat.
5. ✅ #5 Ordine extindere — REZOLVAT (ridesharing→curierat→IT→profesii→chirii, vezi 2.1)
6. ✅ #6 Structură juridică CECCAR — REZOLVAT (research triangulat 4 surse: Claude+Perplexity+Gemini+cel intern). VERDICT: minimul CECCAR pentru ridesharing = ZERO. PFA are drept legal să depună singur (Legea 82/1991 art.1(5)+10(4¹)); nicio certificare D212 obligatorie; reprezentarea (împuternicit) NU e rezervată profesiei. Model A (software + user depune din SPV-ul lui) = zero CECCAR, cost zero, inatacabil (art.348) — se mapează pe traseu D. Model B (reprezentare) = tot zero-CECCAR-rezervat. Plătești CECCAR doar dacă vinzi serviciul contabil în sine (premium opțional Faza 2). SOLO confirmă modelul (firmă software CAEN 6210, NU firmă CECCAR, depune ca împuternicit).
   - CAPCANĂ contabil angajat (art.12 OG 65/1994): expertul angajat pe SRL NU poate presta pentru clienții SRL-ului. Soluție: reziliezi CIM, ea face PFI/cabinet propriu, contract B2B cu Coniar (audit algoritmic general, nu per-client → cost per-user zero). NECESITĂ AVOCAT: T&C exonerare + structura contabilului + statusul art.348 (înăsprire Senat oct 2025 spre 6luni-5ani).
   - AVERTISMENT (din Gemini): modelul BPO-mascat (platforma preia semnătura clientului, ca SOLO) e riscant — raport Incorpo.ro acuză SOLO de mii de falsuri (semnături generate cu mouse-ul). Dacă mergem spre depunere de către noi, userul trebuie consimțământ REAL informat, nu semnătură auto.

### 📡 PUNCT DE URMĂRIRE LEGISLATIVĂ — comodatul în transportul alternativ

**Ce s-a depus:** proiect de lege la Senat (**iunie 2026**, parlamentari PSD) care modifică **art. 13 din OUG 49/2019**. Autorizațiile s-ar elibera doar pentru autoturisme deținute în **proprietate, închiriere sau leasing** — **comodatul nu ar mai fi acceptat**.

**Cât de mare e:** peste **45.000 de mașini**, ~**70% din parcul autorizat** (date ARR).

**⚠️ NU E ÎN VIGOARE.** Poate fi modificat, poate primi perioadă de tranziție, poate fi respins. Discuții similare durează de ani de zile în România. **Nu construim pe presupunerea că trece** — dar nici nu ne lasă nepregătiți dacă trece.

**CONSECINȚA PENTRU PRODUS:** dacă trece, masa de șoferi trece pe mașină **în proprietate** → **AMORTIZAREA devine mecanismul central de deductibilitate**, nu un caz marginal. De aici prioritatea blocantului „MOTORUL DE AMORTIZARE" din §5 (azi F4, cere research înainte de build; gardianul de achiziție — ÎNCHIS, PR #123 — oprește doar tratarea greșită, nu ține loc de motor). Tot de aici și interdicția din §3.4 pe generatorul de contract de comodat.

---

## §3. RESEARCH-URI DE FĂCUT (coadă, în ordine)

1. ✅ Research depunere SPV (triangulat 4 surse) — FĂCUT, vezi §1.2
2. ✅ Research competitiv top-world (triangulat 4 surse) — FĂCUT, vezi FAZA 3
3. 🔬 **URMĂTORUL — la construcția fiecărui subpas Faza 1: research adânc pe acel subpas ÎNAINTE de build** (ex. e-Factura API, PSD2 agregator, DUKIntegrator upload)
4. ⬜ Per pas, la construcție: research adânc pe acel subpas înainte de build (regulă permanentă)

---

## §5. PÂNĂ LA LANSARE

> **Dacă întrebi „ce mai e până la lansare?", răspunsul e AICI. Nu în §1.x, nu în jurnal, nu în capul modulelor de cod.**
>
> **CONVENȚIE DE NUMEROTARE (diferită de §2): PREFIX PE SUBSECȚIUNE** — `F` fiscal · `P` produs · `C` comercial · `L` lansare · `I` ieftine-înainte-de-lansare · `M` MAX. Blocantele se renumerotează pe măsură ce se închid — §5 e **listă de bifat**, nu jurnal de decizii ca §2. În jurnal, blocantele se referă pe **NUME**, niciodată pe ID; prefixul e **tot navigațional**, ca să găsești rândul, nu ca să-l citezi.
>
> *De ce prefix și nu secvență continuă:* numerotarea continuă peste toate subsecțiunile făcea ca închiderea unui singur blocant fiscal să renumeroteze **tot restul listei** — a treia oară în două zile, ~20 de linii de fiecare dată, plus trimiterile „azi N" din alte secțiuni. Prefixul oprește raza de explozie la subsecțiune: închizi un F, se mișcă doar F-urile.

### SCARA DE TIERE — principiul

Logica treptelor nu e „câte funcții primești", ci **cât de multă muncă îi luăm de pe umeri**:

- **START** — *înregistrează și vede.* Bonuri, facturi, venituri prin poză; afișare vizuală. **NU** generează registrul, **NU** generează declarațiile — doar le vede.
- **PRO** — *generează registrul și declarațiile, le depune SINGUR, cu îndrumarea noastră* (DUK Integrator + Java, pas cu pas).
- **MAX** — *depunem noi în SPV.* Toată treaba.

Fiecare treaptă mută o bucată de muncă de la om la noi. Gating-ul de azi trebuie aliniat la scara asta (vezi blocantul „ALINIEREA GATING-ULUI cu scara de tiere", azi P7).

### BLOCANTE — CORECTITUDINE FISCALĂ

> **Principiu:** orice calcul fiscal incomplet e blocant. Un impozit greșit distruge încrederea o singură dată și definitiv.
> *Auditat în cod (august 2026).* **Trei** au ieșit deja din listă: **RCA/CASCO pe comodat** (`posting.py:150-158` întoarce 0% pe comodat, felia 5B, tip nedeclarat → 50 conservator, comparație case-insensitive) · **TVA — declanșarea** (PR #121, vezi jurnalul) · **GARDIAN ACHIZIȚIE VEHICUL** (PR #123, vezi jurnalul — factura de autoturism nu mai cade pe `other_expense` = `FULL`; poarta e o **întrebare declanșată de sumă**, nu un clasificator) · **CONTRADICȚIA CASS** (PR #127, vezi jurnalul — **premisa era falsă**: nu era contradicție, ci un calificativ lipsă; ambele texte erau corecte, dashboard-ul spunea adevărul incomplet) · **SEMANTICA lui `is_salariat`** (PR #128, vezi jurnalul — flagul era un *proxy* („normă întreagă"), nu testul legal; rădăcina nu era în motor, ci în **întrebarea pusă userului**). **Ordinea de mai jos e ordinea de atacat**, și e ordonată pe *ce deblochează*, nu pe mărime: întâi **fundația de reproductibilitate**, fără de care nici corecturile deja făcute nu se pot dovedi (F1), apoi clasa cu cea mai mare expunere, verificabilă într-o trecere (F2), apoi **gardianul** care oprește reapariția problemei (F3), apoi ce cere research înainte de build (F4), apoi ce nu e muncă de cod și merge în paralel (F5).

> 📋 **PASUL 1 AL AUDITULUI PROZEI FISCALE E FĂCUT** — inventarul complet trăiește în **`docs/INVENTAR-PROZA-FISCALA.md`**: **96 de afirmații fiscale în proză, în 15 fișiere**, fiecare cu fișier:linie, temei (DA/parțial/NU) și severitate. **64 din 96 n-au niciun temei legal lângă ele.** Doar UNA (plafonul TVA) poartă forma completă articol + act + data verificării. Blocantul inițial „auditul prozei fiscale" s-a **despicat în trei**, pe baza a ce a găsit inventarul: unul e deja închis (contradicția CASS, PR #127), celelalte două sunt **F2** și **F3**. Restul celor 96 sunt **amânate deliberat**, cu trimitere la inventar.

- **F1** · 🔥 **DECLARAȚIILE NU SE PERSISTĂ — nici rezultatul, nici inputurile.** Nu există tabel; `grep "session.add|commit"` în `app/integrations/anaf/` întoarce **gol**. `RezultatDeclaratie` (`declaratii_service.py:164-181`) și `RezultatD212Service` (`:696-711`) sunt **dataclass-uri care trăiesc cât ține request-ul**; inputurile sunt **doar parametri de funcție** (`:714-730`). XML-ul pleacă prin `BytesIO` (`bot_contabil.py:1903-1905`) și dispare.
   **NU e gaură de conformitate pentru user** — copia autoritativă e în SPV. E gol de **REPRODUCTIBILITATE** și de **RĂSPUNDERE**:
   - recalcularea unui an trecut citește **tăcut profilul de azi** (regim, `is_salariat`, `is_pensionar`), deci poate da alt număr decât s-a depus;
   - **nu există istoric de declarații** pentru user;
   - motoarele fiscale s-au schimbat **de trei ori în august 2026** — nu putem distinge *„motorul era greșit atunci"* de *„userul a răspuns altfel atunci"*.

   **ABSOARBE fostul blocant „flagurile de asigurare n-au an".** Dimensiunea temporală o poartă **DECLARAȚIA, nu userul**: răspunsul e un **input al declarației**, nu o proprietate a omului. Flagul de pe `User` rămâne **precompletare**. **Alin. (8)** (întrebare despre *anul precedent*) își găsește locul aici.
   **E și FUNDAȚIA pentru „Audit Trail"** (I1): exportul cu temeiul fiecărei clasificări **n-are pe ce se sprijini** fără asta.
   **FORMĂ PROPUSĂ, de validat la build:** tabel **aditiv** cu `user_id` · tip declarație · perioadă (an/lună) · **inputurile ca JSON** (semnătura funcției e deja explicită) · sumele rezultate · XML-ul generat · timestamp. Cu loc pentru **indexul de încărcare** și **recipisa**, când depunerea se automatizează.
- **F2** · 🔺 **CELE 8 TERMENE DE DEPUNERE — clasa în care a căzut „10 zile".** Fiecare dintre cele 8 declarații își afirmă termenul (inventar #1, 8, 12, 17, 21, 25, 31, 34) și **niciunul n-are temei legal lângă el**. Sunt exact felul de dată la care legea se poate muta fără ca nimic din cod să semnaleze — cum s-a și întâmplat o dată.
   **Toate opt sunt în același fișier** (`fiscal_calendar.py`), deci se verifică **într-o singură trecere**, contra formei consolidate, ca la plafonul TVA. Severitate MARE pe toate: un termen greșit înseamnă o depunere ratată.
   ⚠️ La corectură, `fiscal_calendar.py` cere două atingeri, nu una: conținutul e **partajat** cu dashboard-ul prin `/api/v1/ghid`, iar testele îl blochează pe fraze (`test_ghid_obligatii_continut.py`).
- **F3** · **TEMEIUL OBLIGATORIU PENTRU PROZA NOUĂ — gardian, nu curățenie.** Modelul e `vat_plafon_msg.py`: articol + act modificator + **data verificării pe forma consolidată**, scrise în modul. Azi **una singură din 96** arată așa.
   ⚠️ **Gardianul cere temei VERIFICAT CU DATĂ, nu prezența unei referințe.** Distincția nu e teoretică — a fost **dovedită la închiderea contradicției CASS** (PR #127): plafonul CASS era atribuit legii greșite (141/2025 în loc de 239/2025), avea o referință scrisă lângă el, arăta a temei și era numărat „DA" în inventar. O referință fără dată de verificare e o afirmație despre lege, nu o dovadă.
   **De construit ACUM:** un gardian care **cade dacă apare proză fiscală nouă fără temei datat** — ca gardianul „10 zile", care există deja și funcționează. Fără el, inventarul se învechește din prima săptămână după ce-l terminăm și refacem munca peste un an.
   **Backfill-ul pe cele 64 fără temei: DUPĂ LANSARE**, în ordinea severității din inventar. E muncă mare și mecanică; gardianul e ce oprește hemoragia, backfill-ul e ce curăță trecutul.
- **F4** · **MOTORUL DE AMORTIZARE — nu există deloc. Cere RESEARCH înainte de build.** `grep amortiz` peste tot codul de producție dă **un singur** rezultat, cuvântul „amortizoare" într-o listă de piese auto. Zero model, zero categorie, zero plafon (nici cel de 1.500 lei/lună pt autoturisme), zero durată normală de funcționare, zero capitalizare, zero legătură între vehiculul din `vehicule` și o cheltuială anuală. **Un PFA cu mașina în proprietate nu deduce NIMIC azi** — pe o mașină de 60.000 lei, câteva mii de lei de impozit plătiți în plus, an de an.
   **Nu e o formulare de reparat, e o funcție de construit** — și, spre deosebire de „GARDIAN ACHIZIȚIE VEHICUL" (ÎNCHIS, PR #123), **cere research pe reguli înainte de a scrie o linie de cod**: plafonul aplicabil, durata normală de funcționare (Catalogul mijloacelor fixe), regimul de amortizare permis la PFA în contabilitate de partidă simplă, interacțiunea cu regimul 50/100 și cu tipul de deținere.
   *Miza poate crește brusc:* dacă trece proiectul de lege din §2 (comodatul scos din OUG 49/2019), masa de șoferi trece pe mașină în proprietate și amortizarea devine **mecanismul central de deductibilitate**, nu un caz marginal.
- **F5** · **Casă de marcat — VERIFICAREA SFATULUI.** Verifică dacă ce spune botul azi despre AMEF e corect pentru transport alternativ. *Ăsta e blocantul de **corectitudine**: să nu mintă.* **NU e duplicat** cu „Modulul casă de marcat + F4109" din blocantele de PRODUS — acela e blocantul de **acoperire**: să construim obligația care urmează după sfat. Se pot închide independent și în orice ordine.

### BLOCANTE — PRODUS

- **P1** · 🔥 **D212 NU PRODUCE NICIUN ARTEFACT.** Fără XML, fără fișier — **omul citește numărul pe dashboard și îl tastează singur** în formularul ANAF. E **singura declarație fără ieșire**, și e **cea mai importantă pe care o depune un PFA**.
   **Consecință directă:** n-are moment de generare, deci **nu poate fi arhivată ca celelalte patru** (F1 acoperă doar D100/D301/D390/D207 — vezi PR #131).
   **TREI VARIANTE DE DECIS:**
   - **(a) arhivare la SCHIMBARE** — scrii doar când numărul diferă de ultimul arhivat; transformă zgomotul în **cronologia estimării**;
   - **(b) îi dăm întâi un ARTEFACT** și arhivăm generarea, ca la celelalte;
   - **(c) amândouă** — dar atunci tabelul ține **două feluri de fapt** („ce am generat" vs „ce ți-am arătat") și trebuie **să le distingă explicit**, altfel minte despre ce conține.
- **P2** · **Ingestia Uber** — research format raport → parser → `Document` cu `platforma="Uber"` (brut/comision/tva/net/cash/banca). **NU** prin `BankTxn` (ăla e format de tranzacție bancară, ar pierde exact câmpurile care contează fiscal).
- **P3** · **Clasificatorul bancar recunoaște depunerile Uber** — azi caută literal `"bolt"` (`classify.py:157`), deci încasările Uber nu nimeresc niciun bucket de venit.
- **P4** · **Reconciliere parametrizată per platformă** — bucket venit, sursă de adevăr, regula cash, praguri.
- **P5** · **Oblio 3b + 3c** (emiterea propriu-zisă + e-Factura) — *blocat pe:* cont Oblio + serie facturare + datele I-SHTEF ca furnizor.
- **P6** · **Loturile de voce aprobate și neaplicate** + cele 3 locuri rămase cu „Contai".
- **P7** · **ALINIEREA GATING-ULUI cu scara de tiere** — azi registrul, exporturile CSV, foaia de parcurs și certificatul sunt FREE, dar registrul trebuie la PRO. **De făcut ACUM, cât nu ai useri cărora să le iei ceva.**
- **P8** · **Modulul casă de marcat + declarația F4109** (neutilizare lunară) — azi doar semnalăm „ai nevoie de AMEF", fără să acoperim obligația care urmează. **SOLO REFUZĂ explicit segmentul numerar/casă de marcat** (vezi §3.0) — deci nu e doar un gol de conformitate, e un segment liber, cu concurență zero. *Perechea lui de corectitudine e „Casă de marcat — verificarea sfatului" din blocantele FISCALE: acolo verificăm că nu mințim, aici construim ce urmează după sfat.*

- **P9** · **CICLUL DE VIAȚĂ AL CONFIRMĂRII — trei goluri legate.** Descoperite la reconul gardianului capex (PR #123). Un document extras dar neconfirmat nu e „suspendat" — **nu există deloc**, fiindcă nimic nu se scrie în DB înainte de `confirm|save` (`bot_contabil.py:2604-2614`). Asta e sigur fiscal, dar mută problema în trei locuri:
    - **VIZIBILITATE:** nu există nicăieri o listă de documente neconfirmate. După ce mesajul urcă în istoricul chat-ului, nimic nu mai amintește de el. **Userul pierde tăcut extracția și nu află niciodată.**
    - **DURABILITATE:** pending-ul trăiește în `context.user_data` (`confirmare.py:106`), dict din memoria procesului. **Niciun `PicklePersistence` configurat nicăieri** → moare la fiecare redeploy Render. Mesajul „confirmarea a expirat" descrie corect ce simte userul, dar **cauza reală e restartul, nu timpul**.
    - **FIȘIERE ORFANE:** `register_source_file` scrie și comite **înainte** de `process_entry` (`bot_contabil.py:2752` vs `:2786`), deci un abandon lasă un `SourceFile` cu baiții arhivați și niciun `Document` în spate. Cost de stocare + **întrebare de retenție**: păstrăm imagini pe care userul nu le-a confirmat niciodată.

    **DE CE ACUM:** golul **preexistă din Pas R1** și **NU e o regresie a PR #123**. Dar gardianul capex creează un motiv nou de abandon — *„nu știu ce să răspund"* — și apare exact pe **documentul cu cea mai mare valoare din sistem**, fără nicio urgență care să-l împingă pe user să răspundă. Cazul cel mai grav al unui gol vechi a devenit mult mai probabil.

    ✅ **CE E DEJA ÎN REGULĂ, de păstrat la orice reparație:** retrimiterea pozei funcționează, fiindcă dedup-ul verifică **existența unui `Document` legat de fișier, nu SHA-ul pozei** (`bot_contabil.py:2757-2784`). Un abandon nu produce `Document`, deci userul **NU** primește fals „e deja înregistrată". Fără asta, golul ar fi fost catastrofal: omul ar fi rămas convins că documentul e salvat când de fapt nu există.

    ⚠️ **NOTĂ DE COMPORTAMENT:** `_index_de_intrebat` blochează **tot lotul**, nu doar documentul mare. Trei bonuri într-o poză, unul peste prag → toate trei așteaptă răspunsul. Fail-closed consecvent, dar **de reconsiderat la reparație**.

### BLOCANTE — COMERCIAL

- **C1** · **PREȚUL FINAL pe fiecare treaptă** — azi sunt intervale. *Fără cifre nu se pot crea Products/Prices în live.*
    📌 **Ancoră verificată (aug 2026): SOLO costă 229 lei/lună la preț complet**, după emiterea codului de TVA. Susține grila din §1 (99-149 / 179-199 / 289-349) — **nu** prețuri mai mici. Liderul de bătut e la 229 cu procesare umană și cutie neagră; nu intrăm sub el din reflex.
- **C2** · **Juridic** — termeni și condiții, politică de confidențialitate, temei de prelucrare, retenție. *Stocăm CNP, CUI, venituri.*
- **C3** · **Suport** — cine răspunde, în cât timp, pe ce canal.
- **C4** · **Brand** — OSIM clasele 9/35/36/42 + domeniile coniar.ro/.com. **Înainte de orice reclamă.**

### BLOCANTE — LANSARE

- **L1** · **Călirea Stripe** — fallback pe `stripe_customer_id` când `metadata.user_id` lipsește · alerte admin pe ramurile tăcute · ordinea evenimentelor · backfill trial pentru userii existenți · șters `STRIPE_PUBLISHABLE_KEY` (declarată, nefolosită).
- **L2** · **Proba de foc în sandbox** — plată reală, userul devine PRO, adresa ajunge în DB.
- **L3** · **Test cap-coadă cu USER NOU** — de la `/start` la prima declarație și prima plată, fără ajutor din partea ta.
- **L4** · **Trecerea pe live Stripe** — cont activat · Products/Prices live · endpoint webhook nou cu secret nou · chei live · plată reală + stornare.
- **L5** · **Prezentare + marketing** — *sursa textelor e* `docs/INVENTAR-CONIAR.md` (ce face produsul azi), nu busola.

### IEFTINE ȘI ÎNAINTE DE LANSARE

> Toate patru se construiesc pe **motoare care există deja**. Niciuna nu cere partener bancar, asigurător, licență sau furnizor nou. Nu sunt blocante în sensul strict — dar raportul valoare/efort e atât de bun încât ar fi o risipă să lanseze fără ele.

- **I1** · **Audit Trail** — export cronologic cu **temeiul legal pentru fiecare clasificare**, de predat inspectorului la control. ⚠️ **Depinde de F1** (persistarea declarațiilor): fără inputurile și rezultatele salvate, exportul n-are pe ce se sprijini — ar recompune din datele de azi, nu din ce s-a depus. Materializează principiul „AI explicabil" din §3.2, care azi e doar o intenție: motorul deja *știe* de ce a dat 50% sau 0% (regim, tip deținere, categorie), doar că n-o scrie nicăieri într-o formă pe care s-o pui pe masă la ANAF. Antidotul direct la cutia neagră SOLO.
- **I2** · **Recuperarea retroactivă de deduceri la onboarding** — import extras pe 6-12 luni + categorizare retroactivă → **„îți găsim bani înapoi"**. Cel mai puternic moment de activare posibil: userul vede valoare în lei *înainte* să fi făcut vreo muncă. Conducta de import + clasificare există deja; nou e doar declanșarea pe istoric la înscriere.
- **I3** · **Detector de risc de reclasificare ca activitate dependentă** (art. 7 Cod fiscal) — scor de concentrare a venitului pe surse. **Nimeni în RO nu-l are.** Datele sunt deja în `Document.platforma`; e o interogare plus un prag, nu un motor nou.
- **I4** · **Seiful de taxe v1** — buzunar **VIRTUAL** cu sold urmărit + memento de transfer la fiecare încasare. Fără bancă, fără IBAN, fără licență. E nivelul „notificare" din §3.1 (rezervă taxe), cel ieftin — nu BaaS-ul cu IBAN virtual, care rămâne amânat.

### BLOCANT DOAR PENTRU TREAPTA MAX

- **M1** · **§1.2 depunere automată în SPV** — rațiunea de a exista a lui MAX. *Necesită înainte:* research pe împuternicirea ANAF (cum depui legal în numele altuia, la scară) + cine răspunde dacă o depunere eșuează sau întârzie.
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

> **JURNALUL NU SE REEDITEAZĂ.** Intrările consemnează ce era adevărat la momentul scrierii, inclusiv numerele de blocante de atunci. Dacă un număr s-a mutat între timp, **se lasă** — intrarea numește blocantul, deci trimiterea se rezolvă oricum. A rescrie jurnalul ca să se potrivească cu prezentul îl transformă dintr-o cronică într-o a doua copie a stării curente, adică exact ce §5 e deja.

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

- **[august 2026] BLOCANT FISCAL ÎNCHIS: TVA — declanșarea (PR #121, main `9d9257b`, 1067 verzi).** Primul blocant de corectitudine fiscală închis din §5.
  **Ce era greșit și de ce nu e o rușine:** trei suprafețe spuneau că ai „10 zile de la sfârșitul lunii" ca să te înregistrezi. **Textul era CORECT când a fost scris.** Până la 31.08.2025, art. 310 alin. (6) chiar dădea 10 zile, iar „data depășirii" era prin **ficțiune juridică** prima zi a lunii următoare — de unde „până pe 10 ale lunii următoare". **OG nr. 22/2025** (M. Of. 806 din 29.08.2025), în vigoare 01.09.2025, a rescris alineatul și **a eliminat ficțiunea**: acum termenul e *„cel târziu la data depăşirii plafonului"*, iar regimul normal se aplică *„începând cu tranzacţia care conduce la depăşirea plafonului"*. Nu există zile de grație. Legea s-a mutat sub un text corect — de aici blocantul nou 4 (auditul prozei fiscale).
  **Verificare pe sursă primară, nu pe articole de contabilitate:** forma consolidată `legislatie.just.ro` doc 312601, valabilă **08.08.2026** — art. 310 (segment de 16.043 caractere) **nu are nicio adnotare de modificare ulterioară lui 01-09-2025**. Căutare sistematică, nu impresie. Piața încă publică regula veche: monetics.ro spune „până la 10 ale lunii următoare" în 2026; contzilla.ro și regnet.ro o dau corect. Divergența nu e juridică, e de conținut nerevizuit.
  **Ce s-a construit:** sursă unică `app/domain/vat_plafon_msg.py`, cu temeiul legal scris în modul (articol + act + data verificării). **Dashboard-ul scos ca autor de text** — primea `vat.mesaj_scurt` prin payload în loc să-și compună propria frază în JS; fără asta „sursă unică" ar fi rămas o vorbă, frontend-ul era a patra versiune a adevărului. Trei stări: OK neschimbat · APROAPE (≥80%) devine mesajul important (cât a mai rămas + că depășirea te face plătitor pe loc, plus „nu trebuie să faci nimic azi") · DEPĂȘIT spune „ești deja plătitor" cu pașii concreți.
  **Gardieni verificați prin injectare deliberată** — am pus regresia în cod, am confirmat că pică, apoi am scos-o. Un gardian netestat la regresie e decor. Allowlist motivat în cod: `d700_ghid.py` (3-10 zile = durata de ridicare a certificatului) și modulul-sursă (docstring-ul explică regula veche; dacă o interzici acolo, cineva o reintroduce peste un an crezând că repară o omisiune).
  **La revizuire, două corecturi:** scos „~" de pe o cifră exactă (395.000 − 340.000 = 55.000; o aproximare pe un număr exact învață userul că cifrele noastre sunt orientative) și completat pasul 3 cu partea din lege **favorabilă** userului — art. 310 alin. (6^1) lit. b) vorbește de **DIFERENȚĂ** (colectat minus deductibil: motorină, service, comision), nu de TVA brut. Mesajul spunea doar partea care sperie.
  ⚠️ **RĂMAS NEVERIFICAT — normele metodologice (HG 1/2016, pct. 88).** N-am confirmat dacă au fost aliniate la noua procedură. **Legea bate norma**, deci mesajele noastre sunt corecte oricum. Dar dacă norma încă poartă ficțiunea „prima zi a lunii următoare", **contabilul unui șofer i-ar putea spune exact opusul a ce spunem noi** — și ar avea un text oficial în mână. **E o situație de suport, nu una de cod:** merită verificat înainte ca cineva să ne conteste, ca să știm ce răspundem.
  ⚠️ **Mină latentă lăsată deliberat:** `vat.message` (varianta lungă, cu `*bold*` de Telegram) rămâne în payload-ul API deși n-o afișează nimeni. Cine o folosește mâine în web vede asteriscuri literale. *(Scoasă în pasul următor.)*

- **[august 2026] BLOCANT FISCAL ÎNCHIS: gardian achiziție vehicul (PR #123, main `f217ca5`, 1090 verzi).** Factura de autoturism nu mai cade pe `other_expense` = `FULL`. Poarta stă în `show_confirmation` — sursă unică `app/domain/capex.py`, prag **10.000 lei ca CONSTANTĂ NUMITĂ, cu raționamentul scris lângă ea**. Orice drum spre confirmare (poză, text, PDF) trece prin ea, deci nu există cale ocolitoare.
  **DECIZIA DE DESIGN care contează: poarta NU e câmpul VIN, ci o ÎNTREBARE declanșată de sumă.** Un gardian pe VIN cade **DESCHIS** — poză proastă, vânzare privată fără factură, factură fără VIN → documentul cade înapoi pe `other_expense` = `FULL`, adică **exact gaura păzită**. (Verificat la recon: AI-ul nici nu extrage seria de șasiu azi, și nici modelul `Vehicul` n-o are — dar asta e a doua obiecție, nu prima.) **Suma e proastă la a decide CE e ceva, dar bună la a decide CÂND să întrebi:** pe sumă nu deosebești o rablă de 8.000 lei de un motor refăcut de 15.000. Decizia o ia omul, prin buton; costul maxim al unui declanșator fals e o întrebare în plus.
  **`vehicle_acquisition` are `keywords=[]` intenționat** — inaccesibilă scoring-ului semantic **prin construcție**; singurul drum spre ea e butonul. La fel, `category_override` pe `ExtractionItem` are listă albă: e câmp de buton, nu de AI.
  **Aritmetică vs. sens:** categoria e `NON_DEDUCTIBLE` fiindcă 0 chiar e răspunsul corect la întrebarea pusă de `get_effective_deductibility()` — „ce procent intră luna asta". Că mașina se deduce totuși, în ani, o poartă **categoria**, care se persistă și după care se grupează oricum. **Zero valori noi în enum.**
  **Proeminența, reparată la sursă:** achiziția nu intră niciodată în `expense_brut_by_cat`, deci iese din `expense_total_brut`, din donut și din sortare **prin CONSTRUCȚIE, nu prin scădere ulterioară**. Altfel o mașină de 48.500 lei apărea drept „cea mai mare cheltuială a lunii" — rând adevărat pe care contextul îl face să mintă. ⚠️ **`expense_total_brut` înseamnă acum „brutul lunii fără achiziții de mijloc fix"** — definiție nouă pentru orice cod viitor care o citește.
  **Ce NU intră aici:** calculul amortizării. Mesajul către user o spune explicit („cere-i cifra contabilului tău, dacă lucrezi cu unul") în loc s-o ascundă. Câmpul `serie_sasiu` rămâne pe listă ca **accelerator** care pre-completează răspunsul — nu ca poartă.
  **Descoperit la recon, consemnat separat:** „CICLUL DE VIAȚĂ AL CONFIRMĂRII" (blocantele de PRODUS) — golul preexistă din Pas R1, dar gardianul creează un motiv nou de abandon, exact pe documentul cu cea mai mare valoare din sistem.

- **[august 2026] BLOCANT FISCAL ÎNCHIS: contradicția CASS (PR #127).** **Premisa era falsă** — nu era contradicție, ci un **calificativ lipsă**. Podeaua e în **art. 174 alin. (6)**, nu în art. 170 (unde o căutam); excepțiile în **alin. (7)**: lit. a) salarii **≥ 6 SMB** · lit. b) venituri lit. c)-h) cu CASS la cel puțin 6 SMB · lit. c) **pensii, fără prag**. Ambele texte erau corecte; dashboard-ul spunea **adevărul incomplet**.
  **GĂSIT PE PARCURS:** plafonul CASS 60→72 era atribuit **Legii 141/2025** în loc de **239/2025**, în **NOUĂ locuri**. Substanța corectă, temeiul fals. (Legea 141/2025 a introdus excepția pentru pensionari, art. 174 alin. (7) lit. c — două legi confundate.)
  **Citarea legii a fost SCOASĂ din textul către user** — o citare e o **pretenție de verificare**, iar într-un tooltip n-ai unde scrie „neverificat".
  **RĂMÂNE:** re-verificarea atribuirii pe forma consolidată, când `legislatie.just.ro` revine (era căzut — ECONNREFUSED, apoi 502). Urmărită prin **marcaj greppabil în cod** (`TEMEI-NEVERIFICAT`), nu prin blocant.

- **[august 2026] BLOCANT FISCAL ÎNCHIS: semantica `is_salariat` (PR #128, 1100 verzi).** Flagul însemna *„angajat cu normă întreagă"* — **un PROXY, nu testul legal**. Art. 174 alin. (7) lit. a) cere salarii de **cel puțin 6 salarii minime pe an**; lit. c), pensiile, **n-au prag**. Part-time și angajarea la mijlocul anului bifau proxy-ul fără să atingă pragul → săreau podeaua → **SUB-declarare**.
  **RĂDĂCINA NU ERA ÎN `contributii.py`:** coloanele erau deja separate, iar OR-ul din `d212_calc.py:232` e corect odată ce intrările sunt corecte. Greșită era **ÎNTREBAREA**. Reparație de semantică — **zero schemă, zero câmp nou**.
  **SUMA PRAGULUI e afișată DERIVAT din payload** (`_cass_prag_jos_ron`, read-only, în afara allowlist-ului) — fiindcă înlocuisem un prag pe care userul îl putea evalua instant cu unul pe care nu-l poate evalua fără să știe salariul minim și să înmulțească; **cine nu poate răspunde ghicește**, iar direcția de eroare a flagului e sub-declararea.
  **ANCORELE GARDIANULUI sunt derivate din `PARAMETRI_CONTRIBUTII`, nu scrise literal** — altfel testul ar fi apărat textul învechit la o schimbare de multiplu și ar fi picat pe cine actualiza corect.

---

*Fișier viu. Actualizat la fiecare pas. Se citește PRIMUL la repornirea conversației.*
