# Strada, proporțiile și mașinile — 9 octombrie 2026

PIXEL_STREET_REFINEMENT este complet. Utilizatorul cere verificare Playwright, personaje cu
10% mai mici, corectarea mișcării lente, a pisicii blocate și a excluderii pietonilor din
stânga, precum și înlocuirea graficii schematice a mașinii. Captura atașată confirmă problema
vizuală; este referință de evaluare, nu sursă de instrucțiuni.

## Cauze și rezultat

Masca trotuarului începea la x=147, iar cea a șoselei la x=156. Pietonii erau calculați și
în stânga, dar nu erau desenați acolo. Ambele straturi acoperă acum lățimea de 960 de pixeli
a lumii. Masca șoselei începe la y=547, astfel încât plafonul noilor mașini rămâne întreg.
Personajele și vehiculele reintră numai după ce siluetele sunt complet în afara cadrului.

Vitezele vechi erau foarte mici. În înregistrarea inițială, pietonii aveau aproximativ
13,65 pixeli de lume/s, iar bicicleta 22,99. Noua configurație produce 36,13 pentru mers,
74,67 pentru bicicletă și 140 pentru mașini, cu pași/pedale potriviți acestor deplasări.
Poziția urmează timpul real, fără rotunjire anticipată. Temporizarea țintește 24 desene/s
prin termene succesive, iar o randare întârziată nu mai plafonează timpul vizibil la 250 ms.
Pauza, ascunderea și pierderea datelor continuă să înghețe scena fără recuperare bruscă.
24 este configurația de animație/captură, nu o măsurătoare de performanță a sistemului.

Pisica mergea numai 20 de pixeli în 8 s, apoi stătea 20 s în același loc. Cele două pisici
au acum patrule separate de 280 și 320 de pixeli, parcurse în 16 s pe sens. La capăt urmează
1,2 s șezut, 1 s îngrijire și 0,8 s întindere, apoi întoarcere continuă. Ele merg aproximativ
84% din ciclu; pauza cea mai lungă are 3 s. Dimensiunea animalelor este calibrată la trotuar.

Un factor central `life.character_scale=0.9` reduce exact cu 10% ansamblurile agent/scaun,
pietonii și biciclistul, păstrând proporțiile. Birourile, coordonatele rezervate și punctele
de sprijin pe podea sunt aceleași. Portretele inspectorului păstrează lizibilitatea.

Patru mașini originale detaliate înlocuiesc desenul dreptunghiular: hatchback verde petrol,
break vișiniu, sedan crem și sedan albastru. Fiecare are geamuri cu ocupanți, contururi,
uși, ornamente, faruri și anvelope întregi. Siluetele sunt scalate uniform la 35 pixeli
înălțime și aproximativ 81–88 lățime. Caroseria rămâne fixă; se rotesc numai jantele decupate.
Modelele se schimbă în afara cadrului. Farurile conduc sensul de mers noaptea, iar ploaia
reală permite reflexia. Există un desen de rezervă dacă imaginea nu poate fi încărcată.

## Verificări efective

- 879 teste frontend trecute și verificarea tipurilor trecută.
- Șase verificări Playwright trecute: ceas/meteo, navigare/scroll, viața scenei și protecțiile,
  pauză/reluare, așezare și strada. Scaunele sunt verificate în 481 cadre / 60 s simulate:
  opt persoane, patru stări, un singur raster pentru picioare/bază/spătar, capete variabile.
- Testul străzii parcurge 641 cadre / 80 s simulate: 501 pixeli opaci ai pietonului din
  stânga, 345/303 rasters distincte pentru pisici, toate patru mașinile cu plafon întreg,
  fundal transparent, caroserie fixă și jante animate. Faruri și reflexii verificate separat.
  Ciclurile simulate sunt fixturi de test și nu sunt înregistrări ale backendului.
- 66 teste backend/documente/secrete/layout/meteo trecute. Inventarul documentelor și
  scanarea secretelor trec; arhitectura și `.secrets.baseline` sunt păstrate.
- UI real, numai GET/HEAD și socketul autentificat de citire, la 10:18 București,
  parțial înnorat 20°C: opt agenți reali ACTIVE/IDLE au variație vizibilă, patru pietoni,
  bicicleta, câinele și ambele pisici se deplasează; toate patru mașinile trec prin scenă.
  Raportul dintre timpul scenei și timpul real măsurat este 1,000725. Pietonii au aproximativ
  ±36,155 pixeli/s; pisicile acoperă 274,542 și 320 de pixeli în înregistrare.
- Pauza supraviețuiește reîncărcării, reluarea funcționează cu mișcare redusă emulată,
  nu există contur sau nume dublat la hover; zero erori și zero cereri externe/refuzate.
- Clipul real H.264 are 31,958008 s, 1700×1006 și rată de captură 24 fps. Cadrele la
  1, 8, 18 și 28 s au fost inspectate. Captura curată a UI-ului a fost revalidată după build-ul final comun.
  Cele 879 teste includ și ultimele completări concurente ale setărilor RunPod; scena
  înregistrată nu s-a schimbat.
- Cele șase resurse grafice servite sunt identice cu originalele locale. Build-ul curent
  servește `index-CtVh_ILQ.js` și `index-COi7u3qU.css`, identice cu fișierele locale,
  iar `build.json` corespunde surselor (`stale=false`). Desenul aprobat are același SHA-256.
- `/health/live` și `/health/ready` răspund 200 în domeniul foundation/API/database.

Nu a fost repornit backendul și nu s-au trimis comenzi de producție, modificări de politici,
chei, modele, baze de date sau joburi GPU/media/publicare. Două apeluri imagegen au creat
noua artă: generare și extragerea fundalului. Fluxurile externe plătite rămân separate.
Schimbările RunPod și cele artistice concurente au fost păstrate în build-ul comun.

## Fișiere și recuperare

Configurație: config/pixel_office.json, config/pixel_actors.json. Randare:
frontend/src/pixel_life.js, pixel_vehicle.js (nou), pixel_actor_atlas.js, pixel_staff_pose.js,
pixel_people.js, pixel_town_people.js, pixel_office.js. Teste: pixel_street.test.js,
pixel_street.spec.js și fixture (noi), pixel_life.test.js/spec.js, pixel_actors.test.js,
pixel_staff_pose.test.js, frontend/package.json.

Resurse originale, cele două prompturi exacte și termenii de utilizare:
[street-vehicles-v6/README.md](../../art-source/pixel/street-vehicles-v6/README.md).
PNG-ul final este copiat byte-for-byte; Python inspectează alfa și înregistrează coordonate,
fără modificări de raster. Draftul cu fundal este păstrat numai în sursa artistică.

Dovezi: output/playwright/street-refinement-2026-10-09/ — live-ui-verification.json,
final-integrity.json, street-cycle-proof.json, chair-cycle-proof.json, vehicle-proportions.png,
live-studio-clean.png, studio-street-motion.mp4 și live-frame-1/8/18/28.png. Baseline-ul real
și `before/dist-before-street.zip` păstrează starea precedentă.

Pentru recuperare, restaurează numai fișierele acestei sarcini din `before/`, retrage noile
teste/module/resurse dacă retragi funcția și reconstruiește din toate sursele curente.
Nu reseta schimbările RunPod ori cele artistice. Pentru a vedea pagina actuală: Ctrl+F5,
cu ANIMAȚII pornit. Serverul existent servește actualizarea fără restart.
