# Buget actual și corespondență completă — 14 octombrie 2026

Utilizatorul cere eliminarea blocajelor rămase după actualizarea bugetului, limite interne
LLM de zece ori mai mari și eliminarea tăierii mesajelor. Această cerere se aplică viitoarelor
filme și remediărilor prin serviciile comune. Nu s-au modificat scene, verdicturi, conturi,
opriri sau politici în baza de date de producție. Nu s-au apelat modele, pornit serviciul,
GPU, generări ori publicări.

## Ce s-a corectat

- Un plafon explicit STUDIO_FILM_BUDGET_USD are prioritate. Când lipsește, plafonul filmului
  urmează bugetul DAILY activ, citit din DB la fiecare verificare. Fallback-ul vechi de
  15,24 USD rămâne numai când nu există buget zilnic. Bugetele comune, rezervările, costurile
  istorice, limita lunară și toate verificările dinaintea cumpărării rămân obligatorii.
- Prefight-ul explică bugetul comun; nu îl multiplică după numărul filmelor când acesta este
  și plafonul implicit al filmului. Scriitorul, foaia, remedierea și achiziția folosesc aceeași sumă.
- Repurchase gate v2 păstrează contextul deciziei: versiuni și perioade ale bugetelor,
  plafonul filmului și regula de aprobare a media. Un context schimbat redeschide evaluarea
  Nadiei/Sarah. Evenimentele vechi nu sunt șterse; pentru ele se verifică schimbările ulterioare
  și plafonul vechi. Cheltuiala normală nu invalidează repetat refuzul. O acceptare minoră,
  care nu cumpără nimic, rămâne valabilă chiar când bugetul este insuficient pentru cumpărare.
- STUDIO_LLM_CONTEXT_MULTIPLIER=10 este implicit. Fiecare max_tokens explicit este mărit
  o singură dată, după multiplicatorul separat al Directoarei. None păstrează absența unei
  limite interne. Manifestul rulării înregistrează multiplicatorii și limita efectivă.
- Tăierile de caractere și de liste din dosarele QC, briefuri, contextul curent, răspunsuri,
  corespondență, memorie și recenzia dintre modele au fost eliminate. JSON-ul nu mai este
  secționat în mijlocul unui câmp. Peste 200 de tăieri au fost identificate în 24 de module;
  corecturile suplimentare sunt în identity/memory, planul editorului și istoricul rescrierii.
- Contextul identity-v3-complete include toate mesajele deschise adresate agentului și
  întregul fir relevant, cu body_text și body_json. Firul nu este repetat integral pentru
  fiecare mesaj deschis. Memoria selectată crește de la 12 la 120 de înregistrări, fiecare
  păstrată complet. Arhiva nu este încărcată integral la fiecare cerere; selecția respectă rolul.
- clipped/joined/fit_to_schema nu mai taie răspunsuri. complete_schema păstrează validatorii
  semantici, identificatorii, tipurile și expresiile regulate, elimină plafoanele arbitrare de
  text pentru răspunsuri LLM și mărește plafoanele listelor x10. Nu modifică schema clasei
  inițiale. Planurile de cadre și bibliile trec prin același mecanism; acțiunea nu mai este
  tăiată la 500 de caractere.
- Bugetele advisory pentru dosare sunt x10: biblie 120.000, plan 160.000, rescriere 140.000
  caractere. Ele pot separa scene întregi; nu elimină afirmații, lecții, personaje, refuzuri
  ori briefuri. Limitele lecțiilor se măresc x10, iar lecțiile nevalide se refuză întregi.
- Envelopa cererilor de corespondență ale Ownerului este x10. Un răspuns vizibil oprit de
  furnizor cu done_reason=length este păstrat în rulare și marcat INCOMPLETE_OUTPUT; nu
  autorizează executarea. Interfața explică acest rezultat în română.

## Limite reale și activare

Nu mări prin presupunere fereastra fizică a modelului, limitele platformelor sau plafonul
verificat de 20.000 de caractere al cererii native de imagine/video. Acestea se verifică
explicit înainte de cumpărare; nu se rezolvă prin tăierea datelor. Conform documentației
Ollama, modelele Cloud folosesc deja fereastra maximă implicit:
https://docs.ollama.com/context-length . Documentația răspunsului și done_reason:
https://docs.ollama.com/api/generate . Un plafon de răspuns mai mare nu dovedește calitatea.

Serviciul local este indisponibil la ultima citire. Nu a fost pornit de această intervenție.
La următoarea pornire normală se încarcă sursele și configurația implicită noi. Ulterior,
modelul efectiv, promptul revizuit, cererea GPU exactă, imaginea acceptată și QC trebuie
urmărite pe un film deschis. Nu modifica verdicturi manual și nu continua filme publicate.
Un refuz editorial nou și motivat rămâne responsabilitatea Nadiei/Sarah; actualizarea
bugetului redeschide evaluarea, nu inventează aprobarea sau acceptarea vizuală.

## Probe și verificări

BUDGET_AND_COMPLETE_CONTEXT_PROOF_2026-10-14.json este o verificare doar prin citire:
The Zero Script Club are plafon 20 USD, cost istoric 12,843153 USD și 7,156847 USD rămași.
Refuzul 21777 nu mai este reutilizat de codul nou. Aceasta nu este activare în procesul vechi.
COMPLETE_LLM_CONTEXT_CHANGES_2026-10-14.json înregistrează tăierile identificate în surse.

Teste noi: test_budget_change_reevaluation.py și test_complete_llm_messages.py. Sunt probe
locale cu furnizori simulați, DB-uri separate și cadre FFmpeg locale. Testele vechi care
cereau trunchierea au fost schimbate să verifice textul, listele și istoricul complete.
Testul frontend al portretului avea deja un eșec pe Windows: căuta delimitator LF într-un
fișier CRLF și inspecta apoi și funcțiile video care folosesc legitim blob. Normalizarea
EOL în test corectează delimitarea; codul portretelor nu a fost modificat.

Rezultatele finale sunt în CURRENT_STATUS. Mypy a verificat toate cele 39 de module
production modificate, inclusiv lucrările precedente. Typecheck-ul și build-ul frontend
au trecut. Build-ul păstrează avertismentul existent despre mărimea bundle-ului.

## Fișiere și rollback

Nucleul: config.py; agents/identity.py, services.py, memory.py, messages.py, mail.py,
ensemble.py, router.py, schemas.py; economy/repurchase_gate.py; media/prompt_agent.py,
scene_rewrite.py, shooting_sheet.py; runbook/preflight.py; factual/agent_pipeline.py.
Dosarele și rapoartele suplimentare sunt enumerate în manifestul modificărilor.
Frontend: eticheta INCOMPLETE_OUTPUT în main.js și normalizarea EOL în testul portretului.

Schimbările sunt locale și necomise. Nu folosi reset global: în checkout există și lucrările
anterioare la prompturi și gruparea GPU. Retrage numai hunks ale acestei intervenții dacă
este necesar, păstrând modificările anterioare și toate datele de producție.

## Reverificare finală

Cele 27 de regresii noi pentru context complet și actualizarea bugetului au trecut din nou
(12,86 s). Scanarea celor 68 de fișiere schimbate nu a găsit credențiale noi nevalidate.
Verificările /health/live și /health/ready nu au putut contacta API-ul local. Serviciul
nu a fost pornit; activarea codului și proba de producție rămân pentru pornirea normală.
