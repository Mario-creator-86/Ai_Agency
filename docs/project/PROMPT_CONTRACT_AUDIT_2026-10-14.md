# Prompturi și QC — audit și instrucțiuni de continuare

Audit local la 14 octombrie 2026. Nu s-au apelat LLM-uri, nu s-au cumpărat imagini sau
clipuri și nu s-a repornit studioul. Utilizatorul a anunțat că modelele nu mai au credit.

Continuarea ulterioară: [PROMPT_CONTRACT_FOLLOWUP_2026-10-14.md](PROMPT_CONTRACT_FOLLOWUP_2026-10-14.md).
Corecțiile noi reduc blocajele la șase la recompunerea câmpurilor vechi; toate cele nouă
exemple au propuneri revizuite offline în `PROMPT_REPAIR_PROPOSALS_2026-10-14.md`, cu zero
blocaje deterministe. Nu sunt aplicate ori aprobate. Cifrele de mai jos păstrează auditul inițial.

## Rezultatul verificării

Au fost citite toate cele 85 de scene LIVE din cele 14 storyboard-uri înregistrate:
170 de texte pentru imagini și mișcare. Acestea includ istoric respins/randat, nu doar
producții curente. Verificarea deterministă semnalează condiții omise în textele stocate
pentru 57 de scene. Nu este o măsurare a ratei de respingere vizuală.

Recompunerea cu noul cod lasă nouă pachete blocate pentru rescriere editorială. Sunt
propuneri locale: nu au fost aplicate peste scene sau aprobate în numele Directoarei.
Textele înainte/după și fiecare constatare sunt în
`PROMPT_CONTRACT_AUDIT_2026-10-14.json`. Instrumentul reproductibil este
`tools/audit_prompt_contracts.py`; deschide baza SQLite numai pentru citire.

## Probleme corectate

- Filme factuale: `ending_frame` era verificat de QC, dar lipsea din promptul video.
  Acum ajunge și în dialectul modelului ales. Acțiunea și finalul au prioritate față de
  decor; ținta editorială de 95 de cuvinte nu elimină informație care încape în contractul
  real al modelului. Limita furnizorului rămâne obligatorie.
- Serial: compunerea putea pierde ținuta canonică pentru a păstra o acțiune lungă. Acum
  rezervă spațiu pentru primele descrieri ale părului și hainelor. O condiție necesară
  eliminată din imagine/mișcare sau un final inutilizabil produce `REQUIRED_CONTENT_LOST`,
  care blochează foaia înainte de cumpărare și explică agentului ce trebuie scurtat.
- O cameră `static` aleasă explicit este păstrată. Repetarea unei camere statice este
  avertisment editorial, nu motiv de a introduce automat o mișcare. O orbită care poate
  dezvălui o față interzisă este blocată înainte de cumpărare.
- `a finger's-width gap` nu mai activează instrucțiunea care cere figuri umane.
- Agentul care scrie planul primește de la început condițiile privind scena/narațiunea,
  faptele, primul moment, un singur cadru, personajele, hainele, fețele, marcajele permise,
  geometria stabilă, camera și finalul. Pentru un model fără canal negativ trebuie să
  descrie pozitiv rezultatul dorit; lista `avoid` singură nu este o corecție.
- Planurile mari sunt împărțite în loturi de scene întregi. Nu mai dispar scene sau
  afirmații verificate pentru a încăpea în bugetul orientativ de context.
- Au fost eliminate tăierea scrisorilor la 8.000 de caractere, tăierea JSON-ului QC și
  a inboxului Directoarei, omiterea textului scrisorii din acel inbox și omiterea datelor
  structurate din conversația primită de un agent.
- Brief-ul, revizuirea și verificarea rezultatului păstrează toate constatările relevante,
  nu doar primele patru/opt. Condițiile negative specifice scenei și ale bibliei nu mai
  dispar după lista generică sau după pragul estetic de 400 de caractere.
- Protecția existentă `input_guard` este conectată la trimiterea loturilor de imagini și
  video RunPod și la ultima rezervare a unei cereri noi. Compară cuvintele efective,
  modelul și imaginea inițială/referințele, nu doar seed-ul ori hash-ul pachetului. O
  intrare respinsă pentru conținut nu poate fi recumpărată doar cu alt seed. Recuperarea
  unei cereri deja trimise rămâne distinctă de o cumpărare nouă.
- Nu mai există oprirea remedierii foii după cinci încercări, oprirea reluării Directorului
  după șase încercări zilnice sau abandonarea cererii planului după două zile. Remedierea
  semantică are o pauză de cel mult 20 de minute, nu șase ore. Rămân excluderea unei
  continuări duplicate, pauza când furnizorul nu răspunde, aprobările/bugetele și STOP.

## Traseul obligatoriu și responsabilitățile

1. Marcus corectează scenariul numai dacă problema este în poveste/fapte. Cercetarea și
   verificarea faptelor păstrează sursele; Kael primește scena aprobată integral.
2. Kael scrie un pachet pentru primul cadru și mișcare. Imaginea descrie primul moment;
   mișcarea descrie acțiunea, o singură cameră și finalul. Pentru serial, fiecare persoană
   are o clauză separată, cu prezența/partea corpului vizibilă. Finalul nu conține comenzi
   de cameră. Instrucțiunile de cameră stau în câmpul lor.
3. Compunerea și lint-ul verifică textele efective. Pierderea unei condiții oprește
   cumpărarea și se întoarce la agent; nu se scurtează prin eliminarea greșelii de rezolvat.
4. Imaginea generată este judecată înainte de mișcare. Numai o imagine acceptată poate
   deveni primul cadru. Sarah are dosarul complet, inclusiv biblia personajelor.
5. La respingere, Sarah examinează rezultatul și fiecare constatare QC: reală, minoră
   acceptabilă sau falsă. Stabilește cauza și stratul de corectat. O ținută greșită în
   primul cadru cere refacerea imaginii; un prompt de mișcare nu schimbă poza acceptată.
6. Kael rescrie. Sarah verifică promptul **compus**, cu diferența înainte/după și toate
   constatările identificate, înainte de regenerare. `MISSES`, răspunsul indisponibil și
   cuvintele neschimbate nu autorizează o cumpărare. Cele două schimburi dintr-un pas
   sunt o limită de lucru per trecere a workerului; continuarea durabilă reia munca,
   cu istoricul, fără plafon zilnic de remediere.
7. Noul request și imaginea inițială se verifică în jurnal. QC judecă dacă fiecare defect
   inițial a dispărut în noul rezultat. O schimbare de seed sau o afirmație a agentului
   că a corectat problema nu constituie această dovadă.

Sarah coordonează calitatea; Kael modifică planul/prompturile și produce; Marcus repară
scenariul când este cazul. Proprietarul rezolvă conturi, credit, autorizații și depășiri
ale limitelor sale financiare. Problemele editoriale rămân la agenți.

## Verificare și continuare

Lotul amplu: 861 teste, 858 trecute; trei așteptări vechi au fost actualizate pentru noua
versiune și eliminarea regenerărilor neaprobate. Reverificarea finală: 228 trecute, inclusiv
cele trei și cele 20 de regresii noi. Mypy trece pentru 14 module; Ruff, verificarea
diferențelor și integritatea documentației trec. Transcrierea completă, inclusiv primul
rezultat, este în `PROMPT_CONTRACT_TESTS_2026-10-14.txt`.
Testele folosesc furnizori controlați, baze temporare și exemplele înregistrate, inclusiv
Kelvin, ciclotronul și serialul. Demonstrează transferul și protecțiile; nu demonstrează că
un model vizual real va livra din prima o imagine bună. Verificarea de tipuri este pentru
modulele modificate, nu o certificare a întregului proiect.

După refacerea creditului: activați codul prin pornirea normală, păstrând opririle și
politicile Proprietarului; lăsați workerul să rescrie cele nouă pachete unde filmele sunt
încă deschise; verificați în jurnal promptul revizuit de Sarah versus request-ul efectiv,
apoi imaginea/video și răspunsul QC pentru defectul inițial. Nu redeschideți storyboard-uri
respinse/închise și nu înlocuiți verdictul prin editarea bazei. Traseul RunPod este testat;
adaptoarele externe rămân de evaluat cu fiecare model real. Nu există dovadă nouă de
activare în aplicația pornită, generare reală reușită sau publicare.

Rollback: retrageți aceste schimbări de compunere/context/limite și protecția de la
trimitere/rezervare. Păstrați jurnalul, artefactele, rezultatele și politicile Proprietarului.
Nu resetați scenele sau munca existentă pentru a obține artificial teste ori QC verzi.
