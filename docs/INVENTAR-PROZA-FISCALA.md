# INVENTAR — PROZA FISCALĂ

> **HARTĂ, NU VERDICT. NICIO INTRARE NU E VERIFICATĂ CONTRA LEGII.**
>
> Documentul ăsta răspunde la o singură întrebare: **unde afirmă codul o regulă fiscală în proză, către user?** Nu spune dacă afirmația e corectă. „Temei DA" înseamnă că referința legală e scrisă lângă text în cod — nu că cineva a confirmat-o contra formei consolidate.
>
> Rezultatul PASULUI 1 din blocantul „auditul prozei fiscale" (§5, `docs/PLAN-CONIAR.md`). Motivul existenței lui: textul cu „10 zile" a fost **corect când a fost scris**; legea s-a mutat sub el la 01.09.2025 (OG 22/2025) și nimeni n-a observat un an. Nu a fost neglijență — a fost o clasă de eșec pe care n-o supraveghea nimeni.

**Convenție de numărare:**
- **DA** — referință legală (articol și/sau act) scrisă adiacent în cod
- **parțial** — numește un articol sau o convenție, dar fără actul modificator sau data verificării
- **NU** — nicio referință

**Severitate dacă afirmația e greșită:**
- **MARE** — ratează o depunere, plătește greșit, ia amendă
- **MEDIE** — ia o decizie proastă
- **MICĂ** — se încurcă, dar nu pierde bani

*Inventariat: august 2026. Liniile se referă la `main` la data inventarierii.*

---

## A. Ghidul declarațiilor — `app/domain/fiscal_calendar.py`, `DEFINITII_OBLIGATII`

### D100 poz. 634
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 1 | `:197,219-222` | Lunar, până pe 25 a lunii următoare | NU | **MARE** |
| 2 | `:188-193,229-238` | Cote nerezident: Bolt 2%/16% (Convenția RO-EE art.12), Uber 0%/16% (art.7) | parțial | **MARE** |
| 3 | `:205` | Formula: cotă × bază factură fără TVA | NU | **MARE** |
| 4 | `:200-202,215-218` | Doar lunile cu factură de comision primită | NU | **MARE** |
| 5 | `:206-209` | Majorări 0,02%/zi + penalități | NU | MEDIE |
| 6 | `:223-228` | Se depune pe CUI-ul PFA, NU pe codul special TVA | NU | **MARE** |
| 7 | `:229-238` | Obligația de reținere cade pe plătitorul român, nu pe platformă | parțial | **MARE** |

### D207
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 8 | `:255-256,280-283` | Anual, 28 februarie, pentru anul precedent | NU | **MARE** |
| 9 | `:259-263,276-279` | Se declară și veniturile SCUTITE (Uber 0%), nu doar impozitul | NU | **MARE** |
| 10 | `:266-270` | Amendă „de regulă 500–1.000 lei" | NU | MEDIE |
| 11 | `:253,284-288` | Fără plată, pur informativă | NU | MICĂ |

### D301
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 12 | `:310,332-334` | Lunar, până pe 25 a lunii următoare | NU | **MARE** |
| 13 | `:306,318,335-338` | 21% × baza facturii fără TVA | NU | **MARE** |
| 14 | `:311-314,328-331` | Se aplică neplătitorului cu cod special (D700) | NU | **MARE** |
| 15 | `:319-321` | Amendă 1.000–5.000 RON + majorări 0,02%/zi | NU | MEDIE |
| 16 | `:339-345` | La taxare inversă neplătitorul nu deduce integral → rămâne de plată | NU | MEDIE |

### D390
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 17 | `:359-360,384-387` | Lunar, până pe 25, împreună cu D301 | NU | **MARE** |
| 18 | `:361-366,380-383` | Se aplică celor 4 categorii listate (plătitori și neplătitori cu cod) | NU | **MARE** |
| 19 | `:371-375` | Amendă „de regulă 1.000–5.000 lei" | NU | MEDIE |
| 20 | `:388-391` | Operațiune tip „S" (servicii), cu codul TVA al platformei și valoarea netă | NU | MEDIE |

### D300
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 21 | `:428` | Lunar sau trimestrial după cifra de afaceri, până pe 25 | NU | **MARE** |
| 22 | `:424-427` | Doar plătitorii de TVA; PFA neplătitor are D301 | NU | MEDIE |
| 23 | `:430-432` | D300 ÎNLOCUIEȘTE D301 la trecerea pe plătitor | NU | **MARE** |
| 24 | `:417-419` | Amendă + majorări 0,02%/zi | NU | MEDIE |

### D212
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 25 | `:449-450,472-475` | Anual, până pe 25 mai, pentru anul încheiat | NU | **MARE** |
| 26 | `:454-457,480-486` | Bonificație 3% DOAR pe impozit, condiționată de plata INTEGRALĂ până pe 15 aprilie | NU | **MARE** |
| 27 | `:444-445,458,464-467` | Impozit 10%, CAS 25%, CASS 10% | NU | **MARE** |
| 28 | `:468-471,480-486` | CAS doar peste 12 salarii minime; CASS cu plafon propriu | NU | **MARE** |
| 29 | `:445,476-479` | Plata în contul unic 5504 pe CNP, nu pe CUI | NU | **MARE** |
| 30 | `:460-463` | Majorări 0,02%/zi + pierderea bonificației | NU | MEDIE |

### D101
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 31 | `:496-497,513` | Trimestrial (25 după trimestru) + anuală pe 25 martie | NU | MEDIE |
| 32 | `:505,509,514` | 16% pe profitul fiscal | NU | MEDIE |
| 33 | `:510-512` | Doar SRL Normal; PFA are D212 | NU | MICĂ |

### D700
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 34 | `:528-531,551` | O singură dată, înainte de prima factură intracomunitară | NU | **MARE** |
| 35 | `:543-546` | Cod special de TVA conform art. 317 | DA | **MARE** |
| 36 | `:539-542,553-558` | Fără D700 nu poți depune legal D301/D390 | NU | **MARE** |
| 37 | `:547-550` | Se aplică neplătitorului, înainte de prima factură UE | NU | **MARE** |

## B. Ghidul D700 — `app/integrations/anaf/d700_ghid.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 38 | `:35,46-47` | Formular 700, Subsecțiunea B.VI, pct. 1.23.1, bifa 3 (art. 317 alin. (1) lit. c) | DA | **MARE** |
| 39 | `:37-40` | Nu există prag; cei 10.000 € sunt doar pentru BUNURI, nu pentru servicii | NU | **MARE** |
| 40 | `:43-44` | Cere semnătură electronică calificată + înrolare SPV pe CUI-ul PFA | NU | MEDIE |
| 41 | `:51-52` | Certificatul se ridică de la sediul ANAF în 3-10 zile | NU | MICĂ |
| 42 | `:56-57` | Termen: înainte de prima cursă/comision | NU | **MARE** |

> **#41** e pe allowlist-ul gardianului „10 zile" — vezi §4, august 2026: acolo „3-10 zile" e durata de ridicare a certificatului, nu termenul de înregistrare TVA.

## C. Plafonul TVA — `app/domain/vat_plafon_msg.py` · **MODELUL DE URMAT**
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 43 | `:18-35` | Art. 310 alin. (6) după OG 22/2025 (M. Of. 806/29.08.2025): termenul e chiar ziua depășirii, fără zile de grație | **DA, cu data verificării** | **MARE** |
| 44 | `:37-48` | Art. 316 alin. (1^1) lit. b): înregistrarea e valabilă de la data depășirii | DA | **MARE** |
| 45 | `:91-108` | Texte user: „ești deja plătitor din tranzacția care a depășit" | DA | **MARE** |

## D. Profil fiscal — `app/domain/fiscal_profile.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 46 | `:49-51` | Plafon TVA 395.000 lei (OG 22/2025, în vigoare 01.09.2025) | DA | **MARE** |
| 47 | `:53` | Plafon TVA e-commerce intracomunitar (EUR) | NU | MEDIE |
| 48 | `:116-122` | Bolt: 2% cu certificat / 16% fără (art. 224 CF); NU există 0% | DA | **MARE** |
| 49 | `:123-126` | Uber: art. 7 „profituri", 0% cu certificat / 16% fără | parțial | **MARE** |

## E. Contribuții — `app/domain/contributii.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 50 | `:32,62-65` | Plafon CASS urcă 60→72 SMB doar pentru veniturile din 2026 (Legea 141/2025) | DA | **MARE** |
| 51 | `:47` | Salariu minim 4.050 lei (HG 1506/2024) | DA | **MARE** |
| 52 | `:50,59-61` | Praguri CAS 12 și 24 SMB; podea CASS 6 SMB | NU | **MARE** |
| 53 | `:29-31,213-215` | Sub 6 SMB cu altă asigurare → 10% pe venitul real, fără urcare la podea | NU *(marcat în cod ca surse secundare)* | **MARE** |

> **#53** e jumătatea unei contradicții active — vezi #75 și Observația 3.

## F. Norma de venit — `app/domain/norma_venit.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 54 | `:6,13-14,123` | CAEN 4933 eligibil normă doar din 2026 (OMF 1960/2025, Art. III) | DA | **MARE** |
| 55 | `:33,41,188-191` | Plafon 126.038 lei (25.000 € × 5,0415), art. 69 CF; peste el, real obligatoriu din anul următor | DA | **MARE** |
| 56 | `:59-61` + nomenclator | Norme pe județ × tip localitate, Decizii AJFP 2026 | DA (per valoare) | **MARE** |

## G. Reguli de bază — `app/domain/tax_rules.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 57 | `:11-12,25-26,31-32` | TVA 21% din 01.08.2025, 19% până la 31.07.2025 | parțial *(„OUG aplicabilă", fără număr)* | **MARE** |
| 58 | `:13-14` | Taxare inversă pe servicii intracomunitare, art. 307 alin. 2 CF | DA | **MARE** |
| 59 | `:15-16` | Auto mixt 50% (art. 25 alin. 3 lit. l CF); exclusiv + dovadă → 100% | DA | **MARE** |
| 60 | `:17,29` | Impozit nerezidenți 2% (convenția RO-Estonia) | parțial | **MARE** |

## H. Casa de marcat — `app/domain/casa_marcat.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 61 | `:4-7,74-78` | AMEF obligatorie la încasare directă cash/POS propriu (OUG 28/1999 republicată; OUG 49/2019 art. 21 sancțiuni) | DA | **MARE** |
| 62 | `:6-7,69-73` | Plățile prin aplicație NU declanșează AMEF | NU | **MARE** |
| 63 | `:10-11,79-84` | Bolt permite dezactivarea cash; Uber permite mereu cash | NU *(fapt comercial)* | MEDIE |
| 64 | `:16-17` | Disclaimer „orientativ, de verificat cu contabil/ANAF" | NU | MICĂ *(atenuant)* |

## I. Certificat de rezidență — `app/services/certificat.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 65 | `:7,51-56` | Cu certificat 2% la D100, fără 16%; Convenția RO-EE Art. 12 | parțial | **MARE** |
| 66 | `:61` | Trebuie certificatul valabil pentru anul depunerii | NU | **MARE** |
| 67 | `:68-88` | Reminder anual de reînnoire (2%) / optimizare (16%→2%) | NU | MEDIE |

## J. Onboarding — `app/services/onboarding.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 68 | `:58-69,496-533` | Cote nerezident per platformă, cu articolele convențiilor | parțial | **MARE** |
| 69 | `:123` | CAEN alternativ eligibil normă 2026 (OMF 1960/2025) | DA | MEDIE |
| 70 | `:1132` | Cod special de TVA art. 317 | DA | MEDIE |
| 71 | `:186-190` | Regimuri TVA: neplătitor / plătitor 21% | NU | MEDIE |

## K. Dashboard web — `app/http/templates/dashboard.html`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 72 | `:735` | Combustibil 50%/100% pe regim; ANAF cere dovada, foaia de parcurs | NU | **MARE** |
| 73 | `:765` | TVA 21% pe comisionul Bolt prin D301 + VIES prin D390, lunar până pe 25 | NU | **MARE** |
| 74 | `:1310` | Impozit 10% pe ce rămâne după CAS și CASS (art. 68 Cod fiscal) | DA | **MARE** |
| 75 | `:1312` | CASS: sub 6 SMB pe baza minimă · 6-72 pe real · peste 72 plafonat (Legea 141/2025) | DA | **MARE** |
| 76 | `:1330` | CAS devine obligatoriu doar peste 12 salarii minime | NU | **MARE** |
| 77 | `:1373` | Norma indisponibilă la ridesharing până în 2026 | NU | MEDIE |
| 78 | `:1375` | Plafon normă 126.038 lei (2026); trecerea se face de anul viitor | NU | **MARE** |
| 79 | `:1377` | Revenirea la normă abia după minimum 2 ani fiscali pe real | NU | **MARE** |
| 80 | `:1379` | Decizia de regim se ia prin D212 (termen 25 mai), valabilă de anul viitor | NU | **MARE** |
| 81 | `:884-886,905-911` | Cod special art. 317; Bolt art. 12 / Uber art. 7 | DA | MEDIE |
| 82 | `:1556` | Pragurile vin din salariul minim + plafonul TVA legal (OG 22/2025) | DA | MEDIE |

> **#75** e cealaltă jumătate a contradicției — vezi #53 și Observația 3.

## L. Gardianul de conformitate — `app/domain/compliance_guardian.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 83 | `:412-426` | Majorări de întârziere 0,02%/zi „conform Cod Fiscal" | parțial *(fără articol)* | MEDIE |

## M. Deductibilitate — `app/activities/ridesharing.py`
| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 84 | `:12-15` | Docstring: toate cheltuielile auto limitate la 50% pe autoturism mixt, art. 25 alin. (3) lit. l) | DA | **MARE** |
| 85 | `:72-79, 120-128, 169-176, 188-195` | Note user: 50%/100% pe regim; comodat → asigurarea nedeductibilă | parțial | **MARE** |
| 86 | `:264-276` | „Nu se scade în luna cumpărării, se amortizează an de an" *(PR #123)* | NU | MEDIE |

## N. Botul — `bot_contabil.py`

> În rădăcină, nu în `app/` — dar **vorbește direct cu userul**, deci excluderea pe criteriu de director ar fi fost arbitrară. Proza fiscală de aici e subțire fiindcă majoritatea e surfațată din sursele de mai sus (rezultatul muncii de „sursă unică"); ce urmează e ce afirmă botul **pe cont propriu**.

| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 87 | `:473-497` | Mesaj de confirmare: procentul deductibil, pe categorie și regim | NU | MEDIE |
| 88 | `:454-471` | Achiziție: „n-o pun la cheltuielile lunii; se amortizează an de an" *(PR #123)* | NU | MEDIE |
| 89 | `:1537` | „Din care deductibil: X RON" — afirmă implicit că restul nu se deduce | NU | MEDIE |
| 90 | `:1756` | „D100: X lei (impozit nerezident, {procente})" — cota afișată userului | NU | **MARE** |
| 91 | `:1889` | „Folosește deocamdată ghidul de completare (sigur)" — afirmație despre siguranța depunerii | NU | MICĂ |
| 92 | `:2804` | „Comisioane bancare — deductibile" | NU | MEDIE |
| 93 | `:3062,3151,3253` | Cod special TVA art. 317 | DA | MEDIE |
| 94 | `:711` | Help foaie de parcurs (ce comenzi există) | NU | MICĂ |

## O. Combustibil — `app/services/combustibil.py`

> ⚠️ **Ratat în prima trecere a inventarului.** E în `app/`, ar fi trebuit să apară de la început. Adăugat la trecerea pentru `bot_contabil.py`.

| # | Locație | Afirmația | Temei | Sev. |
|---|---|---|---|---|
| 95 | `:8-11,21-22,192-194` | Consum normat = km business × normă / 100; verdictul se dă pe LITRI, nu pe lei; NU determină deductibilitatea | NU | MEDIE |
| 96 | `:277,295-296` | „Ai depășit consumul normat" — afirmă un plafon de plauzibilitate | NU | MEDIE |

---

# TOTALURI

**96 de afirmații fiscale în proză**, în 15 fișiere.

| Temei legal adiacent | Număr | Procent |
|---|---|---|
| **DA** — articol și/sau act scris lângă | **23** | 24% |
| **Parțial** — numește un articol/convenție, fără actul modificator sau data | **9** | 9% |
| **NU** — nicio referință | **64** | 67% |

**Doar UNA singură** (#43, plafonul TVA) poartă forma completă pe care o cere blocantul: **articol + act modificator + data verificării pe forma consolidată**. Restul celor 22 „DA" au articolul, dar nu și dovada că cineva le-a verificat contra legii la zi.

| Severitate | Număr |
|---|---|
| **MARE** — ratează o depunere, plătește greșit, ia amendă | **58** |
| **MEDIE** — ia o decizie proastă | **31** |
| **MICĂ** — se încurcă, dar nu pierde bani | **7** |

---

# TREI OBSERVAȚII PENTRU ORDINEA DE ATAC

## 1. Concentrarea

**37 din 96 stau într-un singur fișier** — `fiscal_calendar.py`. E și cel mai expus: **34 din cele 37 n-au niciun temei**. Conținutul e partajat între bot și dashboard (`/api/v1/ghid`), deci o eroare acolo apare pe două suprafețe simultan, iar testele îl blochează pe fraze (`test_ghid_obligatii_continut.py`) — ceea ce înseamnă că o corectură cere și actualizarea testului, nu doar a textului.

## 2. Termenele sunt clasa cea mai goală

Fiecare dintre cele 8 declarații își afirmă termenul — **#1, 8, 12, 17, 21, 25, 31, 34** — și **niciunul n-are temei**. E exact clasa în care a căzut „10 zile": o dată la care legea se poate muta fără ca nimic din cod să semnaleze. Toate opt sunt în același fișier, deci se verifică într-o singură trecere.

## 3. O contradicție internă, de verificat ca una singură

**#53** (`contributii.py:29-31,213-215`) spune că cine e sub 6 SMB dar are altă asigurare plătește **10% pe venitul net real, fără urcare la podea**.

**#75** (`dashboard.html:1312`) îi spune userului că **sub 6 salarii minime CASS se calculează pe baza minimă de 6 salarii**.

Cele două descriu **rezultate diferite pentru același om**, iar al doilea e cel pe care userul îl citește efectiv. Nu le-am verificat contra legii — dar nu pot fi ambele adevărate, deci **una e greșită acum**. Nu e o sarcină de audit, e un bug activ; și nu se verifică separat, fiindcă răspunsul corect le rezolvă pe amândouă.

---

*Fișier generat la PASUL 1 al auditului prozei fiscale. Se actualizează când se închid intrări sau când apare proză nouă.*
