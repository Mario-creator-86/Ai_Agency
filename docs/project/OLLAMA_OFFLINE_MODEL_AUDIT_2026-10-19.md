# Ollama: evaluare fără generări plătite — 19 octombrie 2026

Stare operațională la redactare: oprire controlată cerută; se așteaptă încheierea apelului deja pornit. Serverul nu trebuie repornit fără o cerere nouă a utilizatorului. Confirmarea opririi se înregistrează separat în acest raport.

## Recomandarea pentru problema actuală

**Mistral Large 4 este candidatul meu provizoriu pentru rescrierile lui Kael**, pe baza eficienței observate în răspunsurile istorice ale studioului. Nu este demonstrat drept cel mai bun model ca precizie pe contractul actual v8: istoricul lui folosește v3–v6, iar GLM a lucrat ulterior pe v6–v8. Nu am schimbat alocarea niciunui agent.

Recomandarea se referă la rescrierea unui prompt de scenă, nu la înlocuirea tuturor modelelor agenției. Pentru Sarah, istoricul DeepSeek-v4.1-flash la `director_rewrite_review` și `director_scene_brief` este mult mai relevant decât un clasament general de coding. Pentru verificarea cadrelor trebuie păstrată capacitatea de vedere; GPT-OSS este candidat pentru text, nu pentru înlocuirea unui evaluator vizual. [Catalogul oficial](https://ollama.com/search?c=cloud), [GPT-OSS](https://ollama.com/library/gpt-oss).

**Gemma 4 este candidatul economic secundar**, cu text și vedere și tarif mai mic. Nu există în eșantionul nostru o evaluare a lui pe rescrierile reale. Nu îl declar câștigător pe baza tarifului sau a benchmarkurilor generale. [Gemma 4](https://ollama.com/library/gemma4).

**GPT-OSS:120b** merită păstrat ca alternativă economică pentru text structurat; lipsesc însă rescrieri Kael comparabile în eșantion. Nu garantează automat răspunsuri fără epuizarea raționamentului. **Mistral Large 3** are JSON și vedere și nu este etichetat ca model de thinking în catalog; este o alternativă documentată, dar fără rezultate noi măsurate aici. [Mistral Large 3](https://ollama.com/library/mistral-large-3).

Nu recomand revenirea la GLM-5.3-flash pentru această corecție doar prin creșterea limitei: cele trei răspunsuri goale au consumat fiecare 65.536 de tokeni de ieșire, iar configurația nu trimitea un plafon artificial mic. Modelul primea limita nativă a furnizorului. Cererile cu răspunsuri valide nu au dispărut la parsare în reconstituirea locală.

## Ce s-a verificat fără cost de inferență

- Zero apeluri noi de generare către Ollama, Runpod sau alți furnizori.
- Doar pagini publice oficiale pentru catalog, prețuri și capabilități.
- Baza reală citită cu SQLite `mode=ro` și `query_only`; nicio modificare a cozii, a prompturilor sau a aprobărilor.
- Istoric de producție de la 16 octombrie 2026, ora 12:00 UTC, până la data din `audit.json`.
- Reconstituirea a 21 de răspunsuri reale GLM v8: toate cele 21 trec din nou schema actuală a câmpurilor finale. Aceasta verifică forma, nu fidelitatea viitoare a clipului și nici aprobarea semantică a lui Sarah.
- 51 de teste locale trecute: contractul Cloud nativ, citirea streamului, răspunsul gol, schema finală, validarea structurată, calculul prețurilor și reconstituirea răspunsurilor salvate.
- La teste, conexiunile către API-uri sunt blocate. Singura conexiune internă permisă este construirea `socketpair` necesară buclei asyncio pe Windows. Prima gardă prea strictă a blocat și acest mecanism local; a fost corectată în harness, fără schimbări în aplicație.

Acestea sunt teste de software și analiză a datelor existente. Nu sunt teste comparative noi ale inteligenței modelelor. Un model pe care nu l-am apelat nu poate primi aici un scor de calitate inventat.

## Modele și prețuri publice

USD per un milion de tokeni. Tarifele sunt un instantaneu al paginii publice din 19 octombrie; nu modifică registrul de prețuri al studioului. Catalogul enumeră 20 de familii Cloud, cu două dimensiuni GPT-OSS. Disponibilitatea publică nu înseamnă verificarea accesului în contul utilizatorului. [Catalog](https://ollama.com/search?c=cloud), [prețuri](https://ollama.com/pricing).

| Model | Intrare | Intrare din cache | Ieșire |
|---|---:|---:|---:|
| deepseek-v4.1-flash | 0.30 | 0.006 | 1.20 |
| deepseek-v4-pro | 1.32 | 0.044 | 3.96 |
| gemma4 | 0.14 | 0.05 | 0.40 |
| glm-5.3 | 1.40 | 0.26 | 4.40 |
| glm-5.3-flash | 0.15 | 0.03 | 0.50 |
| glm-5.2 | 1.40 | 0.26 | 4.40 |
| gpt-oss:120b | 0.15 | 0.014 | 0.60 |
| gpt-oss:20b | 0.07 | 0.035 | 0.30 |
| kimi-k3 | 3.00 | 0.30 | 15.00 |
| kimi-k2.7-code | 0.95 | 0.19 | 4.00 |
| kimi-k2.6 | 0.95 | 0.16 | 4.00 |
| minimax-m3 | 0.60 | 0.12 | 2.40 |
| minimax-m2.7 | 0.30 | 0.06 | 1.20 |
| mistral-large-4 | 0.68 | 0.07 | 2.09 |
| mistral-large-3 | 0.50 | nepublicat | 1.50 |
| muse-spark-open | 1.25 | 0.15 | 4.25 |
| nemotron-3-nano | 0.06 | nepublicat | 0.24 |
| nemotron-3-super | 0.015 | 0.015 | 0.60 |
| nemotron-3-ultra | 0.10 | 0.10 | 3.00 |
| beam | nepublicat în tabel | nepublicat | nepublicat |
| clef | 0.24 | nepublicat | nepublicat |

Beam este listat în catalog, dar lipsește din tabelul de prețuri consultat: nu îi atribui un tarif. Clef este prezentat ca model de decizie pe o schemă de întrebări; nu îl tratez drept înlocuitor direct al scriitorului de prompturi. [Catalog oficial](https://ollama.com/search?c=cloud).

Doar DeepSeek-v4.1-flash și DeepSeek-v4-pro au în tabel tarife reduse la jumătate în afara intervalului 12:00–18:00 UTC în zilele lucrătoare și în weekend. Intrarea din cache nu este presupusă pentru un apel nou. Costurile scenariilor de mai jos folosesc tariful integral, fără cache. [Regula tarifară](https://ollama.com/pricing).

Planurile publice sunt Free cu credite la consum, Pro 20 USD/lună cu 60 USD credite, Max 100 USD/lună cu 300 USD credite și Team 500 USD/lună cu 1.000 USD credite. Nu am verificat sau schimbat abonamentul acestui cont. [Planuri](https://ollama.com/pricing).

## Costul unei sarcini scurte, nu doar tariful per token

Scenariu aritmetic: 10.000 tokeni de intrare și 1.000 de ieșire, fără cache, la tarif integral. Numerele nu reprezintă răspunsuri generate sau promisiuni de calitate.

| Model | USD / scenariu |
|---|---:|
| nemotron-3-super | 0.000750 |
| gpt-oss:20b | 0.001000 |
| gemma4 | 0.001800 |
| glm-5.3-flash | 0.002000 |
| gpt-oss:120b | 0.002100 |
| deepseek-v4.1-flash | 0.004200 |
| mistral-large-3 | 0.006500 |
| mistral-large-4 | 0.008890 |

Un apel GLM cu aceeași intrare, dar 65.536 de tokeni de ieșire și niciun răspuns utilizabil, ajunge aritmetic la 0,034268 USD. Tariful mic per token nu face economică o sarcină care consumă zeci de mii de tokeni fără să producă rezultatul cerut. Nu extrapolez acest scenariu la factura reală sau la valoarea creditelor din abonament. [Tarife](https://ollama.com/pricing).

## Istoricul real, reanalizat local

`SUCCEEDED` înseamnă că apelul a returnat text utilizabil transportului; nu garantează că schema, revizia lui Sarah sau verificarea video au trecut. Durata mediană privește apelurile cu răspuns. Costul mediu este recalculat la tarifele publice actuale, fără cache, doar pentru rândurile cu ambii contori disponibili. Rândurile fără contori nu sunt considerate gratuite.

| Model | Sarcină | Apeluri | Stări | Mediană răspuns, secunde | Ieșire medie, tokeni | USD mediu recalculat |
|---|---|---:|---|---:|---:|---:|
| deepseek-v4.1-flash | director_rewrite_review | 297 | SUCCEEDED: 297 | 4.221 | 829.222 | 0.003378 |
| deepseek-v4.1-flash | director_scene_brief | 74 | SUCCEEDED: 74 | 4.995 | 769.716 | 0.004441 |
| glm-5.3-flash | scene_prompt_rewrite | 146 | SUCCEEDED: 137, ABANDONED: 1, FAILED: 4, EMPTY_OUTPUT: 3, RUNNING: 1 | 189.236 | 39805.788 | 0.021449 |
| mistral-large-4 | scene_prompt_rewrite | 212 | SUCCEEDED: 212 | 8.344 | 778.377 | 0.008436 |

Pe rescrieri, Mistral Large 4 are 212/212 obiecte JSON extrase de parser, unele în blocuri Markdown; GLM are 137/137 între apelurile cu răspuns. Faptul că un răspuns nu este JSON literal fără bloc Markdown nu reprezintă o eroare: parserul aplicației acceptă acest ambalaj.

Evenimentele legate explicit de rescriere arată doar un subeșantion: Mistral are 11 evenimente legate, dintre care 3 cu salvare/TREATS; GLM are 60, dintre care 48 cu salvare/TREATS. Sunt versiuni și cerințe diferite, iar evenimentele lipsesc pentru multe apeluri vechi. **Nu folosesc aceste fracții ca rată comparabilă de calitate și nu susțin că 212 apeluri returnate înseamnă 212 rescrieri acceptate.**

Pe eșantionul cu contori disponibili, media recalculată este aproximativ 0,00844 USD/rescriere Mistral versus 0,02145 USD/rescriere GLM. Acest avantaj observat de eficiență susține candidatura Mistral, fără să demonstreze superioritatea calității în contractul v8.

## Localizarea erorii și limitele concluziei

Cele trei apeluri GLM au ieșire goală și sfârșit la limita de generare. Reconstituirea parserului confirmă că el păstrează toate fragmentele vizibile ale răspunsului și separă câmpul `thinking`. Nu promovează procesarea internă la statut de răspuns valid. [Contractul Ollama](https://docs.ollama.com/api/generate), [thinking](https://docs.ollama.com/capabilities/thinking).

Datele nu separă definitiv un comportament al modelului declanșat de această cerere de o problemă a serviciului. Nu am acces la implementarea internă a furnizorului și nu am efectuat apeluri noi. Schimbarea candidatului poate reduce riscul, dar nu demonstrează cauza internă și nu garantează fidelitatea clipurilor video.

## Ce rămâne de făcut înainte de orice activare

1. Păstrarea serverului oprit, conform cererii utilizatorului.
2. Alegerea explicită a candidatului pentru Kael; nu înlocuirea în bloc a evaluatorilor vizuali cu modele numai text.
3. Dacă se autorizează ulterior o schimbare, folosirea căii normale de configurare a agentului și păstrarea limitei de două randări, bugetelor, reviziei lui Sarah și cozii automate. Nicio rescriere sau aprobare manuală a scenelor.
4. O comparație reală pe aceleași scene, cu criterii de calitate înghețate, ar necesita răspunsuri noi ale modelelor și implicit cereri pe care această sarcină le interzice. În această evaluare, acel pas rămâne neexecutat.

Fișiere de dovadă: `output/ollama-offline-model-audit-2026-10-19/audit.json`, `catalog.json`, `tests.xml`, `audit.py`, `test_offline_audit.py`, `run_tests.py`. Nicio cheie sau urmă de raționament intern nu este exportată.
