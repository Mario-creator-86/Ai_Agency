# Agenția: cercul de încercări și proba reală — 14 octombrie 2026

Înainte de oprire nu exista progres de producție verificabil. Sarah repartiza repetat,
iar Kael fie era blocat de un apel rămas din procesul închis, fie returna zero planuri
utilizabile. Nu confundați SUCCEEDED la transport sau FILM_CONTINUE COMPLETED fără lucru
cu un film terminat.

## Cauze confirmate și corecții

1. **Filme deja încărcate reintrau în remediere.** `film_is_closed` verifică acum relația
   exactă PublicationRecord → asset → render COMPLETED → storyboard. Încărcările confirmate
   PUBLISHED/SCHEDULED/REMOTE_CONFIRMED sunt excluse de la scanare, rescriere și cumpărare.
   Titlul publicat poate diferi; privacy nu redeschide producția. Rapoartele vechi devin
   STALE, corespondența de remediere se închide, fără continuare nouă sau schimbare a QC.
2. **Kael era ocupat de un proces mort.** Apelul `f1321dd5` început la 08:51 a supraviețuit
   repornirii de la 08:52 în DB; toate cererile noi primeau „Agent already has an active task”.
   Recuperarea pornește numai sub blocarea exclusivă a workerului și numai pentru apeluri
   corelate cu sarcini text FILM_SHEET_REPAIR preexistente pornirii. Apelurile curente și
   sarcinile care pot cumpăra rămân protejate. Starea este ABANDONED, nu reușită inventată;
   încercările/coada păstrează contabilizarea și backoff-ul. Activare confirmată la 09:20.
3. **Modelul nu livra planul.** GLM-5.3-flash a epuizat 7.000 tokeni în ambele moduri.
   Proba izolată a epuizat și 21.000 tokeni, fără răspuns utilizabil. JSON cerut nu înseamnă
   schemă garantată în cloud: [documentația oficială Ollama](https://docs.ollama.com/capabilities/structured-outputs)
   spune că Ollama Cloud nu suportă în prezent structured outputs. Parserul decide dacă
   există un plan, nu eticheta HTTP. Răspunsurile goale nu sunt folosite la cumpărare.
4. **Sarcina unei singure scene era ambiguă.** Povestea comună făcea Mistral să returneze
   toate cele cinci scene. Fiecare batch numește acum explicit indicii solicitați; contextul,
   toate constatările, biblia și dovezile scenei rămân complete. După corecție a returnat
   numai scena 2: 889 tokeni de ieșire, față de 4.210 pentru cinci scene.
5. **Compunerea inversa interdicții.** `no extra figure, reflection, or ghost image appears`
   era spart la virgule: `reflection` și `or ghost image appears` ajungeau pozitive în video.
   Listele de mișcare păstrează acum propoziția și predicatul comun. Și la imagine, o
   excludere elimină restul listei negate. O excludere se elimină
   întreagă; nu devine o invitație. `flask, stand, valve ... stay locked` rămâne întreg;
   `locked` aplicat obiectelor nu mai este confundat automat cu mișcarea camerei.

## Proba reală autorizată după oprirea studioului

Exemplu: **Storyboard: Why the Kelvin Scale Has No 'Zero' to Begin From**, `83881ed0`,
scena 2. Studioul a rămas oprit. Testele au folosit baze de date copiate pentru scene;
apelurile, modelele și costurile reale sunt în AgentRun din producție, cu rezumat
`Test izolat Codex`. Nu s-au trimis cereri GPU și nu s-a schimbat scena din producție.

- Sarah/kimi-k3 a dat repartizarea și diagnosticul: eliminarea cercetătorului, descrierea
  concretă a suportului/robinetului, cameră statică, geometrie fixă.
- Kael/GLM: EMPTY_OUTPUT la 21.000 tokeni; zero schimbări.
- Kael/Mistral Large 4: plan valid. Prima probă a evidențiat eroarea compunerii; nu a fost
  aplicată în producție. Sarah a observat textul corupt, deși verdictul ei era TREATS.
- După corecția compunerii, Sarah a reverificat textul efectiv: TREATS. A comparat cele două
  probe și a ales modelul alternativ. Alocarea a fost salvată prin comanda versionată
  `assign_agent`, origine DIRECTOR_REPAIR; bugetele, sloturile și politicile rămân păstrate.
- Proba finală folosește **modelul efectiv alocat** și scopul explicit `[2]`. Kael returnează
  numai scena 2. Blocajul local REQUIRED_CONTENT_LOST dispare. Sarah revede textul recompus
  și declară toate cele patru constatări serioase tratate, fără blocaje sau lecții încălcate.
  Mai are două observații consultative de compoziție/gramatică; nu declarați promptul perfect.

S-au făcut **13 apeluri reale**, 125.231 tokeni de intrare / 31.541 de ieșire;
costul calculat în unitatea internă a studioului: **0,078390 VR**, păstrat pe rulări.
Acesta nu reprezintă o factură reconciliată de furnizor.

Textele exacte vechi/noi, verdictul fiecărei constatări și ID-urile apelurilor sunt în
`AGENCY_LOOP_PROOF_2026-10-14.json`. Ultima probă completă este
`output/agency-watch/probe-2306ffc6-8b44-4ae3-84fc-2fa116fd1595/report.json`.
Comparația GLM și alegerea lui Sarah sunt în celelalte rapoarte indicate de JSON-ul dovezii.

## Cod și verificare

Surse: `media/shooting_sheet.py`, `media/blocker_repair.py`, `agents/recovery.py`, `main.py`,
`config.py`, `media/prompt_agent.py`; opțiuni în `.env.example`. Alocarea lui Kael este o
modificare de configurație în DB, cu eveniment și valori anterioare păstrate.

`STUDIO_SHOT_PLAN_OUTPUT_TOKENS` și `STUDIO_SHOT_PLAN_RECOVERY_OUTPUT_TOKENS` sunt configurabile.
O epuizare nativă demonstrată a modelului/furnizorului alocat selectează muncă pe o scenă
completă și alocarea de recuperare. Aceasta **nu a reparat GLM în proba făcută**; alegerea
modelului care livrează efectiv a fost necesară. Limitele zilnice de tokeni/USD sunt independente.

Teste noi: excluderea filmelor publicate, recuperarea selectivă a apelurilor, transportul
JSON/re-ask, profilul bazat pe rezultate, listele negate și replay-ul candidatului real Kelvin.
Fixture-ul vechi din worker folosește SHA-ul real și identitatea curentă de mișcare, pentru
a testa aprobarea validă fără a slăbi protecția clipurilor schimbate.
207 teste relevante și apoi 153 teste de compunere/editorial/remediere au trecut;
reverificarea finală combinată este consemnată în CURRENT_STATUS. Scoped mypy pentru cinci
module, Ruff, formatarea, diff check și hash-urile documentelor sunt verificate separat.

## Ce face următorul AI

1. Păstrează studioul oprit până când utilizatorul dorește reluarea. Nu porni generări din
   automatizarea de monitorizare. Apelurile de test sunt separate de progresul producției.
2. Citește dovezile exacte; nu copia draftul probei ca verdict QC sau ca asset acceptat.
3. La următoarea pornire normală, verifică modelul din **rularea efectivă** și repararea
   scenelor încă blocate. Nu rescrie filme deja încărcate și păstrează imaginile acceptate.
4. Pentru scena 2, diagnosticul este pe stratul STILL: noua imagine trebuie creată din
   promptul revizuit, verificată și acceptată înainte să fie folosită drept primul cadru.
5. Urmărește Sarah review → text/hash exact din request → imagine livrată → QC pe cele
   patru defecte → abia apoi video → review/request nou → QC video. Probele de aici verifică
   textul și comunicarea, **nu dovedesc calitatea unei imagini/video noi**.
6. Folosește comenzi normale și dovezi efective. Un fișier cu secrete criptate este în copiile
   locale de test; nu distribui bazele de date sau cheia. Rapoartele JSON nu conțin cheia,
   URL-uri semnate, imagini base64 sau raționamentul privat al modelului.

La cererea finală a utilizatorului, monitorul `urm-rire-agen-ie-amn-ai` este **PAUSED**.
Studioul rămâne oprit; nu porni automat serverul. Reper: `AGENCY_WATCH_STATE_2026-10-14.json`.
