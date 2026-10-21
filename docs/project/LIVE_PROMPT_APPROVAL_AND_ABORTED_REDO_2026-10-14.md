# Verificarea prompturilor aprobate și a regenerării anulate — 14.10.2026

## Ce s-a întâmplat efectiv

La **The Zero Script Club**, scena 4, promptul de 1.844 de caractere a ajuns complet și identic la cele două cereri Qwen-Image-2512 din 16:47:24 UTC. Era diferit de vechiul prompt de 954 de caractere. Plafonul vechi nu a tăiat această cerere. Nadia (model efectiv mistral-large-4) a aprobat financiar cererea la noul plafon de film de 20 USD.

Textul avea un verdict anterior Sarah/Kael `TREATS` (eveniment 21758), dar conținea încă fragmente moștenite incomplete: fundalul se termina în „compete with the”, iar ținuta lui Sarah în „sky-blue”, deși contractul personajului cere „sky-blue tie”. Aceste fragmente au fost salvate înaintea eliminării tăierilor. Un verdict vechi nu demonstra că planul era complet.

Sarah declara reutilizarea gratuită a imaginii 7e4ec124, însă acea imagine provenea dintr-un prompt diferit de cel curent. Execuția a trimis de fapt două cereri noi. După oprirea GPU de către Owner, ambele au încheiat fără imagine livrată (`EXPIRED_UNDELIVERED`). Evenimentele 22328–22331 au raportat greșit progres de regenerare cumpărată/în așteptare, în timp ce rezultatul concret era `NOT_BOUGHT`, cu restaurarea variantelor vechi. Jurnalul local indică zero pentru acele cereri; aceasta nu constituie reconcilierea facturii furnizorului.

Dovezi publice curate: `LIVE_PROMPT_APPROVAL_PROOF_2026-10-14.json`. Nu conține chei, URL-uri semnate sau raționament ascuns.

## Corecțiile aplicate

- Verificarea inițială și regenerarea detectează câmpurile incomplete și condițiile de ținută întrerupte. Trimit toate constatările către circuitul existent Sarah → agent de rescriere → verificarea Sarah. Nu completează automat sensul lipsă și nu șterg condițiile.
- Reutilizarea unei aprobări de prompt cere verdictul explicit `TREATS`, plan complet și egalitatea cu textele curente efective. Modificarea textului invalidează aprobarea veche pentru regenerare.
- O imagine propusă drept înlocuire gratuită trebuie să fie acceptată, să existe fizic, să aibă checksum valid și să corespundă identității promptului/referințelor curente. Sarah primește instrucțiuni explicite în `director-qc-v11`.
- Anularea fără livrare, inclusiv restaurarea variantei vechi, nu produce progres fals și nu deschide verificarea unei imagini inexistente. O imagine nouă livrată, dar respinsă de QC, rămâne în circuitul de remediere. Rezultatele încă incerte rămân urmărite; contabilitatea nu este resetată.
- Validarea rescrierii factuale păstrează și câmpurile de peste 500 de caractere, cu regulile semantice existente. Descrierea „cu spatele către cameră” rămâne completă în promptul de mișcare; comenzile de cameră sunt tratate separat.
- Aceste verificări acoperă proiectele viitoare și revalidarea planurilor vechi înainte de o achiziție nouă. Filmele deja publicate nu au fost modificate.

## Fișiere și verificări

Cod: `backend/app/media/prompt_agent.py`, `director_qc.py`, `assembler.py`, `stills_stage.py`, `scene_rewrite.py`, `prepared_batch.py`; `backend/app/runbook/stages.py`; `backend/app/agents/reviews.py`.
Teste: `tests/test_live_prompt_approval.py` (18 regresii), fixture-ul public `tests/fixtures/live_serial_scene4_2026-10-14.json`, teste existente pentru deciziile Directorului, revizuirea regenerării și reluarea achizițiilor. `tools/prepare_prompt_repairs.py` păstrează o propunere completă de fundal; propunerea offline nu reprezintă aprobarea Sarah.

Verificări locale, suite care se suprapun și nu se însumează: **153 teste funcționale trecute** pentru traseul Director/QC/rescriere/relansare; **103 teste funcționale trecute** pentru loturi și context complet; verificarea finală de **38 teste trecute** include limitele financiare, loturile native și cele 18 regresii noi. Verificarea statică a plăților și proba unui apel plătit neprotejat trec. O coliziune conservatoare între `Session.execute` și noul executor GPU intern a fost eliminată prin numele explicit `run_purchase`; scannerul și regulile financiare nu au fost slăbite. Ruff și verificarea de tipuri trec.

## Activare și următoarea verificare reală

Schimbările sunt locale, necomise și necesită următoarea repornire normală a serverului pentru activare. Codex nu a repornit serviciul, nu a apelat modelele, nu a pornit GPU, nu a schimbat oprirea Owner, scenele, verdicturile sau conturile de producție. Ultima citire confirmă GPU oprit; serviciul local nu răspundea la verificarea finală.

La reluarea autorizată, următorul AI urmărește: constatările complete → rescrierea agentului → aprobarea Sarah a textului exact → cererea reală identică → imagine efectiv livrată și acceptată → acea imagine ca primul cadru al clipului → QC video → film finalizat. Nu declară calitatea demonstrată doar din testele locale. Pentru Kelvin nu există în această intervenție o imagine nouă acceptată sau progres video verificat.

Final repository hygiene: format/diff checks pass; 76 changed text files scanned, no new secret findings after removing redundant digest literals from public proof (complete prompt strings remain available for identity verification).
