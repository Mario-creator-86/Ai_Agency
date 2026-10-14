# Prompturi și remediere QC — continuarea din 14 octombrie 2026

Au fost corectate pierderi suplimentare în compunere și în comunicarea dintre agenți.
Cele nouă exemple semnalate anterior au acum propuneri concrete, cu promptul vechi și cel
nou compus: [PROMPT_REPAIR_PROPOSALS_2026-10-14.md](PROMPT_REPAIR_PROPOSALS_2026-10-14.md).
JSON-ul omonim păstrează modificările pe câmpuri, biblia personajelor, verificările și
amprenta textului video. Toate cele nouă propuneri trec verificările deterministe locale.
Nu sunt aprobări Sarah și nu au fost aplicate în baza de producție.
„Înainte” este textul din pachetul scenei înregistrat în snapshot, nu o dovadă a cererii
vechi efective către GPU. „După” este textul candidat compus local, fără un request nou.

Nu s-au apelat modele, cumpărat imagini/video sau repornit studioul. Utilizatorul a raportat
lipsa creditului LLM; nu a anunțat refacerea lui. Calitatea vizuală reală și activarea
codului în aplicația pornită nu sunt demonstrate de acest pas.

## Ce era greșit și ce s-a reparat

- O referință la altă scenă din `ending_frame` elimina întreaga descriere a finalului.
  Acum se păstrează celelalte clauze vizibile, fără pointerul pe care generatorul nu îl
  poate interpreta. Un final care conține o comandă de cameră rămâne blocat pentru editare.
- Primul moment putea deveni doar descrierea hainelor: după introducerea personajului,
  prima acțiune era citită ca un moment ulterior și omisă. Acum introducerea precede
  prima acțiune. „Behind her, Marcus…” și „Marcus stands behind her” păstrează persoana
  și poziția, în loc să rămână fragmentul „behind”.
- Ținta de 95 de cuvinte elimina condiții din mișcarea serialului deși încăpeau în limita
  efectivă folosită de contract. Acum limita tehnică rămâne obligatorie; ținta editorială
  nu elimină acțiunea și finalul care încap. Pierderile imposibil de încadrat sunt semnalate
  și blochează cumpărarea. Limita implicită conservatoare de 1.000 UTF-16 nu este prezentată
  drept capacitatea tuturor modelelor GPU; contractele specifice și rezultatele lor reale
  rămân de evaluat. Nici limita JSON de 20.000 caractere nu dovedește capacitatea tokenizerului.
- Un plan cu „Nothing in the world moves” primea automat umbre în mișcare și, uneori,
  „everything … keeps moving”. Declarația explicită de decor nemișcat se păstrează;
  completarea și finalul camerei nu mai inventează mișcare în acel decor.
- O rescriere exclusiv video putea fi respinsă pentru o omisiune din promptul vechi al
  imaginii acceptate, deși acest strat păstrează imaginea. Verificarea compunerii ține
  acum cont de strat: mișcarea nouă trebuie să fie completă; cumpărarea unei imagini noi
  cere și primul cadru complet. Foaia recunoaște imaginea acceptată pentru promptul curent.
  Dacă QC constată o problemă în imagine, ea trebuie rejudecată/refăcută; această corecție
  nu autorizează animarea unei imagini respinse și nu transformă o imagine greșită într-una bună.
- Mai rămăseseră două limite de șase constatări, tăieri de 300/400 caractere în constatările
  și cauzele curente, tăieri de 600/800 caractere în răspunsul/refuzul editorului și tăierea
  JSON-ului dosarului filmului la 14.000. Au fost eliminate. Lista `avoid` păstrează toate
  excluderile specifice după combinarea bibliei, scenei și brief-ului, inclusiv la serial.
- Răspunsul lui Kael către Sarah include promptul complet, `prompts_before`,
  `prompts_after`, stratul și încercările de revizuire. Mesajul și datele sale structurate
  pot fi citite integral de destinatar. O revizuire nereușită nu autorizează generarea.
- Instrucțiunile inițiale și cele de rescriere cer acțiuni concise, fără repetarea părului
  și hainelor deja introduse din biblie, și acord între subiect, distribuție, primul cadru
  și final. Versiunile de plan/brief/rescriere/review sunt v3; dosarul vizual al filmului v6.

Aceste verificări detectează pierderi de informație; nu înlocuiesc judecata semantică și
vizuală a Directoarei. Pot exista reformulări echivalente ori omisiuni acceptabile pentru
un obiect nevizibil. Nu se elimină protecția doar pentru a obține un verdict local verde.

## Cine repară exemplele

| Film / scenă | Problema și responsabilul |
| --- | --- |
| Moon, 2 | Compunerea ștergea finalul. Codul îl păstrează; filmul este REJECTED în snapshot, nu se redeschide automat. Sarah/Research verifică și fidelitatea fizică a mișcării înainte de reutilizarea unui exemplu. |
| Particle, 5 | Planul trecea de la atomi la tunel într-un singur cadru continuu. Marcus și Sarah decid planul; Kael primește apoi o scenă coerentă. Propunerea rămâne pe grupul de sfere și păstrează finalul explicit. Nu este o nouă aprobare factuală. |
| NASA, 3 | Pointerul la scena 4 ștergea descrierea membranei/flapului. Compunerea păstrează finalul și decorul declarat nemișcat; Sarah verifică promptul efectiv și faptele. |
| Cyclotron, 3 | Subiect/final trunchiate, comandă de cameră în final. Kael primește geometrie concisă și un final vizibil; Sarah verifică obiectul, iar Research clarifică orice efect conceptual nejustificat. |
| Serial, 1 | Subiectul spunea că Sarah lipsește, acțiunea/distribuția o includeau la margine. Sarah și showrunnerul trebuie să stabilească prezența; draftul păstrează umărul vizibil. |
| Serial, 2 | Identitatea duplicată ocupa spațiul acțiunilor. Kael primește acțiuni concise și un final precis pentru ambele persoane; Sarah verifică fiecare condiție. |
| Serial, 4 | Corecția era îngropată în interdicții repetate; poza înregistrată avea ținuta greșită. Sarah rejudecă primul cadru cu biblia Nadiei, Kael repară imaginea înainte de mișcare; Sarah rămâne umăr/braț la margine. |
| Serial, 6 | Prefixul spațial și compunerea pierdeau Marcus/scaunul gol. Kael primește clauze scurte pentru persoane și obiect; Sarah verifică poziția lor în imagine și la final. |
| Serial, 7 | Acțiunea lui Marcus lângă tabla goală dispărea. Kael primește primul moment distinct și finalul; Sarah verifică prezența ambelor personaje și tabla fără scris. |

Biblia completă trebuie comparată cu imaginea și referințele, inclusiv toate hainele/props
vizibile. Verificarea deterministă a ținutei minime din compunere nu demonstrează că toate
detaliile canonice sunt prezente. Un prompt video nu poate schimba hainele primului cadru.

## Dovezi și fișiere

Snapshot-ul înghețat pentru teste: `tests/fixtures/prompt_contract_followup.json`.
Instrumentul de propuneri: `tools/prepare_prompt_repairs.py`, fără acces la producție.
Reauditul bazei actuale: `PROMPT_CONTRACT_FOLLOWUP_CURRENT_2026-10-14.json`, citire SQLite
readonly: 85 scene LIVE/14 storyboard-uri, 57 semnale în textele stocate, șase pachete
încă blocate la simpla recompunere a câmpurilor vechi. Trei pierderi de final sunt corectate
prin compunere; celelalte cer editare. Cele nouă drafturi separate au zero blocaje locale.
Nu suprascrieți auditul inițial cu rezultatul noilor propuneri: sunt probe diferite.

Module modificate în această continuare: `prompt_agent.py`, `scene_rewrite.py`,
`shooting_sheet.py`, `fix_check.py`, `picture_qc.py`. Regresii noi în
`tests/test_prompt_contract_followup.py`; două așteptări vechi actualizate în testele
fix-check și lessons. Testele verifică inclusiv request-ul exact după revizuirea Sarah,
numai cu furnizori controlați/baze temporare, fără generări plătite.

Lotul relevant: 357 teste trecute, cu două avertismente; o eroare a instrumentului de
raportare a fost apoi corectată și raportul executat din nou, cu zero blocaje pentru nouă
exemple. Reverificarea separată a celor 19 regresii trece fără avertismente. Transcrierea
lotului este în `PROMPT_CONTRACT_FOLLOWUP_TESTS_2026-10-14.txt`. După instrucțiunile v3,
reverificarea finală trece 84 teste; o așteptare a versiunii v2 a fost actualizată și testul
verifică și instrucțiunea completă dată autorului inițial. Mypy cu importurile tratate
silent verifică cele cinci module modificate; analiza mai largă a dependențelor raportează
20 erori în alte module și nu este declarată verde. Ruff, formatarea, diferențele Git și
integritatea documentelor trec la închiderea claim-ului. Nu se declară întreaga suită a
proiectului trecută.

## Următoarea verificare reală

1. După refacerea creditului, folosiți pornirea normală și politicile/opririle existente.
   Nu porniți un al doilea worker și nu activați GPU ca efect secundar al acestei documentații.
2. Pentru fiecare film încă deschis, citiți dosarul curent și constatările pe scena/stratul
   actual; nu aplicați automat snapshot-ul de aici. Nu redeschideți filme închise/respinse.
3. Sarah decide cauza și agentul potrivit. Marcus/Research repară povestea/faptele când
   este necesar; Kael repară planul și prompturile. Scurtarea nu poate elimina condiția QC.
4. Sarah revizuiește fiecare constatare față de prompturile compuse. Numai un review valid
   care tratează constatările poate continua; indisponibilitatea modelului rămâne pauză.
5. Comparați cuvintele revizuite cu request-ul real din jurnal, modelul, durata și hash-ul
   imaginii acceptate folosite ca primul cadru. Nu folosiți numai hash-ul pachetului scenei.
6. Judecați noul rezultat și fiecare defect original. Dacă persistă, reveniți la Sarah cu
   probele complete; un alt seed nu este o corecție. Proprietarul păstrează deciziile despre
   conturi/credit/buget, nu primește probleme editoriale ca solicitări de răspuns.

Rollback: retrageți corecțiile locale de compunere/feedback/strat și versiunile lor.
Păstrați probele, take-urile, costurile, politicile și aprobările reale. Nu modificați
verdicturi sau scene în baza de date pentru a simula trecerea QC.
