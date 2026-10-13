# Personaj împreună cu scaunul — verificat pe 9 octombrie 2026

PIXEL_NATURAL_MOTION este complet. Utilizatorul a respins gambele alungite și schimbarea
bruscă între posturi, apoi a cerut generarea fiecărui agent împreună cu scaunul.
Această cerere înlocuiește soluția anterioară cu corpul montat peste mobilierul ilustrat.

## Rezultat

Opt personaje originale, cu identitățile existente, generate împreună cu scaunul/taburetul.
Un singur factor de scalare pentru întregul ansamblu, baza ancorată la podeaua biroului.
Nicio întindere separată a trunchiului, gambelor sau pantofilor. Capul și antebrațul au
mișcări mici, continue; tranziția între stările reale este interpolată în 1000 ms.
Nu se schimbă brusc întregul corp sau scaunul și nu se mai aleg automat cană/întindere.

Scaunele goale din desen sunt acoperite doar prin siluetele lor configurate, cu fragmente
din noua imagine de curățare. Ilustrația aprobată rămâne fișierul original, cu același SHA-256;
clădirea, plantele, mesele, biblioteca, luminile și decorul rămân baza scenei. Dacă foaia
personajului ori imaginea de curățare nu se încarcă sau identitatea este schimbată,
rămân desenul anterior de rezervă și mobilierul original, fără curățare incompletă.

Pozițiile rezervate, desk_id, employee_id și stările din backend rămân autoritative.
ACTORS selectează exclusiv identitatea și aspectul corespunzător din Character Bible.
Animațiile nu creează evenimente/sarcini și nu scriu în backend. Pauza, datele vechi,
conexiunea pierdută, reluarea, pagina ascunsă și ieșirea păstrează protecțiile existente.
Controlul ANIMAȚII continuă să funcționeze inclusiv cu preferința Windows de mișcare redusă.

## Verificări efective

- 863 teste frontend trecute; verificarea tipurilor trecută.
- Cinci verificări Playwright reale, izolate: mediu/ceas, navigare/scroll, viața scenei,
  pauză/reluare și scaune. Verificarea scaunelor parcurge 60 s de timp simulat în 481
  cadre de test pentru opt persoane și patru stări. Picioarele/baza și centrul spătarului
  au exact un singur raster; capul are 475–478 variante. Tranzițiile și pauza sunt testate.
  Acesta este un ciclu simulat de test, nu un minut înregistrat din producție.
- 62 teste backend/documente/secrete/layout/meteo trecute. Ruff și inventarul documentelor
  sunt verificate separat. Filtrul de secrete recunoaște numai liniile complete SHA-256
  din manifestul grafic; o cheie sau un câmp token rămân detectate, cu regresie dedicată.
  .secrets.baseline nu este modificat.
- UI real, numai GET/HEAD și socketul de citire autentificat: la 09:27 București,
  Înnorat 15°C, toți opt angajații ACTIVE/IDLE au variații vizibile. Patru trecători,
  bicicleta, câinele și pisicile au mișcare verificată. Pauza supraviețuiește reîncărcării,
  reluarea funcționează, niciun contur/nume dublat la hover, zero erori de pagină.
- Cele cinci resurse grafice servite au exact octeții originalelor locale. Clipul efectiv
  are 19,916016 s, 1700 × 1006, 12 fps, H.264. 12 fps este rata configurată, nu benchmark.
- Build-ul final servește index-yH2pRUIA.js și index-DLEOKCqA.css, identice cu fișierele locale;
  build.json corespunde surselor și stale=false.
- /health/live și /health/ready răspund 200 HEALTHY în domeniul foundation/API/database.

Nu a fost repornit serverul sau lucrătorul; nicio modificare de politici, chei, modele,
baze de date ori joburi de producție. Fixturile de lucru/gândire sunt separate de realul
IDLE. Fluxurile plătite și acceptarea producției media externe rămân verificări separate.

## Fișiere și dovezi

Cod: frontend/src/pixel_actor_atlas.js, pixel_staff_pose.js (nou), pixel_people.js,
pixel_office.js; config/pixel_actors.json, pixel_office.json. Teste: pixel_staff_pose.test.js,
pixel_seating.spec.js și fixture (noi), pixel_actors.test.js, pixel_life.test.js/spec.js,
frontend/package.json. Filtru/test secrete: scripts/check_secrets.py, tests/test_check_secrets.py.

Dovezi: output/playwright/natural-motion-2026-10-09/:

- chairs-idle/working/thinking/reviewing.png — opt prim-planuri, stări explicit de test;
- chair-cycle-proof.json — 481 cadre, verificări de rigiditate și pauză;
- live-studio-actors.png — captură reală; live-ui-verification.json — măsurători reale;
- studio-chair-motion.mp4 — clip real; live-frame-1/9/18.png — cadre inspectate;
- frontend-unit.log, backend-scoped.log, final-integrity.json;
- before/ — copii de recuperare și dist-before-chair.zip.

[Resurse originale, surse și prompturi](../../art-source/pixel/chair-ensembles-v5/README.md).
Cele patru variante per persoană sunt păstrate ca artă sursă; doar primul ansamblu este
folosit pentru animația stabilă. Desenele v3/v4 anterioare sunt istorice, nu grafica activă.

Recuperare: restaurare numai a fișierelor acestei sarcini din before/, apoi build din toate
sursele curente. Păstrează schimbările RunPod și cele artistice concurente. Actualizare UI:
Ctrl + F5; ANIMAȚII pornit. Serverul existent servește pagina nouă fără restart.
