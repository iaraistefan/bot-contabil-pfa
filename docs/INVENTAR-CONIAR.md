# INVENTAR CONIAR — ce face produsul AZI

> **Fișierul ăsta spune CE FACE Coniar azi. `PLAN-CONIAR.md` spune CE AM DECIS. Sunt întrebări diferite — nu le amesteca.**

Citit din COD (comenzi, butoane, rute, joburi), nu din busolă. Limbajul e al șoferului, nu al dezvoltatorului: dacă o funcție nu se poate explica într-o propoziție pe care un PFA o înțelege, probabil n-ar trebui să existe.

**Gating** (harta din `app/services/gating.py`): **FREE** = liber pentru toți · **START** / **PRO** = cere planul respectiv. În primele 30 de zile de la înscriere, orice user nou are PRO complet (reverse trial, fără card).

---

## Intrare & profil

| Ce face | Unde | Plan |
|---|---|---|
| Te înscrie și te configurează pas cu pas — CUI-ul îl ia singur de la ANAF | `/start` → wizard în Dashboard | FREE |
| Aceeași configurare, dar prin chat, dacă nu-ți merge butonul | `/setup_text` | FREE |
| Îți arată ce știe despre tine: firmă, CUI, regim fiscal, activitate | `/profil` · „⚙️ Setări" | FREE |
| Îți șterge configurarea și o iei de la capăt | `/reset_profil` | FREE |
| Îți completează codul special de TVA și CNP-ul, cerute de declarații | `/coduri_fiscale` · `/cod_tva` · `/cnp` | FREE |
| Îți ține mașinile și regimul lor: mixt, exclusiv sau comodat | „⚙️ Setări" → Vehicule | FREE |
| Îți spune dacă ai nevoie de casă de marcat | onboarding + Dashboard | FREE |
| Îți șterge tot contul, dacă vrei să pleci | `/delete` | FREE |

## Venituri

| Ce face | Unde | Plan |
|---|---|---|
| Îți aduce singur cursele din contul tău Bolt, în fiecare noapte | `/bolt_conectare` + sync automat | **START** |
| Îți citește încasările dintr-un extras PDF de la bancă (BT) | trimiți PDF-ul în bot | FREE |
| Îți arată cât ai încasat, pe lună și pe an | „📊 Raport" · Dashboard | FREE |
| Îți desparte veniturile pe platformă: Bolt, Uber, altele | Dashboard → Venituri | FREE |
| Îți arată dacă luna asta e mai bună sau mai slabă decât cea trecută | Dashboard (badge-uri ▲▼) | FREE |

## Cheltuieli

| Ce face | Unde | Plan |
|---|---|---|
| Îți înregistrează un bon dintr-o poză | trimiți poza în bot | FREE |
| Îți înregistrează o cheltuială scrisă în cuvinte („motorină 200 lei") | scrii în bot | FREE |
| Îți recunoaște singur categoria și cât e deductibil: 50%, 100% sau 0% | automat, la înregistrare | FREE |
| Îți propune cheltuielile găsite în extrasul bancar, să le confirmi | PDF extras → butoane | FREE |
| Îți arată pe ce s-au dus banii, pe categorii | `/cheltuieli` · „💸 Cheltuieli" | FREE |
| Îți ține foaia de parcurs (ture, km, litri) ca dovadă la control | „🛣️ Foaie parcurs" · `/sterge_tura` | FREE |

## Reconciliere — arma secretă

| Ce face | Unde | Plan |
|---|---|---|
| Îți spune dacă ce ai declarat se potrivește cu ce arată Bolt | automat, în rapoarte | teaser la FREE |
| Îți spune dacă banii intrați în cont se potrivesc cu ce ai încasat de la Bolt | automat, cumulativ pe an | teaser la FREE |
| Îți spune ce luni cu Bolt n-au fost sincronizate | automat | teaser la FREE |
| **Îți arată exact ce nu se potrivește și cum se rezolvă** | detaliile complete | **PRO** |

**Teaser** înseamnă: pe FREE afli *că* există o nepotrivire și *cât* de mare e — dar nu afli cauza și nici cum se rezolvă. Verdictul liniștitor („totul se potrivește") îl primesc toți.

## Documente & exporturi

| Ce face | Unde | Plan |
|---|---|---|
| Îți ține toate bonurile și documentele, cu poza originală | Dashboard → Documente | FREE |
| Îți dă Registrul de încasări și plăți pe un an, în Excel | „📂 Registru" | FREE |
| Îți dă tranzacțiile lunii în CSV | Dashboard → Export | FREE |
| Îți dă sumarul lunii în CSV | Dashboard → Export | FREE |
| Îți dă foaia de parcurs în Excel | „🛣️ Foaie parcurs" → Export | FREE |
| Îți dă certificatul de rezidență pentru Bolt, plus ghidul de obținere | `/certificat` | FREE |

## Declarații & termene

| Ce face | Unde | Plan |
|---|---|---|
| Îți explică fiecare declarație: ce e, cui se aplică, când, cum, de ce ție | `/ghid` · „📖 Ghid" · Dashboard | FREE |
| Îți arată ce ai de depus și până când, cu sumele | „📋 Calendar Fiscal" · Dashboard | FREE |
| Te anunță din timp când se apropie un termen | automat, zilnic | FREE |
| Îți calculează Declarația Unică: impozit, CAS și CASS pe venitul tău real | `/declaratie_unica` · „🧮 Declarația Unică" | **START** |
| Îți compară normă de venit vs. sistem real și îți spune ce te avantajează | Dashboard → Simulator | FREE |
| **Îți pregătește D301 / D390 / D100 / D207, gata de urcat în SPV** | butoane în bot · Dashboard | **PRO** |
| Îți spune cât să pui deoparte pentru taxe și cum se plătesc | `/plata_fiscala` · „💳 Plată Fiscală" | FREE |
| Îți marchează taxele plătite, găsite singur în extras | PDF extras → butoane | FREE |

## Abonament

| Ce face | Unde | Plan |
|---|---|---|
| Îți dă 30 de zile PRO complet la înscriere, fără card | automat, la finalul configurării | — |
| Te duce la plată când vrei un plan | „💳 Activează PRO" din mesajul de blocare | — |
| Îți activează abonamentul singur după plată | automat | — |

## Altele — fac singure, fără să ceri

| Ce face | Când |
|---|---|
| Îți trimite un rezumat al săptămânii | luni dimineața |
| Îți trimite sumarul lunii încheiate | pe 2 ale lunii |
| Verifică dacă ai termene aproape | pe 20 ale lunii |
| Trece prin situația ta fiscală | pe 1 ale lunii |
| Îți amintește să-ți reînnoiești certificatul de rezidență | pe 10 ianuarie |

Plus: `/ajutor`, `/status`, `/cont` pentru ajutor și verificare. `/anafdebug` și `/sumar_test` sunt doar pentru owner.

---

# Construit, dar absent din busolă

Opt funcții există în cod și n-au corespondent în `PLAN-CONIAR.md`. Cine citește azi busola ca să afle ce există **subestimează produsul** — inclusiv o funcție obligatorie legal.

1. **Registrul de încasări și plăți** — zero mențiuni în busolă. Document contabil obligatoriu pentru PFA, exportabil în Excel, cu buton propriu în meniul botului.
2. **Exporturile CSV** (tranzacții, sumar lunar) — cuvântul „export" nu apare deloc în busolă.
3. **Simulatorul normă vs. sistem real** — cuvântul „simulare" nu apare deloc. E un diferențiator real („află ce regim te avantajează"), complet invizibil în plan.
4. **Sumarele automate** (săptămânal, lunar) — cuvântul „sumar" nu apare deloc. Patru din cele șapte sarcini programate n-au corespondent în busolă.
5. **Foaia de parcurs manuală** — busola o pomenea o singură dată, în §3.3 „Idei avansate", ca versiunea *auto-generată din GPS*, marcată „dificil, incert legal". Versiunea manuală, construită și livrată, lipsea. **Corectat** — vezi §3.3 în busolă.
6. **Managementul vehiculelor și regimul de utilizare** (mixt / exclusiv / comodat) — inexistent ca funcție în busolă, deși determină deductibilitatea auto.
7. **Plata fiscală** (`/plata_fiscala`, rezerva de taxe) — zero mențiuni; busola pomenește doar deep-link-ul spre SPV, ca idee viitoare.
8. **Ecranul de cheltuieli pe categorii** și **defalcarea venitului pe platformă** — livrate, neconsemnate.

**Ce apare corect în busolă:** reconcilierea, calendarul fiscal și alertele, ghidul de obligații, certificatul de rezidență, onboarding-ul, Declarația Unică, D207, integrarea Bolt, abonamentul Stripe.

**Tiparul:** busola acoperă bine *deciziile mari și feliile fiscale*, dar ratează aproape tot ce a intrat prin capitolele de interfață, exporturi și automatizări. De aceea există fișierul ăsta — nu ca să înlocuiască busola, ci ca să răspundă la cealaltă întrebare.
