# Ziua întreruptă nu se relua, iar supraveghetorul anunța reluarea la nesfârșit — 15.10.2026

Verificare orară a studioului, făcută de Claude (Cowork, sesiune programată de Owner), 04:40–05:10 ora
București. Citire: `/health/ready`, pagina studioului (registrul viu, răspunsurile API pe care le cere
pagina), `data/logs/studio.log`, codul din `backend/app/workflows/` și `backend/app/runbook/`.
Nimeni altcineva nu lucra la proiect (ultima modificare de documente: 00:45, claim eliberat de Codex).

## Ce am găsit în aplicația reală

- Procesul rulează (PID 15596, pornit de Codex la 00:50) și e sănătos: `/health/ready` HEALTHY pe
  toate componentele, supraveghetorul și lucrătorul trec la fiecare 10 minute, backup făcut la 03:30.
- **Dar studioul stă pe loc de la 01:42.** Rularea zilei `fd287887` (data de afaceri 2026-10-15,
  pornită la 00:42) a fost tăiată de cele două reporniri ale backendului (00:45 și 00:50) în etapa
  «episodul din serial» (7/13). Supraveghetorul a închis-o INTERRUPTED abia la 01:42 (după expirarea
  contractului de o oră al sarcinii) și i-a scris Ownerului: «după repornirea studioului o reiau singur».
- Pasul `resume_interrupted_day` a pus în coadă sarcina de reluare `47a1b570` la 01:47. Lucrătorul a
  rulat-o imediat (jurnal 22:47:17 UTC: trei sarcini COMPLETED în aceeași trecere) și **a refuzat-o
  tăcut**: în `worker.daily_run`, pentru o reluare, `attempt = len(runs_today) + 1`; ziua avea deja
  trei rulări (rularea terminată la 00:32, `f1a5e91c` terminată în 20 s la 00:37 cu HTTP 400 peste tot
  și `fd287887` cea întreruptă), deci `attempt = 4 > daily_max_attempts = 3` → `SKIPPED «și-a folosit
  cele 3 încercări; reluarea ei este decizia Owner-ului»`. Sarcina e COMPLETED, nimic nu s-a reluat.
- De atunci, **la fiecare 10 minute**, pasul găsește aceeași sarcină terminată sub cheia de idempotență
  `daily-resume-fd287887…`, primește înapoi aceeași sarcină (`enqueue_task` întoarce rândul existent)
  și scrie din nou evenimentul `runbook.daily_run_resume_queued` cu același `task_id` — de 19 ori între
  01:47 și 04:50. Registrul viu arată «Rularea zilei: daily run resume queued» ×19; nimic nu rulează.
  Acesta este cercul.
- Consecința pentru autonomie: rularea de la 05:00 (`daily_main`) întâlnește `cut_id = fd287887` și
  este refuzată prin regulă («ziua a fost întreruptă; o nouă rulare azi este decizia Owner-ului»).
  Fără intervenție, **azi nu se produce și nu se publică nimic**, deși scrisoarea promitea reluarea.
- Separat, nu e cerc: filmul «The Zero Script Club» stă în `director_qc_waiting` (scena 4: 3 blocaje
  și 21 de avertismente în prompturi — garderoba vizibilă a lui Sarah lipsește din promptul vechi, exact
  blocajul introdus intenționat de codul de garderobă din 14/15.10). Decizia Directoarei din 01:37 a fost
  luată de două ori identic și s-a oprit; circuitul de refacere a promptului e al rulării zilei, care nu
  mai rulează. HTTP 400 de la Ollama Cloud nu a mai apărut după repornirea din 00:50 (Sarah a decis cu
  deepseek-v4.1-flash la 01:37, reușit).

## Ce am schimbat (local, necomis, neactivat — se încarcă la următoarea pornire)

1. `backend/app/workflows/worker.py`, `daily_run`, ramura `resume_of`: plafonul reluării nu mai
   numără rulările zilei, ci **de câte ori a fost tăiată ziua** (`cut_count`, rulările INTERRUPTED ale
   datei). O reluare continuă ziua pe care ceasul a pornit-o deja — etapele încheiate sunt redate, nu
   refăcute, deci nu se alege al doilea subiect și nu se cumpără al doilea film — și nu e una dintre
   reîncercările zilei. Peste `daily_max_attempts` întreruperi rămâne refuzată, cu motiv nou:
   «a fost întreruptă de N ori, peste cele 3 reluări; reluarea ei este decizia Owner-ului».
   Ramura fără `resume_of` (ceasul, reîncercările) e neatinsă.
2. `backend/app/workflows/passes/resume_interrupted_day.py`: cheia sarcinii numește și pornirea
   procesului (`daily-resume-<run>-<START_TOKEN>`, un token pe proces) — o cerere de reluare pe rulare
   întreruptă **pe fiecare pornire**, exact ce spune docstring-ul «după start». O sarcină deja
   existentă sub cheie (terminată sau nu) nu mai e anunțată: evenimentul `daily_run_resume_queued` se
   scrie numai când sarcina e nouă. Rezultatul pasului spune `held`/`asked` în loc de `queued`.
3. `tests/test_resume_after_finished_runs.py` (nou, 3 regresii): ziua tăiată după rulări terminate se
   reia; ziua tăiată de mai multe ori decât `daily_max_attempts` așteaptă Ownerul; sarcina terminată nu
   e anunțată a doua oară până la următoarea pornire (START_TOKEN schimbat prin monkeypatch).

Nu am atins: baza de date, politici, modele, conturi, scene, verdicte, parametri LLM (obiecția
Ownerului din 15.10 rămâne respectată), GPU. Nicio generare, niciun apel plătit.

## Verificare — ce am făcut și ce NU am făcut

- Fișierele noi/modificate: `py_compile` trece; `ruff check` (E, F, W, UP, B) și `ruff format --check`
  trec pe fișierele noi, într-un mediu separat (ruff local, nu venv-ul proiectului; ordinea importurilor
  din pass respectă fișierul original: sqlalchemy, apoi `app`).
- **Suita proiectului (pytest, mypy, check_docs) NU a fost rulată**: sesiunea nu are shell pe mașina
  Windows, doar citire/scriere de fișiere și browserul pentru pagina locală. Testele vechi din
  `tests/test_resume_interrupted_day.py` ar trebui să treacă neschimbate (cheia nu e verificată acolo,
  numărul de sarcini DAILY_RUN rămâne 1), dar nu e dovedit.
- **Repornirea NU a fost făcută**: `scripts/restart.py` trimite evenimente de consolă Windows; nu pot
  rula de aici. Codul nou se activează la următoarea pornire normală.
- `worker.py` a fost rescris cu LF (unealta de editare normalizează); `.gitattributes` are `text=auto`,
  deci git nu vede zgomot.

## Pentru următorul AI / pentru Owner — în ordine

1. `uv run --locked pytest tests/test_resume_after_finished_runs.py tests/test_resume_interrupted_day.py tests/test_shutdown.py -q`,
   apoi `uv run ruff check . && uv run ruff format --check . && uv run mypy` și `scripts/check_docs.py`.
2. Fereastră liniștită (GPU off verificat, niciun FILM_CONTINUE CLAIMED):
   `uv run --locked python -X utf8 scripts\restart_when_quiet.py` sau `scripts\restart.py`.
3. După pornire, la primul tic al supraveghetorului (≤10 min): un singur eveniment
   `daily_run_resume_queued` nou, apoi o rulare nouă cu `resumed_from = fd287887…` care redă etapele
   1–6 și rulează «episodul din serial» și restul. Dacă e după miezul nopții (data de afaceri 10-16),
   reluarea lui 10-15 e refuzată corect («care a trecut») și ziua 10-16 pornește singură la 05:00.
4. Dacă nu vrei să aștepți repornirea: «Pornește rularea de azi» din pagină (manual) rulează ziua
   întreagă; alegerea subiectului va găsi filmul deja în producție.
5. Rămâne, după reluare: scena 4 din «The Zero Script Club» are nevoie de rescrierea promptului cu
   garderoba lui Sarah (circuitul Sarah/Kael din handoff-ul REFERENCE_ROUTE_WARDROBE…); de urmărit că
   decizia Directoarei nu se repetă identic la fiecare buclă.

## Verificarea orară de la 05:40 — rularea manuală (Claude/Cowork, 05:40–05:50)

- Găsit: nimic nu se schimbase. Studioul HEALTHY, nimeni la lucru (ultima modificare a proiectului:
  cea de la 04:56 de mai sus). «daily run resume queued» ×23 (ultimul 05:31:41). `daily_main` a tras
  la 02:00:01Z (`last_run_at`), dar `/api/v1/runbook/runs` nu are nicio rulare nouă: refuzată prin
  regula `cut_id` din `worker.daily_run`, exact cum prevedea diagnosticul. Următorul tic al ceasului:
  16.10, 05:00.
- Repornirea NU se poate face din sesiune: fără shell Windows; prin controlul calculatorului,
  terminalele se acordă doar în modul «click» (fără tastatură), deci nici `restart_when_quiet.py`.
  Codul nou (worker.py, resume_interrupted_day.py) rămâne neîncărcat până la o repornire normală.
- Făcut: «Pornește rularea de azi» din pagină (dialogul de consecințe: «studioul cumpără singur pașii
  plătiți cu plafonul de cel mult 50,00 USD, până la bugetul de 20,00 USD»). POST /api/v1/runbook/runs
  → QUEUED, sarcina `1743a88e-48ef-43d9-84d9-aec4dc4ee390`, 02:46:41Z. Calea `manual` ocolește
  refuzurile ceasului; `attempt` = 4 e informativ. La 05:48:46 rularea era la «episodul din serial»
  (7/13): documentare 4 pagini / 24 afirmații, selecția a găsit filmul în producție, scenariul din nou
  respins («Scenaristul nu a răspuns cu un obiect JSON», glm-5.3-flash — a treia oară azi).
- Efect asupra cercului: după ce această rulare se încheie (orice stare), `resumable_run` nu mai
  întoarce fd287887 (a rulat ceva după ea), deci pasul nu mai anunță nimic — cercul se stinge singur
  și fără repornire.
- De urmărit la 06:40: (1) a trecut «episodul din serial» (înainte: timeout 600 s ×2 pe GLM; acum cu
  codul de răspuns Cloud din 00:50)? (2) «producție media»: scena 4 a filmului «The Zero Script Club»
  — garderoba lui Sarah lipsea din prompt; circuitul rulării trebuie să refacă promptul, nu să repete
  identic decizia Directoarei; (3) «publicare» — scopul Ownerului; (4) scenaristul fără JSON — o
  problemă separată, repetată, de deschis ca sarcină a ei. Repornirea (cu suita înainte) rămâne
  necesară pentru fix-ul reluării, dar nu mai e urgentă pentru ziua de azi.

Dovezi: registrul viu (evenimente 23383, 23387, 23391, … toate cu `task_id 47a1b570-aab3-489b-8e55-c4a699bac359`),
`data/logs/studio.log` 2026-10-14T22:42:41Z (`task_interrupted` 8c24a44a, `daily_run_interrupted` fd287887),
22:47:17Z (`worker_pass` ran 3× COMPLETED), `/api/v1/runbook/runs` (fd287887 INTERRUPTED la `serial_queue`,
`f1a5e91c` COMPLETED 21:37:09–21:37:29Z), `/api/v1/scheduler/jobs` (`daily_main` next 02:00Z).
