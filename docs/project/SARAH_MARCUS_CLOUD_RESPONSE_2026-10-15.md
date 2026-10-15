# Sarah și Marcus: refuz Cloud și apel expirat — 15.10.2026

## Corecție importantă verificată live — nu reintroduce -1

Owner a semnalat regresia. Codex a introdus inițial `num_predict=-1`, extrapolând documentația locală Ollama la Cloud. Aceasta a fost o eroare de implementare: validarea live Cloud cere un număr pozitiv. Traseul final **omite `num_predict`** când se folosește allowance-ul nativ; nu trimite -1 și nu inventează o limită. Inputul rămâne complet, iar testele explicit mici de adapter rămân bounded.

Trei probe tehnice scurte, autorizate anterior de Owner și înregistrate cu rezumat `Test izolat Codex`, confirmă: cererea fără parametrul artificial a răspuns `OK` (18 tokeni intrare, 2 ieșire, cost_vr 0.00001, rulare a52d260d); `-1` este respins pentru că trebuie să fie pozitiv (8df5219a); 480000 este respins fiind peste **393216**, maximul declarat de acest model în răspunsul API (172d43e8). Refuzurile au cost/tokens necunoscuți, nu sunt marcate cu cost zero. Aceste probe nu reprezintă progres de film și nu demonstrează reușita revizuirii complete cu inboxul mare. Nu s-a apelat GPU.

Codex a reîncărcat backendul după constatarea absenței apelurilor RUNNING: procesul vechi verificat 11580 a fost oprit, noul proces 15596 a pornit aceeași intrare `scripts/run.py`, fără fereastră. Politicile, modelele atribuite, conturile, scenele și verdictele nu au fost editate. Endpointurile live/ready sunt 200. Schimbările de parametri și probele sunt oprite la obiecția Ownerului. Costul și ID-urile sunt în proof JSON.

Ultimele 40 teste de contract/context/conexiuni au trecut după eliminarea lui -1. Suitele 153+1 omis și verificările anterioare sunt dovezi locale, nu dovadă pentru parametrul -1 abandonat. Varianta finală testată omite parametrul.


## Ce s-a întâmplat în aplicația reală

Sarah, `director_review`, rularea `f3e5b084-9ccc-4647-9157-10804cfcdfaf`: la 00:21:59–00:22:00 București, modelul efectiv deepseek-v4.1-flash a primit o cerere și a răspuns HTTP 400. Nu a decis cele 10 rapoarte. Parametrul de răspuns era 24.000 × 2 × 10 = **480.000 tokeni**, nu dimensiunea mesajelor. Contextul de identitate avea 1.671.361 caractere, iar obiectivul 21.940. Integrarea veche arunca textul refuzului, deci nu avem dovada exactă a parametrului refuzat. Plafonul supradimensionat este o anomalie concretă corectată; nu inventăm retrospectiv motivul furnizorului și nu deducem că cheia este greșită din HTTP 400.

Marcus, `write_episode`, rularea `1e6bc6f4-7e80-4463-83cc-951e543af89f`: glm-5.3-flash, 00:11:49–00:21:50 București, ProviderUnreachable. Jurnalul local conține TimeoutError. Apelul fără streaming a așteptat aproximativ 600 secunde pentru răspunsul complet. Identitatea avea 646.701 caractere, obiectivul 20.897, parametrul răspunsului 72.000 tokeni. Nu dovedește că modelul a terminat sau că nu a facturat. Agenția a început un alt apel de episod `faf07b36-b6bd-475d-a3db-3859ba8b19ca`, expirat și el la 00:32:01 București, înainte de repornire. Adapterul nu retrimite automat o cerere trimisă și rămasă fără răspuns; repetarea sarcinii la nivelul zilei este distinctă.

Citirea autentificată `/api/show` declară 1.048.576 tokeni de context pentru ambele modele. Acesta este contextul, nu o promisiune că ambele acceptă 480.000 tokeni de ieșire. Nu s-a apelat generarea. Dovada publică locală: `SARAH_MARCUS_CLOUD_RESPONSE_PROOF_2026-10-15.json`.

## Modificări

- În `agents/services.py`, rulările agenților pe conexiunea Ollama Cloud folosesc ieșirea nativă a furnizorului, nu produsul multiplicatorilor ca limită arbitrară. Manifestul păstrează allowance-ul cerut și marchează `effective_max_tokens=null`, `output_limit_source=provider_native`. Politica și bugetul zilnic se verifică în continuare înaintea apelului. Nu se schimbă modelul angajatului și nu se taie obiectivul sau identitatea.
- În `integrations/llm.py`, cererea Cloud folosește streaming și omiterea `num_predict` când serviciul agenților cere limita nativă. Documentația locală pentru -1 nu este aplicabilă validării Cloud; limita reală a furnizorului rămâne. Testele explicite mici de conexiune și modelele locale își păstrează limitele explicite.
- Fluxul NDJSON concatenează toate fragmentele vizibile, păstrează numărătoarea tokenilor din încheiere și numai lungimea raționamentului privat. Timeout-ul de socket devine așteptare de activitate între fragmente, nu așteptarea unui corp complet până la sfârșit. Nu se declară succes fără `done=true`; `done_reason=length` rămâne incomplet. Sfârșitul prematur și timeout-ul după trimitere rămân nereîncercabile în adapter. Limita de siguranță este per linie, nu un plafon de 4 MB pe întregul răspuns; peste 4 MB în fragmente nu se taie.
- Refuzurile HTTP sunt citite limitat pentru clasificare, fără a salva sau a afișa textul furnizorului. Numai categorii tehnice fixe OUTPUT_LIMIT, CONTEXT_LIMIT, UNSUPPORTED_THINKING ajung în diagnostic; fără chei, URL-uri ori citate din cerere. Când cauza nu poate fi clasificată, mesajul spune sincer că motivul exact nu este disponibil.

Fișiere: `backend/app/agents/services.py`, `backend/app/integrations/llm.py`, `tests/test_cloud_response_contract.py`.

## Verificări și limite

- 9 regresii noi pentru cerere Cloud nativă, text complet, streaming, terminare prematură, timeout fără resend, categorii sigure de HTTP 400, test mic explicit și răspuns agregat peste 4 MB.
- 45 teste inițiale pentru contract/context/erori/conexiuni: PASS; apoi 153 teste pentru provider retries, Ollama, integrare și runbook: PASS, 1 test real Ollama omis fiind neconfigurat. 18 verificări finale suprapuse (9 Cloud + 9 garderobă/referințe): PASS.
- Ruff PASS; mypy pe 3 module modificate cu imports silent PASS. Verificarea completă cu imports a găsit erori preexistente în alte module; eroarea nouă din services a fost corectată. Documente normative și git diff --check PASS.
- Nu s-au făcut generări LLM/GPU de test, nu s-au schimbat datele de producție ori verdicte. Cod local/necomis. Backendul a fost repornit extern între timp: procesul 11580 a pornit la 21:35:29 UTC, după salvarea tuturor fișierelor modificate; /health/live și /health/ready au răspuns 200. Codex nu a întrerupt sau repornit procesul. Codul nou este încărcat; nu avem încă o revizuire live reușită cu noul traseu.

Referințe primare: [Ollama num_predict și parametrul -1](https://docs.ollama.com/modelfile), [API generate](https://docs.ollama.com/api/generate), [modelul Sarah](https://ollama.com/library/deepseek-v4.1-flash), [modelul Marcus](https://ollama.com/library/glm-5.3-flash).
