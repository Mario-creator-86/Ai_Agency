# Rutarea modelelor: mediu de test, mediu de producție, și viața unui model

Raport cerut de Owner, 2026-09-12. Toate numerele din el sunt măsurate pe contul Owner-ului,
nu citite pe o pagină de vendor.

## CE EXISTA DEJA

Nimic din ce urmează nu a fost construit de la zero. Studioul avea deja, și a fost extins:

| Ce exista | Unde | Ce făcea |
| --- | --- | --- |
| Catalog de modele descoperit din API | `app/integrations/discovery.py` | citește modelele contului, contractul vendorului (task-uri, formate, durate), le scrie în `provider_resource` |
| Ierarhia de producție | `app/media/production_policy.py` (`resolve_purpose`) | Organizație → canal → serie → episod → scenă + blocaje de personaj |
| Clasare de candidați | `rank_candidates`, `PRIORITY_WEIGHTS` | scor pe calitate, cost, viteză, fiabilitate; „premium" pune calitatea prima |
| Preț și estimare | `estimate_cost_usd`, `credit_usd`, `record_measured_price` | trei unități (caracter, imagine, secundă) plus credite; prețul măsurat din randări |
| Alegerea adaptorului | `app/media/factory.py` | ce adaptor filmează fiecare scenă |
| Pasul de mișcare din randare | `app/media/assembler.py` | clip per scenă, dizolvări, plafon de buget, cadru întâi |
| Cercetarea stewardului | `app/media/model_research.py` | angajatul citește paginile vendorului și notează modele (săptămânal) |
| Contabilitate | `app/economy/accountant.py` | costul fiecărei randări în registre, pe scenă și unitate |
| Comandă versionată a Owner-ului | `app/services.py` (`change_stop`, `CommandRecord`) | idempotentă, cu conflict la versiune veche |
| Programator de sarcini | `app/workflows/worker.py` | zi, review săptămânal, trenduri, cercetare de modele |

## CE S-A MODIFICAT

- `backend/migrations/versions/0031_environment_and_model_lifecycle.py` — mediul în
  `owner_policy`, starea și proveniența prețului pe `provider_resource`, tabelul
  `model_outcome`.
- `backend/app/integrations/lifecycle.py` — **fișier nou**: stațiile din viața unui model,
  lista de refuz, clasificarea unui model nou, proveniența prețului, review-ul periodic.
- `production_policy.py` — `SceneRequirement`, `choose_model` (un router, două politici),
  `QUALITY_TIERS`, `SCENE_ROLE_TIERS`, `scene_role`, `required_quality`, `model_record`,
  `record_quoted_price`, `named_model`.
- `factory.py` — `motion_for_scene` (înlocuiește `test_motion_provider`): cere un model pe
  bază de cerință, întoarce adaptorul **și motivul**.
- `assembler.py` — `motion_chooser`, `environment`, `run_kind`, `scene_tier`, cotația
  vendorului înainte de cumpărare, plafon per secundă, `_record_outcomes`.
- `media/router.py` și `runbook/stages.py` — citesc mediul din starea studioului, trimit
  plafoanele și toleranța de preț.
- `providers/runway.py` — contractul spune dacă un task acceptă dry run; `estimate_generation`
  și anularea unei sarcini pornite din greșeală.
- `economy/accountant.py` — `price_change_alert`, o singură scrisoare pentru schimbări de preț.
- `integrations/discovery.py` — model nou clasificat, preț cu proveniență, `settings` primite.
- `config.py` — controalele Owner-ului (mai jos).
- `frontend/` — bannerul de mediu în bara de sus, butonul de schimbare lângă comutatorul de
  autonomie, și explicația deciziei sub fiecare film randat.

## CUM FUNCȚIONEAZĂ RUTAREA ÎN TEST

Un test răspunde la întrebarea „merge?". O imagine mediocră este un răspuns bun.

1. Se strâng modelele **compatibile**: task-ul cerut, disponibile în cont, nu pe lista de
   refuz, nu retrase.
2. Se ordonează după **cost**, iar un model fără preț este pus **ultimul** — un test fără preț
   este exact felul în care o după-amiază a costat 21,08 USD.
3. Se elimină cele care depășesc plafoanele (mai jos). Dacă nu rămâne niciunul, **nu se
   generează nimic** și motivul spune cât ar fi costat cel mai ieftin.
4. Clasarea pe calitate **nu este consultată**. Rezerva unui model ieftin care eșuează este
   următorul cel mai ieftin, niciodată cel mai bun.
5. În test filmul se face **din text** (nu se cumpără un cadru întâi) și doar pentru
   `STUDIO_TEST_MOTION_SCENES` scene (implicit 2).

## CUM FUNCȚIONEAZĂ RUTAREA ÎN PRODUCȚIE

Un film se vede. Aici întrebarea este „cât de bun trebuie să fie **această** scenă".

1. Doar modelele **admise** (CANDIDATE, PRODUCTION, PREFERRED) pot filma ceva ce va fi
   publicat. Dacă niciunul nu e admis, randarea refuză și spune care așteaptă afară.
2. Formatul primul: un model care nu poate livra 1080×1920 nu intră în discuție pentru un
   film 9:16 — o imagine mărită artificial nu e premium.
3. Nivelul cerut vine din **rolul scenei în film**: HOOK 0,93, scenele-cheie 0,88, restul
   0,80, finalul 0,93. Primul cadru decide dacă cineva se uită, ultimul dacă cineva comentează.
4. Se alege **cel mai ieftin model care atinge** nivelul cerut — nu cel mai bun, nu cel mai
   ieftin. Costul folosit este **pe secundă acceptată**, nu pe secundă facturată: un cadru
   plătit și aruncat a costat la fel.
5. Decizia scrie **ce nu a cumpărat și de ce**: „X e așteptat la 0,96 (+0,08) pentru 3,0x
   costul, ceea ce scena nu cere". Exact întrebarea marginală pusă de Owner.
6. Dacă nimic nu atinge nivelul, se alege cel mai bun disponibil și se spune explicit că
   nivelul nu a fost atins. Tăcerea ar fi o minciună despre calitate.

## CUM SE DECIDE MEDIUL

`owner_policy.environment` — starea studioului, în baza de date. Se schimbă **numai** prin
`POST /owner/environment`, cu aceeași comandă versionată și idempotentă care oprește
autonomia: `command_id` plus `expected_version`, iar o versiune veche primește 409.

Nicio cerere de randare nu poartă mediul. Pagina îl **afișează** și cere schimbarea; nu îl
decide. Un agent nu îl decide. Un parametru de query nu îl poate falsifica. Implicit, un
studio nou pornește în **TEST** (migrarea are `server_default 'TEST'`): un studio care nu știe
în ce mediu e nu trebuie să cheltuiască ca un studio de film.

## CUM SE PREVIN COSTURILE PREMIUM ACCIDENTALE LA TESTE

Patru plafoane, verificate în locuri diferite, pe numere din setări:

| Plafon | Setare | Implicit | Unde mușcă |
| --- | --- | --- | --- |
| Cost pe o generare | `STUDIO_TEST_MAX_COST_PER_GENERATION_USD` | 0,60 USD | la alegerea modelului și din nou pe cotația vendorului |
| Cost pe secundă | `STUDIO_TEST_MAX_COST_PER_SECOND_USD` | 0,12 USD | la fel, de două ori |
| Scene generate | `STUDIO_TEST_MOTION_SCENES` | 2 | pasul de mișcare |
| Buget pe film | `STUDIO_MOTION_BUDGET_USD` | 12 USD | prima cotație învață prețul, apoi restul e comparat cu ce a rămas |

În plus: modelul fără preț e ultimul, nu primul; în test se filmează din text, deci nu se
cumpără un cadru întâi; și cotația vendorului, unde există, decide în locul prețului scris.

## CUM FUNCȚIONEAZĂ CLASAREA MODELELOR

Trei surse, în ordinea în care au greutate:

1. **Rezultatele proprii** (`model_outcome`): rata de acceptare din generările judecate.
   Sub trei generări judecate nu poate acoperi altceva — un cadru norocos nu e o dovadă.
   De la trei în sus, greutatea crește până la zece generări.
2. **Nota stewardului** (`capabilities.quality_score`), din paginile vendorului.
3. **Costul pe secundă acceptată**, din facturi reale, nu din estimări.

Ce **nu** intră în clasare: vechimea modelului, marca vendorului, ordinea din catalog. Iar un
test funcțional (pe un model deja admis) nu învață niciodată studioul nimic despre imaginea
acelui model — altfel un cadru ieftin cumpărat intenționat ar strica reputația modelului.

## CUM SE SCHIMBĂ PREȚURILE

Trei feluri de preț, distincte: **DOCUMENTED** (o pagină citită), **ESTIMATED** (o cotație
dry-run), **BILLED** (ce s-a facturat). Contabilitatea crede ultimul; istoricul contabil nu se
rescrie niciodată.

**Ce a facturat contul are prioritate peste ce scrie pe o pagină.** Pe studioul live,
stewardul a citit „0,08 USD pe secundă" pentru modelul pe care patru randări îl măsuraseră la
**0,43** — și citirea a înlocuit măsurătoarea. Cu 0,08 stocat, un test ar fi trecut plafonul
de 0,12 USD/s și ar fi fost facturat de 3,6 ori mai mult. De acum un preț documentat nu mai
suprascrie unul facturat: cifra facturată rămâne prețul cu care studioul își face bugetul,
cifra din documentație e păstrată lângă ea (`documented_per_second_usd`), iar dezacordul ajunge
în scrisoare.

Orice scriere de preț trece prin `stamp_price`, care păstrează `previous_pricing_json`,
incrementează `pricing_version` și notează `price_verified_at` și `price_verification`. O
mișcare peste `STUDIO_PRICE_CHANGE_ALERT_PERCENT` (implicit 10%) devine o **scrisoare de la
Contabil către Owner** — aceeași scrisoare, fie că prețul a fost măsurat dintr-o randare, fie
că a fost citit de steward pe pagina vendorului.

O cotație care diferă de prețul stocat cu mai mult de
`STUDIO_PRICE_STALE_TOLERANCE_PERCENT` (implicit 5%) înseamnă că prețul stocat e **învechit**:
se înlocuiește, marcat ESTIMATED, și randarea folosește numărul vendorului pentru decizia de
buget. Cotația se cere **numai** unde contractul publicat al vendorului declară că task-ul
acceptă dry run; un flag nedeclarat nu se trimite niciodată, pentru că o întrebare despre preț
nu trebuie să devină o cumpărare. Dacă vendorul întoarce totuși o sarcină, e anulată imediat.

## CUM SE TRATEAZĂ MODELELE NOI

Stațiile: DISCOVERED → QUARANTINE → BENCHMARKING → CANDIDATE → PRODUCTION → PREFERRED, plus
DEPRECATED.

- Un model apărut azi în catalog e **luat în catalog** (ca să-l vadă Owner-ul) și **ținut
  afară din producție**.
- Un model al cărui contract nu s-a putut citi are capabilități necunoscute → **carantină**.
  Nu se încearcă pe un film ca să se afle.
- Un model pe care îl numește `STUDIO_MODEL_DENY_LIST` (tipare cu `*`) e retras la vedere și
  nu e ales în niciun mediu; doar regizorul, numindu-l explicit, îl mai poate folosi.
- Cu `STUDIO_AUTO_BENCHMARK_NEW_MODELS` pornit, review-ul îl trece în BENCHMARKING; un test
  pe un model neadmis **este** benchmark-ul lui (`run_kind = TEST_BENCHMARK`) — altfel un
  model nou nu ar putea niciodată să intre, pentru că nu are voie să filmeze producție până
  are rezultate.
- Review-ul zilnic (`MODEL_REVIEW`, job programat, nu generează nimic deci nu costă nimic)
  promovează cu `STUDIO_MIN_TEST_SAMPLES_FOR_PROMOTION` generări judecate și ≥80% acceptare,
  retrogradează sub 50% sau după eșecuri tehnice, și retrage un model care costă de peste 3x
  pe secundă acceptată față de cel mai ieftin model admis.

Controalele Owner-ului: `STUDIO_AUTO_DISCOVER_MODELS`, `STUDIO_AUTO_BENCHMARK_NEW_MODELS`,
`STUDIO_AUTO_PROMOTE_CHEAPER_BETTER_MODELS`, `STUDIO_AUTO_DEMOTE_EXPENSIVE_MODELS`,
`STUDIO_MAX_BENCHMARK_BUDGET_USD`, `STUDIO_PRICE_CHANGE_ALERT_PERCENT`,
`STUDIO_MIN_TEST_SAMPLES_FOR_PROMOTION`, `STUDIO_PRICE_STALE_TOLERANCE_PERCENT`,
`STUDIO_MODEL_DENY_LIST`.

## CE S-A REFOLOSIT

Nu există un al doilea router, un al doilea sistem de selecție sau o a doua pagină. `choose_model`
stă lângă `rank_candidates` și `resolve_purpose`, în același fișier, și le folosește:
disponibilitatea din `resource_available`, scopurile din `usable_purposes`, prețurile din
`estimate_cost_usd` și `credit_usd`, formatul din `delivers_studio_frame`. Un model numit de un
nivel al ierarhiei (canal, serie, episod, scenă, personaj) este tratat ca **override** și
respectat; doar implicitul Organizației, care e modelul implicit al conexiunii, lasă politica
să decidă — asta era exact ce cerea Owner-ul de la agent.

Randarea e aceeași randare: `assemble_video_job` a primit un mod de a **cere** un model, nu un
al doilea pas de mișcare. Review-ul periodic rulează pe programatorul existent, lângă
cercetarea stewardului. Scrisoarea de preț folosește cutia poștală existentă.

## REZULTATELE TESTELOR

`uv run pytest -q` — **625 trecute, 1 sărit** (Ollama real, neconfigurat). `ruff check`,
`ruff format --check` și `mypy` curate; `npm test` 86 trecute, `npm run check` și
`npm run build` curate; `scripts/check_docs.py` verificat.

Cele 18 verificări cerute sunt în `tests/test_environment_routing.py`, una pe punct: 1-7
mediul de test (cel mai ieftin compatibil, rezerva tot ieftină, ambele plafoane, override-ul
regizorului, mediul decis de server cu 409 la versiune veche, minimul randat), 8-13 producția
(cel mai ieftin care atinge nivelul, nivelul din rolul scenei, ce nu s-a cumpărat și
multiplul, nivelul neatins declarat, modelul neadmis refuzat, modelul retras/refuzat exclus
din ambele medii), 14-18 învățarea (înregistrarea per generare cu mediu și fel, rezultatele
proprii peste notele de pe pagini, promovare și retrogradare, prețul care se schimbă cu
scrisoare către Owner, cotația care declară prețul învechit și modelul nou care așteaptă
afară).

`scripts/check_secrets.py` nu a putut rula: `detect_secrets` nu e instalat în acest mediu.

## CE A RĂSPUNS CATALOGUL REAL

Rulat pe o **copie** a bazei live (niciodată pe `data/studio.db`), cu 61 de modele video
disponibile în cont și migrarea 0031 aplicată curat (70 de modele existente rămân în
PRODUCTION, verificare de chei străine curată, studioul pornește în TEST):

| Mediu / nivel | Model ales | Preț pentru 6,4 s | Motivul |
| --- | --- | --- | --- |
| TEST / STANDARD | `seedance2_mini` | 0,128 USD | cel mai ieftin compatibil; clasarea nu e consultată |
| PRODUCȚIE / STANDARD | `seedance2` | 0,32 USD | atinge 0,80 cerut; `seedance2_5` ar fi +0,10 calitate pentru **1,6x** costul, ce scena nu cere |
| PRODUCȚIE / HERO | `seedance2_5` | 0,512 USD | nimic nu atinge 0,93, cel mai bun disponibil e la 0,90 — și o spune |

Asta este exact răspunsul la întrebarea Owner-ului: pe o scenă obișnuită studioul **nu** mai
cumpără modelul scump, iar când o face, scrie de ce și cu ce multiplu.

## LIMITE CARE RĂMÂN

0. **Prețurile din catalog sunt cele din documentația vendorului, nu măsurate.** Toate cele
   14 prețuri de pe conexiunea live au sursa `docs.dev.runwayml.com`, scrise azi la 12:47.
   Măsurătoarea de 0,43 USD/s de pe contul Owner-ului nu mai e în catalog. Regula nouă
   împiedică suprascrierea de acum înainte, dar **cifrele stocate azi sunt cele documentate**;
   prima randare de producție le va corecta cu ce facturează vendorul.
1. **Calitatea nu e încă judecată per model.** `accepted` înseamnă acum „cadrul a ajuns și a
   intrat în film" — deci măsoară fiabilitatea, nu frumusețea. Verdictul editorial al
   Directoarei (care se uită la cadre) nu se întoarce încă pe modelul care le-a filmat. Până
   se leagă, „calitatea observată" e de fapt „livrare observată".
2. **Nu există pachete de benchmark.** `STUDIO_MAX_BENCHMARK_BUDGET_USD` e declarat și notat,
   dar studioul nu filmează încă un set fix de prompturi pentru un model nou; benchmark-ul se
   întâmplă când o randare de test îl alege. Deci un model nou intră doar dacă e și cel mai
   ieftin compatibil.
3. **Dry run doar unde vendorul îl declară.** Contractul publicat de Runway nu declară azi
   `dryRun` pe task-urile video, deci în practică prețul rămâne cel măsurat plus
   `estimatedCost` pe care vendorul îl întoarce la trimiterea sarcinii (înregistrat ca BILLED
   după randare). Mecanismul e pregătit și se activează singur dacă apare în contract.
4. **Categoria scenei e aproximativă.** Se ia din `visual_type` al storyboard-ului; nu există
   încă o taxonomie proprie (oameni, vehicule, peisaj), deci scorurile per categorie au date
   subțiri.
5. **Frontiera calitate/cost nu e trimisă.** Review-ul complet o calculează și o întoarce în
   rezultat, dar nimeni nu scrie încă o scrisoare „am găsit o rutare mai bună".
6. **Review-ul „complet" săptămânal** este cercetarea stewardului care exista deja; împărțirea
   e: zilnic rezultatele proprii, săptămânal paginile vendorilor.
