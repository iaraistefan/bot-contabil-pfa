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
- Context istoric: REFRAME (D397 INACCESIBIL șoferului — intern ANAF; nici DAC7 nu-i accesibil PFA) → reconciliem ce controlează șoferul.
- Context (de ce contează): Ordinul ANAF 382/2025 — platformele raportează lunar fiecare cursă/km/CNP/încasare per șofer (D397, dar e al platformei, nu al șoferului) → presiune reală de conformare pe care reconcilierea o transformă în beneficiu.

### 1.6 Ingestie date platformă (REFRAME: import + AI, NU API live) ❓
- 🔴 NU există API oficial șofer nici Bolt, nici Uber (Uber "limited access" practic închis; Bolt zero; SDK-uri neoficiale = ToS violation, fragile)
- Strategie realistă (layered): D397 (1.5) + parsare extrase/CSV săptămânal + ingestie e-Factura comision + foto extras cu AI extraction (fallback universal)
- ❓ DECIZIE STEFAN: accepți "săptămânal + inteligent" în loc de "timp real"?
- **Research necesar:** cele mai bune metode de extracție AI din documente financiare

### 1.7 Plată — ✅ DECIS (Stripe+Billing) · 🔨 Felia 1 FĂCUTĂ
- 🔨 **Felia 1 FĂCUTĂ (fundația abonament).** Câmpuri User (stripe_customer_id/_subscription_id/_status/_tier, oglinda triadei Bolt) + migrarea 023 + config stripe_* (Optional) + subscription.py (tiere FREE/START/PRO/MAX din decizia #4 + is_subscribed/user_tier/has_tier_at_least). INERT prin construcție (userii existenți = NULL = FREE, zero schimbare; gating neaplicat încă). Felii rămase: 2 webhook Stripe (cere chei test), 3 Oblio factură (cere DATE CONIAR furnizor — CUI/reg.com./sediu/IBAN, LIPSESC), 4 gating features.
- ✅ **DECIS (research #7, Stripe vs Netopia).** Ales: **STRIPE + Stripe Billing** pentru lansare. CORECTURĂ MIT: Stripe e RON-nativ pt SRL RO (încasezi RON, payout RON la IBAN românesc, ZERO FX — mitul "Stripe=EUR scump" e doar pt entități US/Atlas). Comision 1.5%+1 RON +0.7% Billing. Stripe Billing = motor abonamente COMPLET (scheduler, retry, dunning, SCA/MIT, portal) → build minim. Netopia mai ieftin pe comision (1.24%+0.3 RON+TVA) DAR doar token, construiești TU tot motorul (săptămâni cod fragil) → nu merită la început. Alt local: Twispay/xMoney (motor gestionat RON-nativ, dar pivot crypto — verifică). La sume mici comisionul fix domină: Stripe+Billing ~5.5% vs Netopia ~2.7% la 30 RON. Diferență ~85 RON/lună la 100 abonați (mică), ~850 RON la 1000. PRAG MIGRARE: ~1000+ abonați. DECIZIE: Stripe+Billing lansare; reevaluezi la 1000 abonați.
- 🔗 **LEGĂTURĂ §1.7↔§1.3:** niciun procesator NU emite factura fiscală. După încasare → webhook → generezi factură (SmartBill/Oblio/FGO API) → trimiți la ANAF e-Factura. e-Factura B2C OBLIGATORIE din 1 ian 2025. Deci pipeline-ul de plată are nevoie de e-Factura ca pas următor — §1.7 și §1.3 se leagă.
- Plată taxe la ANAF (feature separat): DOAR deep-link către ghișeul.ro/SPV (NU există API terți) → calculăm suma exactă + un tap

### 1.8 Model abonament pe etape → vezi §1 (integrare tehnică: Stripe subscriptions + gating funcționalități pe tier)
- Fundația de gating (is_subscribed/user_tier/has_tier_at_least) construită în Felia 1 §1.7; aplicarea pe features = Felia 4.

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
- Ancore preț servicii umane ridesharing: PFA Ride 299 lei/lună, Stradex ~490 lei/lună. Piața plătește 300-500 lei/lună pt liniște.
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
- Foaie de parcurs auto-generată (GPS + date Bolt) pt justificare deducere 100% — dificil + ❓INCERT legal, validează cu consultant
- Arhitectură microservicii + retry asincron pt SPV (XML ANAF se schimbă des, SPV instabil)
- Optimizare fiscală predictivă ("dacă treci normă→real economisești Y"; timing înregistrare TVA; stopaj 2% Bolt cu certificat rezidență Estonia)

### 3.4 DE EVITAT (gimmick/ROI slab)
- ⛔ Mileage GPS ca feature fiscal (valoare ZERO în RO — sistem real deduce costuri reale 50/100, NU km)
- Insights demand "unde să conduci" (Gridwise-style — nu ține de contabilitate, date indisponibile Bolt API)
- Chatbot generic fără acces la datele contului (ChatGPT o face gratis)
- E-commerce/stocuri + multi-țară înainte de a domina RO

---

## §2. ÎNTREBĂRI DESCHISE & DECIZII DE BUSINESS

1. ✅ #1 REZOLVAT — traseu D→A, vezi §1.2
2. ❓ Accepți reframe date "săptămânal + AI" în loc de "timp real API"? (NB: axa bancară reconciliere §1.5 pas 2 se poate face cu PDF manual ING/Revolut — NU e blocată de agregator, vezi §1.4.)
3. ✅ #3 e-Factura build vs wrapper — REZOLVAT: WRAPPER Oblio (SDK Python, 29€/an, e-Factura inclusă). Build ANAF direct = 2-4 luni, evitat.
4. ❓ #4 Preț exact pe tiere — REZOLVAT structura (3 tiere 99-149/179-199/289-349, vezi §1); RĂMÂNE de testat A/B pragul de intrare (99 vs 129-149)
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

---

*Fișier viu. Actualizat la fiecare pas. Se citește PRIMUL la repornirea conversației.*
