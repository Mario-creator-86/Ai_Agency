# Garderobă vizibilă, referințe și continuarea studioului — 15.10.2026

Owner cere rezolvarea pierderii garderobei lui Sarah, folosirea portretelor disponibile, eliminarea falsei așteptări după Owner și a plafonului vechi care bloca video-ul. Intervenția începe în 14.10 și se încheie după miezul nopții, ora București.

## Rezultatul implementat

- Personajul vizibil numai ca umăr/braț păstrează garderoba canonică din CharacterBible. Compozitorul și descrierea trimisă QC folosesc aceeași regulă. Nu adaugă chipul/părul personajului parțial și nu transformă cadrul într-un portret cu două persoane. „Face not visible” nu elimină hainele umărului care rămâne vizibil.
- Un prompt salvat fără garderoba personajului parțial este incomplet pentru o imagine nouă și pentru animare. Verificarea rescrierii examinează candidatul nou, nu textul vechi rămas temporar în pachet. Nu se scurtează textele și nu se aprobă automat un draft.
- În conexiunea RunPod configurată, un film cu portret stocat/citibil alege traseul compatibil declarat în catalog, înainte de cost și aprobare. Pentru familia curentă: Qwen-Image-2512 → Qwen-Image-Edit-2511. Se folosește numai un model descoperit pe aceeași conexiune verificată. Fără portret disponibil, modelul inițial rămâne; un alt furnizor nu este înlocuit. Adapterul original rămâne intact; ruta pregătită este reutilizată pentru lot, cu metadata recitită.
- Alegerea este conectată în foaia/API-ul filmului, traseul zilnic și refacerea Directorului. Prețul și hash-ul aprobării reflectă modelul ales înainte de trimitere. Portretul personajului principal merge prin mecanismul existent Figure 1, iar referința stilului filmului prin Figure 2 când este disponibilă și permisă de capacitatea modelului. Nu se pretinde că simpla disponibilitate a rutei dovedește fidelitatea unei imagini noi.
- Verificarea video folosește modelul real al imaginii acceptate pentru limita promptului de imagine. Limita nativă declarată de 20.000 nu mai revine implicit la 1.000 în acest traseu. Limita video a modelului rămâne verificată separat.
- QC verifică separat condiția de personaj parțial fără față și paginile declarate explicit fără linii/grilă. Aceste cerințe trebuie să primească răspunsuri proprii, nu doar un verdict general. Folosește schema existentă a verificărilor punctuale, cu versiunea still-qc-v5-contract; verificările omise rămân blocante. Marcajele cerute pe alte obiecte (de exemplu scara Kelvin) și regulile existente pentru defecte minore nu sunt eliminate.
- Rapoartele STATUS pentru Owner sunt informative. API-ul și interfața separă destinatarul de necesitatea unui răspuns; întrebările și aprobările reale rămân evidențiate. Titlul vechi BOUGHT_WAITING este corectat în proiecție, inclusiv în fir, fără modificarea mesajului istoric. Textele noi spun că studioul continuă verificarea/remedierea.

## Dovadă pe datele reale, fără scriere

`REFERENCE_WARDROBE_WAIT_PROOF_2026-10-15.json` a fost produs cu SQLite deschis în mode=ro. Pentru The Zero Script Club, scena 4:

- Selecția efectiv calculată de codul nou: **Qwen-Image-Edit-2511**.
- Zero blocaje OVER_CAP pentru imaginile curente în planul video.
- Promptul vechi de 1.963 caractere este oprit pentru lipsa sacoului bleumarin, cămășii albe și cravatei sky-blue a lui Sarah. Nu este trecut mai departe doar fiindcă imaginea sa fusese acceptată anterior.
- Mesajul 685f2a20… are requires_owner_response=false și titlul „studioul verifică și continuă refacerea”. Înregistrarea de producție nu a fost rescrisă.

Imaginea livrată la 23:20 a fost acceptată de agenție, însă inspecția locală arăta fața lui Sarah și registrul cu grilă. Acea acceptare nu a fost modificată manual. Noua validare a planului ține animarea până la corectare/rejudecare prin circuitul normal. Nu există în această intervenție dovadă de generație nouă prin Edit, QC vizual nou trecut sau film finalizat.

## Verificări

Suite care se suprapun, nu se însumează: 173 teste extinse trecute pentru compunere, referințe, Director și loturi înainte de întărirea ultimelor verificări; apoi **151 teste** pentru implementarea extinsă (inclusiv gărzi financiare și loturi); **78 teste** de regresie compunere/Director/agenți; reverificarea finală a celor **12 teste** ale garderobei/referințelor/limitei/rapoartelor a trecut. Fișierul nou are nouă regresii, iar testul limitei video este adăugat în test_motion_redo_prices_runpod.py.

Frontend: **957 teste trecute**, inclusiv două cazuri noi care separă informarea de aprobarea reală; verificarea TypeScript și build trec, cu avertismentul existent privind dimensiunea bundle-ului. Mypy trece pe 11 module de producție relevante; events_feed.py are erori de tipare preexistente în alte funcții, în afara modificării de text a acestei intervenții. Ruff, formatarea, integritatea documentației și diff sunt verificate separat.

Cod principal: media/prompt_agent.py, factory.py, assembler.py, stills_stage.py, picture_qc.py, shooting_sheet.py, router.py; providers/runpod/adapters.py; agents/messages.py; runbook/stages.py; events_feed.py; frontend/src/mail_thread.js. Teste: test_visible_cast_and_reference_choice.py, test_motion_redo_prices_runpod.py și frontend/tests/mail_thread.test.js.

## Activare și instrucțiuni pentru următorul AI

Sursa este locală/necomisă și noul frontend a fost construit. Backend-ul are nevoie de repornirea normală pentru încărcarea schimbărilor. La verificarea finală exista un apel GLM de scriere a episodului în curs; nu se întrerupe un apel plătit pentru a activa codul. Codex nu a făcut apeluri LLM/GPU, nu a repornit serviciul și nu a modificat scene, verdicturi, conturi, opriri sau politici.

La următoarea pornire normală, urmărește: semnalarea garderobei lipsă → Sarah/Kael → prompt complet cu vizibilitate parțială → aprobarea Sarah a textului exact → prețul modelului Edit → referința efectivă în cererea RunPod → imagine livrată și verificată pe fiecare condiție → exact acea imagine acceptată ca primul cadru al clipului. Nu relua generarea pe textul vechi sau pe vechea acceptare a unui rezultat care contrazice planul. Păstrează filtrele pentru filme publicate și toate regulile de bani, STOP, leasing, referințe și QC.


Actualizare activare: backendul a fost repornit extern la 21:35:29 UTC, după salvarea surselor; health/live și health/ready 200. Codex nu a repornit procesul și nu a lansat generări. Codul de referințe/garderobă este încărcat; imaginea nouă Edit și verdictul live rămân de observat.
