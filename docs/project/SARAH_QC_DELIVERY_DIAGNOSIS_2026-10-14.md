# Sarah: QC vizual confundat cu livrare eșuată — 14.10.2026

Verificare cerută de Owner după remedierea precedentă. Producția a fost citită fără scriere.

## Ce s-a întâmplat

1. Kael, model efectiv `mistral-large-4`, a rescris planurile serialului în două runde. Prima a lăsat o constatare în scena 8; a doua a încheiat fără blocaje locale de prompt/plan (eveniment 22405, 17:50:25 UTC / 20:50:25 București). Scena 4 are acum imagine de 1.859 caractere și mișcare de 584, cu fundal complet și garderoba Nadiei explicită. Promptul nou nu a fost trimis la GPU; nu există o imagine nouă sau acceptare vizuală demonstrată.
2. Sarah, model efectiv schimbat între timp în `deepseek-v4.1-flash`, a privit din nou clipul existent și a confirmat trei defecte reale: garderoba Nadiei greșită, Sarah absentă și apropierea camerei în locul cadrului static (evenimente 22602 / 22619).
3. Circuitul de rescriere a filmului a moștenit `delivery_failure` din cel mai recent take, care încheiase cu `RUNPOD.EXPIRED_UNDELIVERED`. Aceasta era altă încercare, fără fișier livrat. Funcția `rewrite_for_redo` adăuga corect constatarea QC a filmului, dar păstra simultan instrucțiunea de a reîncerca livrarea. Sarah a diagnosticat apoi livrarea, ignorând problema vizuală curentă.
4. Exemplul JSON din instrucțiune omitea `action`, deși validatorul cerea `retry_delivery` în acel context. Cele patru răspunsuri de brief nu au produs o rescriere utilizabilă. Ambele decizii de reparare au încheiat `NOTHING_DONE` (22610 / 22627), nu progres de generare.
5. Niciun job GPU nou după 17:39 UTC. Owner a eliberat oprirea GPU la evenimentul 22387; ulterior închiderea serverului a oprit și verificat GPU la 22630–22637, până la 18:10:52 UTC / 21:10:52 București. La verificare serviciul local nu răspunde. Nu confundați oprirea serviciului/GPU cu `autonomy_stopped`: politica globală păstrează valoarea false.

## Corecție locală

`backend/app/media/scene_rewrite.py`: rescrierea pentru QC al filmului elimină doar rutarea activă `delivery_failure`, păstrează constatările QC și jurnalul original, fixează cauza activă `QC.FILM` și stratul cerut. Circuitul separat pentru livrare terminală rămâne intact, cu dovada din jurnal și toate regulile de buget, oprire și aprobare.

Contractul `director-scene-brief-v4` include în exemplul JSON acțiunea efectivă cerută. Schema unei livrări cere explicit `action`; nu inventează decizia și nu transformă un răspuns incomplet în aprobare. Pentru QC, `retry_delivery` rămâne interzis.

Cinci regresii noi în `tests/test_director_delivery_routing.py`, pentru ambele straturi, păstrarea circuitului independent de livrare, acțiunea explicită și exemplul trimis. Verificare finală: **53 teste trecute** pentru livrare, regenerare, rescrierea Directorului și aprobările curente; Ruff, formatare, mypy, integritatea documentației și verificarea diferențelor trec. Testele folosesc baze temporare și modele simulate; Codex nu a făcut apeluri LLM/GPU, restart sau modificări de scene, verdicturi, conturi sau politici de producție.

## Probleme distincte și următoarea verificare

Sarah `director_review`, rulare 8a294de7…, a primit HTTP 400. Cererea înregistrată avea 480.000 tokeni maxim de ieșire, dar eroarea salvată nu păstrează explicația furnizorului; nu este demonstrat că această valoare a cauzat refuzul. Alte apeluri DeepSeek au reușit. Nu atribuiți problema lipsei creditului fără dovadă.

Scrierea episodului, `glm-5.3-flash`, rulare 482194bf…, a încheiat `ProviderUnreachable` după circa zece minute. Nici acest eșec nu este rezolvat de corecția rutării QC. Rularea zilei spune explicit că nu a publicat niciun film, deși statusul său de coordonare este `COMPLETED`.

Promptul scenei 4 numește umărul lui Sarah, însă `in_frame` o include doar pe Nadia; hainele vizibile ale lui Sarah nu sunt descrise explicit în textul compus. Sarah trebuie să confrunte această omisiune cu biblia/referința la aprobarea textului final. Un plan fără erori deterministe nu înseamnă prompt aprobat semantic sau imagine acceptată.

Schimbările sunt locale/necomise și se încarcă la următoarea pornire normală. La reluare urmăriți explicit Sarah → brief QC, Kael → rescriere, Sarah → verificarea textului exact, apoi cererea reală identică și QC al rezultatului. Nu porniți generări pentru a verifica această intervenție. Kelvin nu are progres nou de media în jurnalul inspectat.
