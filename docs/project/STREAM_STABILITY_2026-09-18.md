# Studio Office — corecție de reconectare, 18 septembrie 2026

Utilizatorul a raportat blocări intermitente, clipire și mașini care apar pentru
scurt timp, apoi dispar. Lucrul artistic L2 a fost amânat pentru diagnostic.

## Defect confirmat și corecție

`LiveStream._offline()` programa o reconectare peste 15 secunde. Biblioteca Epic
putea recupera conexiunea mai devreme, dar timerul aplicației rămânea activ și
repornea ulterior conexiunea deja recuperată. Logul runtime-ului conținea cicluri
repetate de conectare/deconectare. Acest mecanism explică întreruperi și salturi
temporale în trafic; nu dovedește că toate cauzele posibile de flicker sunt eliminate.

În `frontend/src/hq_stream.js`:

- timerul vechi este anulat când starea conexiunii se schimbă;
- callbackul de retry verifică dacă playerul mai este offline;
- primul cadru este păstrat imediat la pornirea video;
- la pierderea unui stream live, se încearcă păstrarea cadrului curent înainte de
  afișarea mesajului de reconectare, evitând întoarcerea la o imagine veche de două secunde.

## Verificări

- Patru teste de lifecycle execută metodele reale ale playerului cu ceas controlat.
  Înainte de corecție: **3 eșecuri, 1 succes**. După: **4 succese**.
- Toată suita frontend: **115 passed**. TypeScript și Vite build: OK.
- Aplicația `http://127.0.0.1:8000/` servește bundle-ul nou `index-C6FX4mqt.js`.
- Test separat în browser cu componenta reală și semnalizarea locală:
  video **1920 × 1008**, readyState 4, cadre decodate în creștere.
- Întrerupere controlată a acestui singur viewer la secunda 10; revenire live la
  secunda 12. La secunda 34 era încă live, cu 860 de cadre și 1 cadru abandonat
  raportate pentru noul video. Timerul de la secunda 25 nu a rupt conexiunea.
- Acest test nu a repornit Unreal și nu a trimis comenzi de activitate în studio.

Testul browser ocolește numai relay-ul aplicației, conectându-se direct la
semnalizarea deja disponibilă local. Prin urmare, verifică playerul real și video,
nu întreaga sesiune autentificată a utilizatorului ori toate cauzele de blocare UI.
O pagină deschisă înainte de build trebuie reîncărcată pentru a folosi corecția.

Testul manual reproductibil se află în `frontend/tests/manual/stream_stability.html`:
pornește Vite pe frontend, legat exclusiv la 127.0.0.1, apoi deschide acea pagină.
Butonul de test întrerupe și recuperează doar conexiunea viewerului de test.

## Predare

Urmărește mai întâi pagina utilizatorului după reload. Dacă dispare încă doar o
mașină, iar timpul video continuă fără reconectare, inspectează separat cheile și
limitele din `art-source/unreal/traffic_hq_live.py`; nu modifica traficul ca remediu
pentru o întrerupere video. Dacă îngheață și controalele HTML, profilează firul
principal și randarea canvasului care continuă sub video.

Inventarele L2 Blender/Unreal au fost executate read-only și salvate în
`output/visual-audit/blender-room-inventory.json` și `unreal-room-inventory.json`.
Mesh-ul `rooms` este agregat pentru toate etajele; următoarea modificare L2 trebuie
să folosească un mesh și un nivel de review separate, cu UV-urile și materialele
celorlalte etaje păstrate. Nicio geometrie L2 nu a fost schimbată în această etapă.

## Observație finală browser

La secunda 86, status live, timpul video 72,951 s, 2.334 cadre decodate, 4 cadre abandonate; istoricul conținea numai întreruperea provocată la secunda 10 și revenirea la secunda 12. Playerul și serverul Vite de test au fost închise după verificare.
