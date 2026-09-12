# Directoarea conduce compania: stare, diagnoză, repartizare, învățare

Raport cerut de Owner, 2026-09-12. Principiul: compania nu există ca să țină agenții ocupați.
Există ca să facă filme pe care oamenii le aleg, le termină, le dau mai departe și pentru care
se întorc.

## CE EXISTA DEJA

Am citit codul înainte să scriu o linie. Exista, și a fost refolosit:

| Ce | Unde | Ce făcea |
| --- | --- | --- |
| Directoare / CEO | `agents/director.py` | alege tema zilei, citește inboxul și răspunde cu ACKNOWLEDGE / REQUEST_INVESTIGATION / APPROVE / REJECT / ESCALATE_TO_OWNER, depune rapoartele etapelor, scrie Owner-ului |
| Verdictul pe film | `agents/editorial.py` | vizionează filmul finit, cu cadre, și un REJECT închide storyboard-ul |
| Verdictul pe poveste | `factual/story_review.py` | citește povestea înainte de producție (adăugat ieri) |
| Ierarhie și departamente | `agents/models.py`, `config/workforce_seed.json` | 8 roluri cu misiune, contract și agent activ |
| Coadă de sarcini | `workflows/models.py TaskQueueItem` | prioritate, încercări, lease, DEAD_LETTER |
| Orchestrare | `workflows/services.py`, `worker.py` | `scheduler_tick`, `ScheduledJob`, 5 tipuri de sarcini |
| Analitică | `analytics/` | `AnalyticsSnapshot`, `compute_cohort_metrics`, `generate_director_recommendations` (N≥3, ±0,20), `ContentExperiment`, `ContentStrategy` cu ponderi și `cooldown_until`, `TrendSnapshot` |
| YouTube | `youtube/`, `providers/youtube_analytics.py` | OAuth, ferestre 1h/24h/7d/28d/LIFETIME, `channel_bindings` |
| Conducta de conținut | `factual/`, `media/`, `runbook/stages.py` | teme → afirmații → scenariu → recenzie → storyboard → prompturi → randare → QC → publicare |
| Economie | `economy/` | `ProviderCostRecord` cu atribuire pe randare, bugete, `reconcile_day` |
| Watchdog | `agents/services.py` | curăță starea rămasă agățată; `measure_workforce` numără agenți inactivi, rata de eșec, coada, sarcinile moarte |
| Memorie | `agents/memory.py` | `MemoryRecord` cu clase, inclusiv STRATEGY |
| Mediu TEST/PRODUCȚIE | `owner_policy.environment` | starea studioului, schimbată doar de Owner |

Ce **nu** exista: o stare a companiei, o diagnoză de creștere, detectarea gâtuirii, repartizarea
lucrului către departamente, un registru de decizii strategice cu condiție de revizuire, și
normalizarea performanței per film.

## CE S-A REFOLOSIT

Nu există un al doilea sistem de management. Totul intră în ce era:

- Directoarea e **același agent**, cu același rol și același model; a primit o sarcină nouă
  (`direct_company`), nu un frate.
- Repartizarea se face prin **cutia poștală existentă** (`post_message`, intent HANDOFF către
  rolul care poate acționa), și escaladarea prin aceeași cutie cu `to_owner=True`.
- Bucla rulează pe **programatorul existent** (`ensure_scheduled_job`, `ScheduledJob`,
  worker-ul), ca job standard, în spatele opririi de autonomie.
- Agenții inactivi, rata de eșec și sarcinile moarte vin din **`measure_workforce`**, nu dintr-un
  contor nou.
- Recomandările pe ponderi rămân `DirectorRecommendation`, cu constrângerile ei din bază
  (minimum trei măsurători, schimbare mărginită la ±0,20). Nu am duplicat-o.
- Memoria strategică folosește `MemoryRecord` clasa STRATEGY.
- Analitica citește `AnalyticsSnapshot` existent; costul vine din `ProviderCostRecord` prin
  atribuirea pe `render_job_id` care era deja scrisă.
- Panoul e panoul existent „Rulare zilnică", cu o secțiune nouă. Niciun dashboard paralel.

## CE S-A MODIFICAT

- `backend/migrations/versions/0033_director_decisions.py` — tabelul `director_decision` și
  coloanele `topic_idea.priority` / `priority_reason`.
- `backend/app/analytics/performance.py` — **nou**: normalizarea per film, praguri, mediane
  rulante, clasificare cu încredere, diagnoză, sănătatea canalului, diagnoza de creștere,
  anomalii.
- `backend/app/agents/command.py` — **nou**: starea companiei, conducta și gâtuirea,
  prioritizarea backlogului, chestiunile ridicate de măsurători, bucla executivă, escaladarea,
  revizuirea deciziilor.
- `backend/app/analytics/models.py` — `DirectorDecision`.
- `backend/app/workflows/worker.py`, `backend/app/main.py` — tipul de sarcină `DIRECTOR_LOOP` și
  jobul standard, la fiecare 6 ore.
- `backend/app/runbook/router.py`, `backend/app/analytics/router.py` — endpointurile de stare,
  de conducere, de decizii și de performanță.
- `frontend/` — secțiunea „Compania acum" în panoul existent, cu butonul „Condu compania acum".

## CUM VEDE DIRECTOAREA STAREA COMPANIEI

`company_state()` întoarce, numai din rânduri stocate: mediul și dacă autonomia e oprită;
maturitatea datelor; fiecare canal cu publicate, măsurate, vizualizări în 7 zile față de
precedentele 7 și schimbarea procentuală, plus nota de bază; conducta pe etape cu ce e în lucru
neterminat și gâtuirea; agenții activi, inactivi, coada și sarcinile moarte, cu rata de eșec pe
agent; backlogul ordonat cu motivul; deciziile deschise; anomaliile; și ce limitează creșterea
pe fiecare canal.

Rulat pe o **copie** a bazei live, chiar acum:

```text
environment: TEST | autonomy stopped: False | maturity: COLD_START | measured films: 0
Main Channel A: published 0, measured 0, 0 measured films; a baseline needs 3
Channel B:      published 0, measured 0, 0 measured films; a baseline needs 3
pipeline: 6 teme propuse, 1 selectată, 1 scenariu aprobat, 4 randări, 6 QC trecute, 0 publicate
in flight: 2 | bottleneck: PUBLISHING (6 în așteptare, 0 trecute)
agents: 8 activi, 1 fără rulări, 0 sarcini moarte
growth: NO_DATA (LOW) pe ambele canale
```

## CUM FUNCȚIONEAZĂ MANAGEMENTUL AGENȚILOR

Directoarea nu face munca altora. Decide **ce** trebuie făcut și **cine** o face, iar
`ASSIGNABLE` spune ce poate primi fiecare departament — exact tabelul din promptul Owner-ului.
O repartizare care numește un rol inexistent sau o muncă pe care rolul nu o poate face este
refuzată de cod, nu doar descurajată. Repartizarea e o scrisoare HANDOFF cu observația,
interpretarea, încrederea, decizia, ce e de făcut și condiția de revizuire.

Maximum **trei** repartizări pe trecere: un executiv care dă douăsprezece sarcini într-o
dimineață nu a prioritizat nimic.

## CUM SE PREVINE LUCRUL DE UMPLUTURĂ

Trei reguli, toate în cod:

1. **O chestiune deja în lucru nu se ridică a doua oară.** Dacă există o decizie OPEN pe
   `matter_key`, trecerea următoare nu o repartizează din nou. Pe copia live, a doua trecere a
   răspuns: „3 chestiuni, toate deja în lucru cu o decizie deschisă."
2. **Agenții inactivi primesc lucru doar dacă nu e nimic în producție.** Cu filme în lucru,
   răspunsul e să se termine ce e început; chestiunea „idle" nici nu se ridică. Verificat de
   test: două teme selectate fac chestiunea să dispară.
3. **Nimic nu e un raport.** Fiecare chestiune poartă departamentul care poate acționa și
   munca pe care o primește. Ce nu poate deveni acțiune nu intră în buclă.

## CUM FUNCȚIONEAZĂ STARTUL LA RECE

`data_maturity`: 0 filme măsurate = COLD_START, sub 10 = EARLY_DATA, de la 10 = MATURE. La rece,
diagnoza de creștere spune `NO_DATA` cu încredere LOW și trimite munca spre cercetare, cu
decizia EXPERIMENT: nu se optimizează un număr care nu există și nu se inventează o audiență.
Un canal nemăsurat raportează `None`, nu zero — un zero s-ar citi ca o măsurătoare.

## CUM SE FOLOSEȘTE ANALITICA YOUTUBE

Prin integrarea existentă și prin instantaneele ei. Ferestrele sunt cele pe care integrarea le
poate cere efectiv: **1h, 24h, 7d, 28d, LIFETIME**. Nu 6h, nu 72h — o etichetă peste o perioadă
pe care nimeni nu a raportat-o e exact bugul pe care studioul l-a avut deja o dată. Ce nu a
raportat platforma este `None`. Nu există un al doilea client YouTube.

## CUM SE MĂSOARĂ CREȘTEREA CANALULUI

`channel_health` dă publicate, măsurate, vizualizări în ultimele 7 zile, cele 7 anterioare,
schimbarea procentuală, abonații pe ambele perioade și costul ultimei săptămâni, plus baza.
`growth_diagnosis` răspunde la întrebarea Owner-ului — ce împiedică creșterea — luând ultimele
zece filme măsurate, diagnosticând fiecare, și numind cauza care se repetă: REACH, RETENTION,
CONVERSION, TOPIC_SELECTION, NONE_VISIBLE sau NO_DATA, cu încredere HIGH doar de la trei filme
care arată la fel.

## CUM SE ANALIZEAZĂ REȚINEREA

Reținerea se citește **față de mediana canalului**, nu ca număr absolut. Sub 0,8 din mediană,
diagnoza e HOOK_OR_RETENTION_FAILURE și merge la scenarist. Ce studioul **nu** poate ști e unde
anume în film au plecat: curba de reținere pe secunde nu e în integrare, iar diagnoza spune asta
în text în loc să inventeze o secundă.

## CUM SE ANALIZEAZĂ CREȘTEREA ABONAȚILOR

`subscriber_conversion_percentage` = abonați câștigați / vizualizări. Exemplul Owner-ului, din
teste: 100 000 vizualizări cu 200 abonați dă 0,20%; 30 000 cu 300 dă 1,00%, iar al doilea film
e mai valoros strategic. Când vizualizările și reținerea sunt bune dar conversia e sub 0,6 din
mediană, diagnoza e CONVERSION_FAILURE și munca merge la final și la întrebarea de închidere.

## CUM SE EVALUEAZĂ PERFORMANȚA UNUI FILM

Niciodată pe total de vizualizări. `video_performance` dă rate: vizualizări pe oră și pe zi,
reținere, conversie, angajament, CTR, cost, minute de producție, vizualizări pe dolar, abonați
pe dolar, cost la mia de vizualizări. `classify` compară cu mediana canalului și întoarce
STRONG_WINNER, PROMISING, NORMAL, UNDERPERFORMER, FAILED_EXPERIMENT sau INSUFFICIENT_DATA, cu
încredere LOW/MEDIUM/HIGH.

Trei condiții pentru orice verdict: canalul are bază (minimum 3 filme măsurate), filmul are
minimum 24 de ore, și comparația e o rată. Fără una din ele, răspunsul este INSUFFICIENT_DATA —
care e un răspuns adevărat, nu o lipsă.

## CUM SE LEAGĂ COSTUL DE PERFORMANȚĂ

Costul unui film vine din `ProviderCostRecord` prin atribuirea pe randare; timpul din
`VideoRenderJob.duration_ms`. Amândouă stau pe același rând cu vizualizările, reținerea și
abonații, deci comparația din promptul Owner-ului se face direct. Un film fără consum tarifat
raportează cost `None`, nu zero: netarifat nu e gratis, și studioul a fost mușcat exact de
citirea asta.

## CUM SE IDENTIFICĂ FILMELE CÂȘTIGĂTOARE

Un film peste de trei ori rata canalului, la reținere cel puțin egală cu mediana, e
STRONG_WINNER — cu încredere care spune cât valorează verdictul. Un salt e ridicat și ca
anomalie VIEW_SPIKE, cu decizia sugerată **NEEDS_MORE_DATA** și munca la cercetare: „mai fă
unul" nu e o decizie, iar un film bun nu dovedește un format.

## CUM SE DIAGNOSTICHEAZĂ EȘECURILE

Patru cauze care se pot separa din datele existente, fiecare cu departamentul ei:

| Ce arată numerele | Cauza | Cine |
| --- | --- | --- |
| CTR sub 0,7 din mediană, sau afișări fără vizualizări | REACH_FAILURE | VideoEditor (primul cadru) |
| Reținere sub 0,8 din mediană | HOOK_OR_RETENTION_FAILURE | ScriptWriter |
| Vizualizări și reținere normale, conversie sub 0,6 | CONVERSION_FAILURE | ScriptWriter (final, îndemn) |
| Afișări și reținere normale, rată de vizualizări mică | TOPIC_FAILURE | LeadResearcher |
| Fără bază sau fără măsurători | INSUFFICIENT_DATA | nimeni |

Un film slab **nu** blochează o categorie. Nu există status BANNED sau BLACKLISTED nicăieri în
studio, iar pauza strategică e o scădere de prioritate în backlog, nu o pedeapsă permanentă.

## CUM SE OBSERVĂ CONCURENȚA

Prin ce există: `TrendSnapshot`, adică ce caută publicul, citit din feedul public, și paginile de
pe gazdele autorizate. Modelul propriu al studioului spune despre trenduri „never a source,
never a claim" — un trend e un cârlig, nu o dovadă.

Ce **nu** face studioul, și e verificat de un test: nu inventează niciun număr privat al altui
canal. Reținerea, watch time-ul, veniturile, conversia sau CTR-ul altcuiva nu sunt publice, deci
nu apar nicăieri în ce citește Directoarea. Observarea structurată a canalelor concurente
(titluri, frecvență, formate) **nu este implementată** — e în limitele de mai jos.

## CUM FUNCȚIONEAZĂ EXPERIMENTELE STRATEGICE

O decizie se scrie în opt câmpuri: observație, dovezi, interpretare, încredere, decizie, ce e de
făcut, cine, și condiția de revizuire. Baza **refuză** o decizie fără condiție de revizuire,
afară de NEEDS_MORE_DATA: o decizie pe care nimeni nu o verifică e o părere. Deciziile sunt
SCALE, CONTINUE, ITERATE, EXPERIMENT, HOLD, COOLDOWN, REDUCE, STOP, NEEDS_MORE_DATA — lista
Owner-ului, neschimbată. Când filmele pe care aștepta au fost publicate, decizia se ridică din
nou ca chestiune și se închide cu ce s-a întâmplat.

## CUM CREEAZĂ ANALITICA MUNCĂ

Fiecare chestiune ridicată de măsurători poartă departamentul și munca. Trecerea repartizează
cel mult trei, scrie scrisoarea, scrie decizia și o pune în memoria studioului. Pe copia live,
prima trecere a repartizat gâtuirea de la publicare către Publisher și startul la rece al ambelor
canale către cercetare, fiecare cu revizuire după 3 filme.

## CUM ÎNVAȚĂ DIRECTOAREA ÎN TIMP

Trei bucle: maturitatea datelor mută greutatea de la judecată editorială spre performanța
proprie; deciziile se închid cu rezultatul, deci strategia însăși devine verificabilă; și
notele Directoarei despre imagine devin lecții de prompt pentru filmul următor (adăugat ieri).

## REZULTATELE TESTELOR

`uv run pytest -q` — **674 trecute, 1 sărit** (Ollama real, neconfigurat). `ruff check`,
`ruff format --check`, `mypy` curate. `npm test` 86 trecute, `npm run check` și `npm run build`
curate. `scripts/check_docs.py` verificat.

Cele 30 de verificări cerute sunt în `tests/test_director_command.py`. Validare pe date reale,
pe o copie a bazei live: migrarea 0033 se aplică curat, cheile străine sunt curate, starea
companiei a ieșit corectă, gâtuirea reală a fost găsită (6 filme trecute prin QC, 0 publicate),
backlogul a fost reordonat după dovezi (tema selectată cu 9 afirmații verificate prima, cea fără
dovezi ultima), prima trecere a repartizat trei chestiuni și a doua nu a repartizat nimic.

## LIMITE CARE RĂMÂN

1. **Curba de reținere pe secunde nu există în integrare.** Diagnoza poate spune că reținerea e
   slabă, nu la ce secundă pleacă spectatorul. Exemplul Owner-ului cu „puternic la 3 secunde,
   slab între 5 și 12" nu se poate calcula azi; ar trebui raportul `audienceRetention` din
   YouTube Analytics, care nu e cerut încă.
2. **Observarea concurenței nu e implementată** peste trendurile publice. Titluri, frecvență și
   formate ale altor canale ar cere o capabilitate nouă și autorizată; nimic nu e inventat în
   locul ei.
3. **Ferestrele multiple nu sunt ingerate.** Ziua măsoară LIFETIME; 1h/24h/7d/28d sunt
   disponibile în adaptor dar nu sunt colectate, deci „viteza la 24 de ore" se calculează din
   vârsta filmului, nu din raportul de 24 de ore.
4. **Pragurile sunt numerele studioului.** 3x pentru câștigător, 0,6 pentru subperformanță, 3
   filme pentru bază, 24 de ore pentru un verdict. Nu sunt învățate din rezultate; ar cere
   zeci de filme măsurate.
5. **Nu există încă experimente A/B conduse de Directoare.** `ContentExperiment` există și nu e
   încă deschis automat de buclă; deciziile EXPERIMENT sunt repartizări, nu variante controlate.
6. **Timpul de producție e doar durata randării.** Timpul de idee, cercetare și scenariu nu e
   cronometrat, deci „38 de minute per film" măsoară randarea, nu munca întreagă.
7. **Bucla nu pune sarcini în coadă.** Repartizează prin scrisori către departamente, pentru că
   worker-ul execută cinci tipuri de sarcini reale; a inventa tipuri noi fără executant ar fi
   exact infrastructura de umplutură pe care Owner-ul a interzis-o.
