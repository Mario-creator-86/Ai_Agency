# Ideea, povestea, scenariul, promptul: ce decide studioul înainte să genereze

Raport cerut de Owner, 2026-09-12. Principiul: **idee bună + poveste bună + scenariu bun +
prompt bun = video bun.** Un model video puternic nu salvează o idee slabă. Deci studioul
optimizează întâi conținutul și abia apoi generarea.

## CE EXISTA DEJA

Am căutat în cod înainte să scriu o linie. Exista, și a fost refolosit:

| Etapă | Unde | Ce făcea |
| --- | --- | --- |
| Cercetare | `app/research/agent.py`, `service.py`, `retrieval.py` | propune teme, caută pagini, descarcă el însuși paginile |
| Registru de surse de încredere | `ResearchAllowedHost` + gazde din `.env`, testate | numai gazde autorizate și testate PASSED |
| Descoperire de idei | `propose_topics` → `TopicIdea` PROPOSED | șase criterii, deduplicare Jaccard, semnale din trenduri și din performanța măsurată |
| Verificare factuală | `agent_extract_claims`, `agent_verify_claim`, `evaluate_factual_gate` | extractor și verificator **independenți**, dovadă verbatim în pagină |
| Scenarist | `agent_write_script` | scrie numai din afirmații SUPPORTED, fiecare scenă citează, o rescriere la citări lipsă |
| Aprobarea Owner-ului | `approve_script_draft` | VERIFIED_PASS → APPROVED, cu poarta factuală recitită |
| Aprobarea Directoarei | `agents/director.py`, `agents/editorial.py` | alege tema zilei; vizionează filmul finit, cu cadre, și un REJECT închide storyboard-ul |
| Mașina de stări a producției | `runbook/services.py STAGES`, statusuri pe `Storyboard`/`ScriptDraft` | ordinea zilei, de la idei la publicare |
| „Prompt video" | `StoryboardScene.visual_prompt` | **o singură linie**, scrisă de scenarist sub `visual` |
| Runway și rutarea modelelor | `providers/runway.py`, `media/production_policy.py` | contract publicat, `choose_model`, TEST/PRODUCȚIE |
| Analitică | `AnalyticsSnapshot`, `compute_cohort_metrics`, `ContentStrategy` | reținere, CTR, cohorte, recomandări |

Ce **nu** exista: un motiv pentru care un film ar trebui să existe, o structură de poveste, o
recenzie înainte de bani, o biblie vizuală și un pachet de prompt per cadru.

## CE S-A REFOLOSIT

Nu există un al doilea sistem de cercetare, de scoring, de verificare sau de aprobare. Totul
intră în ce era:

- `propose_topics` rămâne singurul generator de idei; a primit o teză și dimensiuni noi.
- `agent_write_script` rămâne singurul scenarist; a primit structura de poveste și o rescriere
  ghidată de recenzie.
- `generate_script_draft` și poarta factuală rămân neschimbate ca logică; păstrează în plus
  povestea.
- Recenzia de poveste rulează pe **Directoare**, agentul care deja aproba filmul finit, și
  folosește `run_agent_task`, `post_message` și `append_event`.
- Prompturile sunt scrise de **VideoEditor**, stewardul care deja citea paginile vendorilor
  despre modelele video.
- `visual_prompt` rămâne câmpul trimis modelului, compus din pachet — deci randarea,
  contabilitatea și controlul de calitate nu s-au atins.
- Lecțiile de prompt stau în `memory_record` (clasa STRATEGY), memoria studioului, nu într-un
  tabel nou.
- Comparația predicție/măsurătoare folosește `AnalyticsSnapshot` existent.

## CE S-A MODIFICAT

- `backend/migrations/versions/0032_editorial_intelligence.py` — `topic_idea.thesis_json` și
  `rejection_reasons_json`, `script_draft.story_json`, `storyboard.visual_bible_json`,
  `storyboard_scene.prompt_json` și `story_purpose`, tabelul `story_review`.
- `backend/app/factual/editorial.py` — **nou**: ponderile și pragurile ideilor, regulile de
  respingere, rolurile scenelor, ritmul narațiunii, verificările de poveste.
- `backend/app/factual/story_review.py` — **nou**: recenzia înainte de producție, simularea
  reținerii, poarta `story_gate`.
- `backend/app/media/prompt_agent.py` — **nou**: biblia vizuală, pachetul de prompt per cadru,
  compunerea promptului, pachetul de producție, lecțiile de prompt.
- `research/agent.py` — teza, cele douăsprezece dimensiuni, respingerea editorială păstrată.
- `factual/agent_pipeline.py` — briefing de poveste, scopul fiecărei scene, rescrierea cu note.
- `runbook/stages.py` — ziua scrie, citește povestea, rescrie o dată, descrie cadrele, și
  **nu randează** un film care n-a trecut recenzia.
- `media/router.py`, `factual/router.py`, `analytics/router.py` — endpointuri pentru recenzie,
  prompturi, pachet de producție și comparația predicție/măsurătoare.
- `agents/editorial.py` — nota Directoarei despre imagine devine lecție de prompt.
- `analytics/services.py`, `runbook/weekly.py` — `story_performance`, citit în revizia
  săptămânală.
- `config.py` — `STUDIO_TARGET_VIDEO_SECONDS` (30).
- `frontend/` — verdictul recenziei pe cardul scenariului, cu curba de reținere, și „De ce
  acest film" sub fiecare storyboard.

## CUM SE DESCOPERĂ TEMELE

Neschimbat în esență: Lead Researcher-ul propune, numai de pe gazde autorizate **și** testate,
cu deduplicare față de ultimele 40 de titluri, având în față trendurile țării și ce a măsurat
bine sau prost pe canalele studioului. Un trend e un cârlig, nu o sursă: se folosește doar
unde paginile autorizate pot dovedi. Studioul descarcă el paginile; o adresă inventată nu se
rezolvă.

Nou: fiecare candidat trebuie să vină cu o **teză** — faptul, de ce contează, de ce acum,
răsplata, cârligul, finalul, îndemnul și felul lui, potrivirea cu canalul, ce se vede, riscul
și lungimea așteptată. Briefingul dă și exemple: „James Webb a descoperit ceva interesant" nu
e o idee; „un exoplanet nou e neobișnuit, iar filmul se închide dezvăluind caracteristica
pentru care astronomii țin la el" este.

## CUM SE PUNCTEAZĂ IDEILE

Douăsprezece dimensiuni, **ponderate, nu mediate** (`IDEA_WEIGHTS`):

| Dimensiune | Pondere | Dimensiune | Pondere |
| --- | --- | --- | --- |
| hook_potential | 0,14 | channel_fit | 0,07 |
| payoff_strength | 0,14 | visual_potential | 0,06 |
| story_potential | 0,13 | originality | 0,05 |
| fact_confidence | 0,13 | shareability | 0,04 |
| curiosity | 0,10 | cta_opportunity | 0,03 |
| retention_potential | 0,09 | production_feasibility | 0,02 |

Media egală de dinainte era exact problema: un subiect frumos și gol câștiga. Acum cârligul,
răsplata, povestea și încrederea factuală decid. Numele vechi (interest, credibility, novelty,
cost) sunt citite în continuare și mapate, ca un răspuns în forma veche să fie punctat pe ce a
spus, nu aruncat.

## CUM SE RESPING IDEILE

Determinist, înainte să fie întrebat cineva (`idea_rejections`):

- nu are răspuns la „de ce contează", „cu ce rămâne spectatorul", „ce îl ține în primele trei
  secunde", „care e faptul", „cum se închide";
- nu are un îndemn care ține de povestea asta, sau are unul generic („like and subscribe");
- e sub pragul unei dimensiuni critice: hook 0,45, payoff 0,45, poveste 0,40, fapte 0,55;
- are scorul compozit sub 0,50;
- lungimea propusă nu e de short (sub 12s sau peste 90s);
- **finalul nu răspunde la ce promite cârligul** (niciun cuvânt de conținut comun) — momeala
  e singurul lucru mai rău decât un cârlig slab.

Ideea respinsă **nu se aruncă**: se păstrează cu statusul REJECTED, teza și motivele, ca
studioul (și Owner-ul) să poată vedea ce a refuzat și de ce.

## CUM FUNCȚIONEAZĂ VERIFICAREA FAPTELOR

Neschimbată, și e coloana vertebrală: un agent extrage afirmații din pagina descărcată, un
**alt** agent le verifică găsind dovada verbatim în text, iar `evaluate_factual_gate` blochează
orice scenariu care citează o afirmație care nu e SUPPORTED. Scenaristul primește numai
afirmații SUPPORTED și fiecare scenă trebuie să citeze identificatori din listă; unul inventat
respinge tot scenariul. Recenzia de poveste refuză (REJECT, nu REVISE) un scenariu în care o
scenă nu se sprijină pe nicio afirmație — aia nu e o problemă de scris, e o problemă de dovezi.

## CUM SE CONSTRUIEȘTE POVESTEA

Scenaristul primește acum o structură-ghid (0-3s cârlig, 3-8s context, 8-18s dezvoltare,
18-26s răsplată, 26-30s final plus îndemn), regula de progresie cauzală („pentru că", „dar",
„până" — nu „and then"), interdicția deschiderilor goale, cerința ca fiecare scenă să declare
rolul (HOOK, SETUP, DEVELOPMENT, EVIDENCE, REVEAL, PAYOFF, ENDING, CTA), regula „arată
informația, nu o repeta în imagine" și **un buget de cuvinte**: la 2,6 cuvinte pe secundă, 30
de secunde sunt cam 78 de cuvinte pentru tot filmul.

Scenariul păstrează povestea în `story_json`: mesajul unic, ce rămâne spectatorului, cârligul,
finalul, îndemnul și felul lui, structura și durata estimată.

## CUM SE EVALUEAZĂ REȚINEREA ÎNAINTE DE PRODUCȚIE

Două straturi, separate intenționat (`story_review.py`):

1. **Verificările se calculează**, fără model și fără cost: are cârlig, cârligul nu e generic,
   fiecare scenă are rol și atribuire, există o răsplată în a doua jumătate, există final,
   finalul răspunde la cârlig, există un singur mesaj, progresia e cauzală, îndemnul ține de
   poveste și are un fel, titlul promite ce livrează, durata e realistă.
2. **Judecata e a Directoarei**: citește scenariul ca un spectator pe telefon și spune câți
   spectatori se așteaptă să mai fie acolo la 0, 3, 5, 10, 15, 20, 25 de secunde și la final,
   unde se pierde interesul și ce să se schimbe.

Verdictul: PASS, REVISE (se rescrie **o dată**, cu notele) sau REJECT (probleme de dovezi, sau
a treia încercare pe aceleași dovezi). Gustul poate fi mai strict decât regula, niciodată mai
permisiv: Directoarea poate trimite înapoi un scenariu care a trecut verificările, dar nu
poate aproba unul care le-a picat. Fără model, verificările decid singure.

## CUM SE ALEGE ÎNDEMNUL

Îndemnul e parte din poveste, nu reclamă lipită la final. Scenaristul îl scrie împreună cu
felul lui (CURIOSITY, DECISION, KNOWLEDGE, DEBATE, FOLLOW, SERIES, COMMENT), iar verificarea
cere două lucruri: să nu fie generic și să aibă cel puțin un cuvânt de conținut comun cu
narațiunea filmului. Felul e înregistrat ca să se poată vedea mai târziu care fel a adus
comentarii — în loc să se lipească aceeași frază pe fiecare film.

## CUM AJUNGE SCENARIUL ÎN PRODUCȚIE

```
CERCETARE → IDEE (teză + scor) → reguli editoriale → VERIFICARE FACTUALĂ →
SELECȚIA DIRECTOAREI → SCENARIU (poartă factuală) → RECENZIA POVEȘTII →
[rescriere o dată] → APROBAREA OWNER-ULUI → STORYBOARD →
BIBLIE VIZUALĂ + PROMPT PER CADRU → RANDARE → QC → VIZIONAREA DIRECTOAREI → PUBLICARE
```

Poarta e la bani, nu la text: `story_gate` refuză atât **agentul de prompt** (pasul dinaintea
generării) cât și **randarea**, în runbook și prin API. Un film a cărui poveste n-a fost citită
nu se descrie și nu se randează, iar ziua raportează de ce. Aprobarea scenariului rămâne a
Owner-ului, iar vizionarea finală rămâne a Directoarei.

## CUM SE CREEAZĂ BIBLIA VIZUALĂ

O singură dată pentru tot filmul, înainte de orice cadru: stil și nivel de realism, perioadă,
lume, paletă, cum se comportă lumina, limbajul camerei, vremea, regulile de continuitate (ce
rămâne identic de la cadru la cadru) și ce nu trebuie să apară niciodată. Se stochează pe
`storyboard.visual_bible_json`, iar fiecare cadru o moștenește. Fără model, biblia se compune
din câmpurile filmului plus regulile implicite ale studioului — un film consecvent, nu un set
de cadre fără legătură.

La lista de excluderi a filmului se adaugă mereu ce studioul refuză oricum: text pe ecran,
mâini deformate, piele de plastic, aspect de desen animat când se cere realism, mișcare de
cameră nemotivată, haine sau vreme care se schimbă fără motiv, fețe care se topesc, watermark.

## CUM SE GENEREAZĂ PROMPTURILE

Un pachet complet per cadru: subiect, acțiune (descrisă ca mișcare, nu ca etichetă — nu „merge"
ci „merge repede spre cameră, uitându-se peste umăr, paltonul tras de vânt"), mediu, cameră
(mărime, unghi, caracter de obiectiv, mișcare — și mișcare doar când povestea o cere), lumină
cu direcție și temperatură, compoziție pentru cadru vertical, mișcare și cum răspunde lumea,
emoție la intensitate credibilă, viață în fundal care nu concurează subiectul, continuitatea cu
cadrul anterior, ce rămâne în ultimul cadru, intenția audio, tranziția și excluderile.

Trei reguli care nu se negociază:

1. **Nu inventează fapte.** O cifră care nu apare în narațiune sau în afirmații e tăiată din
   prompt înainte de trimitere — o imagine face o cifră să pară documentată, iar studioul ar
   publica-o ca fapt. (Obiective și rapoarte de aspect nu sunt cifre factuale: „35mm" și „9:16"
   trec.)
2. **Nu face filmul mai spectaculos decât povestea.** Un ultim mesaj de la o navă care moare nu
   capătă explozii și extratereștri.
3. **Nu e mai lung decât trebuie.** Maximum 1 400 de caractere de prompt compus; detaliat nu
   înseamnă verbos, iar o mie de cuvinte fără conținut îngroapă exact câmpurile care contează.

Ce lipsește din răspunsul modelului se completează din biblie sau din linia scenaristului, și
se notează că a lipsit — un cadru fără lumină e un cadru a cărui lumină o inventează modelul.

## CUM SE GARANTEAZĂ CONTINUITATEA

- **Personaj:** biblia de personaj existentă (`CharacterBible`) intră în prompt cu fața, părul
  și hainele, în fiecare cadru unde apare, plus regula „nu schimba paltonul" din
  `forbidden_deviations`. Blocajele de identitate rămân cele existente.
- **Mediu și vreme:** lumea și vremea stau în biblie, deci sunt aceleași în toate cadrele; a
  doua scenă nu devine o după-amiază însorită.
- **Lumină și cameră:** declarate explicit pe fiecare cadru, moștenite din biblie când cadrul
  nu le spune.
- **Între cadre:** fiecare pachet primește ca `continuity` intenția ultimului cadru din cadrul
  precedent, iar în producție primul cadru al clipului este imaginea aprobată de Directoare.
- **La montaj:** dizolvările și offset-urile existente, neschimbate.

## CUM DIFERĂ TEST DE PRODUCȚIE

Promptul e **identic**. Agentul de prompt nu primește niciodată mediul ca parametru — un test
verificat de `inspect.signature` în suita de teste — și pachetul se scrie o singură dată, din
poveste. Ce se schimbă e doar modelul cumpărat: în TEST cel mai ieftin compatibil, cu plafoane
per generare și per secundă și doar minimul de scene; în PRODUCȚIE cel mai ieftin model care
atinge calitatea cerută de rolul scenei. „Mediu de test, deci prompt scurt" — nu. Un prompt bun
se poate testa ieftin.

## CUM ÎMBUNĂTĂȚEȘTE ANALITICA POVEȘTILE VIITOARE

Două bucle, amândouă pe date reale:

1. **Lecții de prompt.** Nota Directoarei pentru VideoEditor, după ce a văzut filmul, devine o
   lecție în memoria studioului, iar agentul de prompt o primește în briefing la filmul
   următor. Dacă o formulare produce constant o mișcare de cameră greșită, asta e un fapt
   despre modelul vendorului.
2. **Predicție față de măsurătoare.** `story_performance` pune, per film publicat, ce a prezis
   studioul (cârlig, reținere, șansa de comentariu) lângă ce s-a măsurat (procentul mediu
   vizionat, CTR, comentarii și share-uri raportate la vizualizări), și raportează diferența.
   O diferență peste 20 de puncte înseamnă că judecata editorială e sistematic optimistă.
   Revizia săptămânală o citește; nu se optimizează orbește pentru vizualizări.

## REZULTATELE TESTELOR

`uv run pytest -q` — **645 trecute, 1 sărit** (Ollama real, neconfigurat). `ruff check`,
`ruff format --check`, `mypy` curate. `npm test` 86 trecute, `npm run check` și `npm run build`
curate. `scripts/check_docs.py` verificat.

Cele 21 de verificări cerute sunt în `tests/test_editorial_quality.py`, toate locale, cu model
scriptat, fără vendor și fără generare: ideea fără răsplată respinsă și păstrată cu motivul;
ideea fără dovezi nu ajunge la scenariu; imaginile frumoase singure nu aprobă o poveste slabă;
scenariul are cârlig, progresie, răsplată și final; îndemnul ține de poveste; narațiunea
încape în durată; fiecare scenă își declară rolul; agentul de prompt primește doar povești
trecute; nu inventează cifre; scrie pachete detaliate; personajul arată la fel în toate
cadrele; lumea se ține; lumina și camera sunt decise; imaginea servește narațiunea; pachetul e
identic în ambele medii iar rutarea rămâne cea existentă; sursele rămân atașate filmului;
lecțiile de prompt ajung la promptul următor; aprobarea Directoarei încă decide; pagina și
backendul spun același lucru.

**Două defecte reale găsite de aceste teste, în timpul scrierii lor:** agentul de prompt nu
verifica poarta poveștii (acum o verifică și refuză), și o a doua rulare a prompturilor își
citea propriul output ca „linia scenaristului", deci filmul se depărta la fiecare pas de ce
cerea scenariul (acum citește linia din scenariu, deci e idempotent).

## LIMITE CARE RĂMÂN

1. **Continuitatea e garantată în text, nu în imagine.** Biblia, personajul repetat și cadrul
   întâi impun consecvența în instrucțiuni; nimic nu compară două cadre generate ca să vadă
   dacă persoana arată la fel. Singura verificare vizuală rămâne vizionarea Directoarei, după
   randare.
2. **Garda „fără fapte inventate" prinde doar cifre.** O afirmație calitativă inventată într-o
   descriere de imagine („mulțimea se revoltă") nu e detectabilă așa.
3. **Ritmul e o constantă, nu o măsurătoare per voce.** 2,6 cuvinte pe secundă; durata reală a
   narațiunii se măsoară abia la randare, când vocea a fost sintetizată.
4. **Curba de reținere e o estimare, nu o măsurătoare.** Comparația cu realitatea are nevoie de
   filme publicate și măsurate; studioul nu are încă niciunul.
5. **Pragurile ideilor sunt numerele studioului, nu învățate.** Nimic nu le ajustează din
   rezultate reale; asta ar cere zeci de filme măsurate.
6. **Verificările „finalul răspunde la cârlig" și „îndemnul ține de poveste" merg pe cuvinte
   comune.** Un final scris cu sinonime ar fi trimis înapoi degeaba.
7. **Personajele nu sunt atribuite automat scenelor.** Biblia de personaj intră în prompt doar
   unde scena numește un personaj; scenaristul nu face încă atribuirea.
8. **Recenzia depinde de un model pentru partea de gust.** Fără model de limbaj, verificările
   calculate decid singure — corect, dar mai sărac.
