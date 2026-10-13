# Trei modele per angajat, și niciun nume de model în logică

Raport cerut de Owner, 2026-09-12. Regula arhitecturală: numele modelelor sunt **configurare**,
nu logică. Modelele se schimbă des; Owner-ul trebuie să poată înlocui oricare din interfață,
fără nicio modificare de cod.

## CE EXISTA DEJA

| Ce | Unde |
| --- | --- |
| Model alocat per agent | `agent.model_id` + `agent.provider_id` → `model_record` |
| Registrul de modele | `ModelRecord`, descoperit din vendor prin `sync_provider_models` |
| Capabilități separate de identitate | `Capability`, `ModelCapability`, `RoleCapability` |
| Integrarea Ollama | `providers/ollama.py`, `ProviderRegistry`, retries și timeout în adaptor |
| Execuția unui agent | `run_agent_task`: identitate, nucleu de politici, `AgentRun`, evenimente |
| Istoricul execuțiilor | `AgentRun.model_name` și `provider_name`, scrise la momentul apelului |
| Comanda Owner-ului | `PUT /settings/agents/{id}/model` → `assign_agent`, versionată |
| UI de configurare | `frontend/src/settings.js`, un card per agent cu select de model |
| Memorie și context | `compose_identity`, `MemoryRecord` |

## CE S-A REFOLOSIT

Nu există un al doilea registru de modele, un al doilea conector, o a doua ecran de
configurare sau un al doilea sistem de execuție. Fiecare apel dintr-o strategie este un
`run_agent_task` obișnuit, cu identitatea, nucleul de politici, `AgentRun`-ul și evenimentele
care existau. Alocarea trece prin `assign_agent`, aceeași comandă versionată. Interfața e
cardul care era deja acolo. Reîncercările, timeout-urile și raportarea erorilor sunt ale
adaptorului existent.

## CE S-A MODIFICAT

- `backend/migrations/versions/0034_agent_multi_llm.py` — sloturile secundar și terțiar,
  strategia, politica, cele două praguri, și tabelul `llm_collaboration`.
- `backend/app/agents/ensemble.py` — **nou**: strategiile, decizia dacă o sarcină merită
  modele suplimentare, rezolvarea numelor pe registru, aplicarea alocării, trasabilitatea.
- `backend/app/agents/services.py` — `run_agent_task` primește `model_id` (rulează pe alt
  slot, cu verificarea capabilităților acelui model); `sync_provider_models` aplică alocarea
  de start după ce studioul află ce modele există.
- `backend/app/integrations/services.py` și `router.py` — comanda salvează cele trei sloturi,
  strategia, politica și pragurile, cu validare.
- `backend/app/agents/command.py` — deciziile strategice ale Directoarei sunt declarate
  `STRATEGIC`, deci configurarea ei decide dacă sunt criticate.
- `backend/app/agents/schemas.py`, `router.py` — pagina citește configurarea reală;
  `GET /agents/{id}/collaborations` o citește înapoi.
- `config/workforce_seed.json` — alocarea cerută, ca fișier editabil.
- `scripts/apply_llm_allocation.py` — aplicarea manuală, cu `--force`.
- `frontend/src/settings.js` — trei select-uri, strategia, politica și pragul, pe același card.

## ALOCAREA CERUTĂ, APLICATĂ

Rulat pe o **copie** a bazei live, cu registrul real:

| Rol | Principal | Strategie | Secundar |
| --- | --- | --- | --- |
| Director | kimi-k3:cloud | REVIEW | nemotron-3-ultra |
| LeadResearcher | minimax-m3 | SINGLE | — |
| FactChecker | qwen3.5:397b | SINGLE | — |
| ScriptWriter | kimi-k3:cloud | SINGLE | — |
| VoiceArtist | mistral-large-3:675b | SINGLE | — |
| VideoEditor | glm-5.3-flash:cloud | SINGLE | — |
| Publisher | nemotron-3-ultra | SINGLE | — |
| Accountant | glm-5.3-flash:cloud | SINGLE | — |

Numele din fișier poartă sufixe de vendor care variază între actualizări
(`nemotron-3-ultra:cloud` în fișier, `nemotron-3-ultra` în registru). Sunt rezolvate pe
registru, nu crezute literal, și un nume care nu se potrivește cu nimic e raportat, nu
inventat.

## CÂND SE FOLOSESC MODELELE SUPLIMENTARE

Niciodată la muncă de rutină. Decizia se ia din configurarea agentului plus importanța
declarată de apelant:

| Politică | Când |
| --- | --- |
| IMPORTANT_ONLY | sarcina atinge pragul `min_importance` (implicit STRATEGIC) |
| LOW_CONFIDENCE | încrederea raportată e sub `min_confidence` (implicit 0,6) |
| ALWAYS | mereu |
| MANUAL | doar când apelantul cere explicit |

Motivul e înregistrat, în cuvinte: „sarcina este STRATEGIC, la sau peste pragul STRATEGIC".
Un motiv se poate audita; „s-a apelat un al doilea model" nu.

## STRATEGIILE

- **SINGLE** — modelul principal, singur. Calea normală.
- **FALLBACK** — principalul; dacă nu răspunde, următorul slot configurat. Dacă niciunul nu
  răspunde, ce primește apelantul e eșecul, nu un răspuns inventat.
- **REVIEW** — principalul răspunde, al doilea caută ce e greșit, principalul decide. Criticul
  primește obiectivul, dovezile relevante și răspunsul, nu toată memoria companiei.
- **DEBATE** — două răspunsuri independente; un al treilea model arbitrează **numai** dacă
  cele două diferă material, și doar dacă e configurat.
- **PARALLEL** — două sau trei modele lucrează aceeași problemă, agentul scrie un răspuns.

Dezacordul material se măsoară pe cuvintele de conținut comune, cu un prag de 0,34. Crud,
ieftin, și imposibil de falsificat scriind mai mult.

## CINE DECIDE

În REVIEW, DEBATE și PARALLEL, răspunsul pe care îl primește apelantul este **mereu** o rulare
pe modelul propriu al angajatului, cu vorbele celorlalte modele în prompt. Un critic nu poate
publica, nu poate comanda un departament și nu poate schimba o strategie, pentru că singurul
lucru pe care îl produce e text pe care îl citește modelul principal. Criticului i se spune
asta explicit: „You are not the decision-maker… do not issue instructions to anyone."

Sarah rămâne autoritatea finală. Oprirea de autonomie a Owner-ului e deasupra tuturor: cu ea
activă, nu se apelează niciun model.

## CE SE ÎNTÂMPLĂ CÂND VERIFICAREA NU SE POATE FACE

Nu se inventează o critică. Colaborarea se închide cu `REVIEW_INCOMPLETE`, răspunsul
angajatului rămâne valabil, iar apelantul e informat — bucla Directoarei coboară încrederea
deciziei la LOW și scrie de ce. O decizie pe care nimeni n-a reușit să o conteste nu e
prezentată ca o decizie contestată.

## TRASABILITATE

Fiecare apel participant e un `AgentRun` obișnuit, cu modelul, statusul, tokenii și ora lui.
`llm_collaboration` le leagă: agentul, sarcina, strategia, importanța, motivul, ce rol a jucat
fiecare model, dacă au fost în dezacord, ce notă s-a păstrat, ce model a dat răspunsul final,
latența și tokenii însumați. Se citește la `GET /agents/{id}/collaborations`.

Istoricul nu se rescrie: schimbarea unui slot azi nu atinge ce a răspuns ieri, pentru că
modelul e scris pe rularea însăși.

## CUM SE ÎNLOCUIEȘTE UN MODEL MÂINE

1. Settings → sincronizează modelele furnizorului.
2. Alege alt model în slotul dorit, alege strategia și politica.
3. Salvează. Versiunea agentului avansează, evenimentul se scrie.
4. Execuțiile următoare folosesc noua configurare. Nicio linie de cod nu se schimbă.

Alocarea din fișier se aplică **o singură dată** per angajat, la prima sincronizare care află
ce modele există, și niciodată peste o alocare existentă: altfel următoarea sincronizare ar
anula în liniște alegerea Owner-ului. Când fișierul e o instrucțiune nouă:

```bash
uv run python scripts/apply_llm_allocation.py --force
```

## REZULTATELE TESTELOR

`uv run pytest -q` — **693 trecute, 1 sărit** (Ollama real, neconfigurat). `ruff`, `mypy`,
`npm test` (86), `npm run check`, `npm run build` și `scripts/check_docs.py` curate.

Cele 22 de verificări cerute sunt în `tests/test_multi_llm.py`, cu modele-paravan numite
`alpha-one`, `beta-two`, `gamma-three` — dacă un test ar trece doar pentru că un nume pare
familiar, testul ar fi greșit. Verificarea cea mai importantă scanează `backend/app` și cade
dacă vreun nume de model din configurare apare în cod, în afara documentației.

Migrarea 0034 se aplică curat pe copia bazei live, iar alocarea cerută se rezolvă complet pe
registrul real. (0034 nu mai este capul lanțului de migrări: `main.py` fixează revizia curentă —
`0038_director_may_approve_episodes` la 2026-09-18 — și `scripts/bootstrap.py` trebuie rulat
înainte de pornire.)

## LIMITE CARE RĂMÂN

1. **Dezacordul se măsoară pe cuvinte, nu pe sens.** Două răspunsuri care spun același lucru
   cu sinonime diferite pot declanșa un arbitru inutil, și două care diferă subtil pot trece
   ca fiind de acord.
2. **Costul colaborării nu intră în registre.** Tokenii sunt însumați pe rândul colaborării,
   dar nu se transformă în cost în lei sau dolari, pentru că Ollama Cloud nu e tarifat per
   apel în books-urile studioului.
3. **`PARALLEL` cere mereu toate modelele configurate.** Nu există încă o regulă care să
   renunțe la al treilea când primele două ajung la același răspuns.
4. **Praguri implicite.** 0,6 pentru încredere, 0,34 pentru suprapunere. Nu sunt învățate din
   rezultate.
5. **Un singur furnizor în practică.** Sloturile pot ține modele de la furnizori diferiți, iar
   codul rezolvă adaptorul per model, dar studioul are azi un singur furnizor configurat, deci
   drumul cu doi furnizori nu a fost exercitat pe date reale.
6. **Nadia interpretează, nu calculează.** Totalurile, soldurile și costurile vin din registre
   și din cod determinist, nu din aritmetica unui model — asta era deja adevărat și rămâne, dar
   nimic din multi-LLM nu o întărește suplimentar.
