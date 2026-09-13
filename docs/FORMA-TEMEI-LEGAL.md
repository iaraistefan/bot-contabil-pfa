# Forma canonică a unui temei legal

> **Ce e documentul ăsta:** definiția UNICĂ a felului în care se scrie un temei legal
> lângă o afirmație fiscală din cod. Primul pas al blocantului **F2** din
> `docs/PLAN-CONIAR.md` §5.
>
> **Ce NU e:** un gardian. Forma se definește și se demonstrează aici; impunerea
> automată vine într-un pas separat, **după** ce forma s-a dovedit stabilă pe mai
> multe exemple reale. A impune o formă care nu există complet nicăieri ar însemna
> să inventăm o disciplină, nu să o codificăm.

## De ce există

Textul cu „10 zile" a fost **corect când a fost scris**. Legea s-a mutat sub el la
01.09.2025 (OG 22/2025) și nimeni n-a observat un an. Nu a fost neglijență — a fost o
clasă de eșec pe care n-o supraveghea nimeni: o afirmație fiscală fără temei nu se
poate re-verifica, fiindcă nu știi ce anume ai verificat, unde, și când.

Inventarul (`docs/INVENTAR-PROZA-FISCALA.md`) a găsit **96 de afirmații fiscale în
proză**, din care **64 fără niciun temei**. Dintre cele cu temei, niciuna nu era
completă în același fel ca alta.

---

## Cele cinci elemente

Un temei complet are **cinci** elemente. Ordinea de mai jos e și ordinea în care se
scriu, fiindcă merge de la „ce spune legea" spre „cât de sigur sunt eu".

### 1. Articol + alineat (+ literă)

Adresa exactă în act. `art. 317 alin. (1) lit. c)`, nu `art. 317`. Un articol întreg
poate spune mai multe lucruri, iar afirmația noastră se sprijină pe unul singur.

### 2. Citat LITERAL din lege

Cuvintele legii, între ghilimele, nu parafraza noastră. E singurul element care permite
cuiva să verifice dacă am înțeles corect, fără să deschidă actul.

Parafraza e locul unde intră eroarea tăcută: „până pe 28 februarie" era o parafrază
onestă a lui „până în ultima zi a lunii februarie", și era falsă o dată la patru ani.

#### De ce ăsta e elementul cel mai valoros din cele cinci

Pentru că e **singurul care se poate verifica fără să ai încredere în noi.**

Celelalte patru sunt referințe: trimit în altă parte și cer ca trimiterea să fie
corectă. Iar o trimitere poate fi **corectă într-un loc și falsă în altul, cu același
număr de act**. Nu e o ipoteză — s-a întâmplat cu același act, în același proiect:

- **Legea 141/2025** e actul **CORECT** pentru cota TVA de 21% (`app/ai/prompts.py`,
  unde scria greșit „OUG 115/2023");
- **Legea 141/2025** era actul **GREȘIT** pentru plafonul CASS, unde corect era
  239/2025 (PR #127).

Același număr, două afirmații, un adevăr și o minciună. Nimic din forma temeiului nu
distinge cele două cazuri — ambele arată la fel de complete. Dar dacă lângă fiecare
stă **citatul literal**, neconcordanța devine vizibilă la citire: textul citat ori
vorbește despre ce spunem noi, ori nu.

**Asta e regula care supraviețuiește când restul formei se erodează.** Dacă vreodată
se scurtează forma — și formele se scurtează —, pct. 2 e ultimul care se taie.

### 3. Actul modificator + Monitorul Oficial + data intrării în vigoare

**Sau** una din celelalte două stări. Sunt **trei** stări posibile, și diferența dintre
ele contează:

| stare | ce înseamnă | cum se scrie |
|---|---|---|
| **modificat** | știm ce act a schimbat textul | `modificat prin [act] (MO nnn/dd.mm.yyyy), în vigoare [dd.mm.yyyy]` |
| **nemodificat** | am verificat ȘI n-are modificări | `nemodificat de la publicare ([actul original], MO nnn/dd.mm.yyyy)` |
| **NEGĂSIT** | am căutat și **nu am putut confirma** | `act modificator: NEGĂSIT (căutat [dd.mm.yyyy] pe [surse])` |

⚠️ **`NEGĂSIT` e o stare DE DREPT, nu o excepție tolerată.** Nu e un temei incomplet
pe care-l îngăduim până se face treaba — e răspunsul **corect** la o întrebare la care
n-avem răspuns, și se scrie cu aceeași demnitate ca celelalte două.

Motivul: **absența informației nu e dovada absenței modificării.** „Nemodificat de la
publicare" e o afirmație despre lege, la fel de tare ca „modificat prin X", și cere
aceeași dovadă. A scrie „nemodificat" fiindcă n-ai găsit istoricul e exact felul de
afirmație plauzibilă care trece de orice gardian de formă și e falsă.

Un „negăsit" e util: spune următorului om unde s-a oprit căutarea, ca s-o reia de
acolo. Un act plauzibil pus lângă o afirmație fiscală nu e util — e o minciună cu
aspect de muncă făcută. De aceea `NEGĂSIT` se scrie cu **ce s-a încercat și când**:
fără asta, e indistinct de „n-am căutat".

### 4. Forma consolidată + data ei

Ce **text** am citit. O formă consolidată e o fotografie a legii la o dată anume:
`forma consolidată legislatie.just.ro valabilă la 08.08.2026`.

### 5. Data verificării NOASTRE (+ sursa, dacă diferă)

Când **noi** ne-am uitat și am confirmat: `verificat 13.09.2026`. Dacă verificarea s-a
făcut pe altă sursă decât forma consolidată de la pct. 4, se scrie:
`verificat 13.09.2026 pe noulcodfiscal.ro`.

### De ce 4 și 5 sunt lucruri DIFERITE

Pentru că răspund la întrebări diferite, iar confundarea lor e chiar gaura pe care o
închidem:

- **Forma consolidată** spune **CE TEXT am citit**. E o proprietate a documentului.
- **Data verificării** spune **CÂND am confirmat că ăla e cel mai nou text**. E o
  proprietate a acțiunii noastre.

O formă consolidată din 08.08.2026 citită astăzi și una citită peste doi ani sunt
**același text**, dar **nu aceeași încredere**. În al doilea caz, legea a avut doi ani
să se miște, iar noi n-am privit.

**Prospețimea se măsoară pe A DOUA.** Un temei cu forma consolidată 08.08.2026 și
verificarea 08.08.2026 e proaspăt; același temei, cu aceeași formă consolidată, dar
neverificat de doi ani, e vechi — deși textul citat n-a fost atins. Când se va construi
gardianul, el va citi data de la pct. 5, nu pe cea de la pct. 4.

---

## Ce garantează forma, și ce NU

Forma asta garantează **completitudine** și **prospețime**. Nu garantează
**corectitudine**, și e important să nu pretindem altceva.

Un temei poate avea toate cele cinci elemente și poate fi **atribuit greșit**. S-a și
întâmplat: la închiderea contradicției CASS (PR #127), plafonul era atribuit **legii
greșite** (141/2025 în loc de 239/2025), avea o referință scrisă lângă el, arăta a
temei, și era numărat „DA" în inventar. Un gardian de formă ar fi zis ✅.

A doua oară, în sesiunea care a produs documentul ăsta: `app/ai/prompts.py` atribuia
cota TVA de 21% lui **OUG 115/2023**. Cifra era corectă, actul era greșit — 21% vine
din **Legea 141/2025**. Aceeași clasă, a doua oară, într-un fișier pe care inventarul
nici nu-l privea.

**Concluzia:** forma canonică e un gardian de completitudine. Numai citirea legii
prinde atribuirea greșită. De asta pct. 2 (citatul literal) e elementul cel mai
valoros din cele cinci — e singurul care face vizibilă o neconcordanță între ce spune
actul și ce spunem noi.

---

## Unde se scrie

**O SINGURĂ DATĂ, la sursa afirmației** — nu copiat în fiecare loc care o consumă.
Trei copii ale unei date de verificare se desincronizează; e tiparul din §ONRC al
busolei. Locurile care consumă afirmația trimit la sursă (`vezi §D700`), nu o repetă.

Excepție: când afirmația e **livrată userului**, temeiul scurt poate apărea și în
textul livrat (ca la `D700.cand`), dar forma completă rămâne la sursă.

## Exemple canonice în cod

Cele trei aduse la forma asta, ca demonstrație:

| afirmație | unde | stare pct. 3 |
|---|---|---|
| D700 — declanșatorul e primirea serviciului | `fiscal_calendar.py`, §D700 | **NEGĂSIT** |
| D101 — termenul anual bifurcat pe ani | `fiscal_calendar.py`, §D101 | modificat (OUG 8/2026) |
| D207 — termenul e ultima zi a lunii februarie | `fiscal_calendar.py`, §D207 | modificat (Legea 296/2020) |

Modelul istoric, care a inspirat forma: `app/domain/vat_plafon_msg.py` (plafonul TVA).

---

## Ce urmează: subsetul mașină-citibil, și cine câștigă

**Documentul ăsta e locul potrivit ACUM**, fiindcă forma e încă **proză și judecată**:
ce înseamnă un citat literal, când ai voie să scrii „nemodificat", de ce data
verificării bate data consolidării. Nimic din astea nu e un tipar.

Dar gardianul din **F2** nu poate citi proză. Va avea nevoie de un **subset
mașină-citibil**:

- numele celor cinci elemente, ca etichete stabile;
- tiparul unei date (`dd.mm.yyyy`);
- tiparul unui Monitor Oficial (`MO nnn/dd.mm.yyyy`);
- tiparul unei adrese în act (`art. N alin. (M) lit. x)`);
- cele trei stări ale pct. 3, ca valori fixe — inclusiv șirul `NEGĂSIT`;
- vechimea maximă acceptată pentru data de la pct. 5.

⚠️ **CÂND SE ÎNTÂMPLĂ ASTA, SUBSETUL SE MUTĂ ÎNTR-UN MODUL** (`app/domain/` sau lângă
gardian), iar **documentul de față trimite la el**. Nu invers, și nu în paralel.

**CINE CÂȘTIGĂ:** pentru partea mașină-citibilă, **modulul e sursa**; documentul o
descrie. Pentru partea de judecată — de ce, când, ce înseamnă — **documentul e sursa**;
modulul n-o duplică. Dacă vreodată diverg pe un tipar, **modulul are dreptate** și
documentul se corectează după el, fiindcă modulul e cel care rulează.

De ce e scris asta aici, înainte să existe gardianul: fără regula de mai sus, gardianul
își va face **propria copie** a formei — un regex scris de mână care „știe" ce e un
temei, lângă un document care spune altceva. Avem deja lista lucrurilor care au
divergat exact așa: mesajul de plafon TVA în trei suprafețe cu trei formulări
(`vat_plafon_msg.py`), termenul anual în două motoare (fiscal #7), numărul ONRC în două
locuri cu două date de verificare. Tiparul e mereu același — a doua copie pare
inofensivă în ziua în care se scrie.
