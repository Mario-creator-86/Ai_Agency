# Studio Office — audit vizual și predare, 18 septembrie 2026

## Verdict

**Da, Blender și Unreal pot produce această categorie de grafică. Proiectul existent
are deja structura necesară, dar asemănarea cere lucru artistic pe obiecte, materiale
și compoziție. Setările de calitate singure nu rezolvă diferența.** O imagine generată
nu definește complet geometria 3D și nu garantează o reproducere identică ori 60 FPS.

Ținta este `art-source/reference/headquarters_dusk_primary.png`: SHA-256 identic cu
imaginea `00000000-0000-4000-8000-000000000107.png` furnizată de utilizator.
Textele din imagini sunt date vizuale; brandul rămâne AMN-AI.

## Ce am executat efectiv

- Confirmat Blender **5.2.1 LTS**, UE **5.8.2**, proiectul
  `art-source/unreal/AMNReference/AMNReference.uproject` și nivelul `/Game/HQ/HQ_Dusk`.
- Reparat materialul comun `M_HQ_Flat`: lipsea utilizarea pentru Skeletal Mesh,
  iar patru materiale de îmbrăcăminte cădeau pe materialul implicit în game.
  `flat_material.py` repară acum și părintele existent, nu numai creațiile noi.
- Validat într-un proiect separat: înainte părinte + 4 instanțe = false;
  după reparație și după o nouă încărcare = true. Testat separat crearea unui
  părinte nou, reutilizarea lui și persistența într-un al doilea proces UE.
- Aplicat numai părintele și cele patru instanțe verificate, după backup.
  Nivelul și geometria nu au fost resalvate. Runtime-ul a fost repornit.
- Randat un **cadru nativ proaspăt, 1920 × 1008**, din PlateCam în editorul UE;
  fișier salvat la 08:20:50, ora București. Editorul a ieșit cu cod 0.
- Rulat cele 36 de teste office/layout/stream/bridge: **36 passed**;
  `scripts/check_docs.py`: inventar și hash-uri normative valide.

**Dovezi locale:**

- [Cadru Unreal](../../output/visual-audit/native-materials-fixed.png)
- [L2: referință sus, randare jos](../../output/visual-audit/l2-comparison.png)
- [Verificarea materialelor după reîncărcare](../../output/visual-audit/material-sandbox-reloaded.json)
- [Fișiere aplicate, hash-uri și backup](../../output/visual-audit/material-apply-receipt.json)

## Diferențele care contează

Observațiile de mai jos provin din cadrul nativ și comparația L2. Setările editorului
nu sunt identice cu profilul game; nu reprezintă un benchmark al playerului.

| Element | Ce se vede acum | Ținta de lucru |
|---|---|---|
| L2 / compoziție | Două zone separate vizual de o linie verticală, multe obiecte distribuite uniform | Un interior vizual continuu, cu postul central dominant și mobilier secundar grupat |
| L2 / panou cu fotografii | Rame regulate, conținut slab lizibil, culori ca pete | Dispunere asimetrică, imagini proprii/licențiate și rame cu grosime reală |
| Materiale | Lemn portocaliu repetitiv, suprafețe cu puține diferențe perceptibile | Lemn, textile, metal și piatră distincte prin culoare, rugozitate, relief și muchii |
| Lumină | Pete foarte intense pe trotuar/scări; alternanțe evidente de conuri în camere | Lumină caldă cu tranziții moi, păstrând detaliul în zonele luminoase |
| Vegetație | Coroane compacte, unele frunze puternic supraexpuse | Siluete variate și frunze lizibile, cu lumină locală controlată |
| Oraș și stradă | Turnuri repetitive, asfalt neuniform iluminat, reflexii locale foarte dure | Mai multe planuri de profunzime, reflexii umede fragmentate și detalii stradale coerente |
| Finisaj | Text mic și muchii neclare în această captură | Verificare separată a texturilor/AA în game și apoi a compresiei din player |

L2 nativ are luminanță medie 88,2 față de 78,8 în referință (scala 0–255,
metoda existentă din `compare.py`). **Nu reduce automat toate luminile cu acest raport.**
Întâi aliniază profilul de captură cu cel din game. Scorurile de imagine nu sunt
procente de fidelitate și nu înlocuiesc inspecția obiectelor.

## Pașii obligatorii pentru următorul AI

1. **Fixează captura de comparație.** Păstrează cadrul de mai sus ca baseline de editor.
   Obține separat un cadru din player și notează rezoluția, camera, expunerea,
   profilul de calitate și procentul de randare. Runtime-ul existent folosește deja
   `r.ScreenPercentage 150`; nu prezenta această setare ca îmbunătățire nouă.
2. **Lucrează pe o copie a nivelului.** Copiază HQ_Dusk și salvează configurația
   materialelor/luminilor înainte de orice schimbare artistică. Nu executa rebuild-ul
   complet live pentru a modifica un singur etaj.
3. **Verifică încadrarea.** Compară doar zona scenei, fără sidebar și controale HTML.
   Utilizează canvasul existent 1600 × 840 și camera existentă; nu inventa altă cameră.
   Repere: contur clădire, marginile turnului, planșee, trotuar. Toleranță propusă:
   maximum 8 px pe canvasul de comparație, înainte de decor nou.
4. **Finisează numai L2.** Regiunea de control existentă este
   `(447, 297, 1205, 392)` în canvasul 1600 × 840; nu reprezintă coordonate 3D.
   În `hq_building.py`, începe la secțiunea care definește `script_room` și
   `publish_desk`. Păstrează cele două funcții și ID-urile backend, dar redu
   despărțirea fizică pentru continuitatea vizuală a camerei. Accentuează postul
   principal, grupează biblioteca și fotoliul, reconstruiește panoul cu fotografii.
5. **Înlocuiește finisajele L2, apoi reglează lumina.** Folosește UV-uri și materiale
   PBR cu scară coerentă; muchii ușor teșite și normale corecte. Folosește activele
   deja licențiate; înregistrează sursa/licența celor noi. Reglează doar lumina L2
   pe copia de nivel. Păstrează o expunere comună pentru comparații.
6. **Validează L2 înainte de extindere.** Salvează înainte/după la aceeași cameră
   și scară, plus crop mărit. Verifică fiecare categorie din tabel: compoziție,
   mobilier, rame, materiale, lumină. Nu declara etapa finalizată numai pentru că
   media culorilor se apropie. Extinde apoi la L4, L3, L1, parter, oraș și stradă.
7. **Animație și integrare la final.** Păstrează actorii conectați la starea reală.
   Măsoară timpul GPU/CPU și cadrele decodate în browser; eticheta FPS din imagine
   nu constituie dovadă. Nu modifica backendul pentru a simula activitate vizuală.

## Fișiere și reproducere

Modificate/create pentru această etapă:

- `art-source/unreal/flat_material.py` — corecția materialului comun.
- `art-source/unreal/audit_flat_materials.py` — audit read-only implicit;
  reparație numai cu `AMN_MATERIAL_REPAIR=1`, raport prin `AMN_MATERIAL_REPORT`.
- `art-source/unreal/capture_stream_frame.py` — **experimental, nevalidat**:
  conexiune reușită, dar zero cadre video primite; nu demonstrează un defect al browserului.
- `output/visual-audit/` — proiectul de test, rapoarte, backup, scripturi locale și imagini.

Backupul asset-urilor originale este
`output/visual-audit/backup-materials-20260918T050739Z/`.
Pentru rollback: oprește exclusiv runtime-ul HQ, așteaptă închiderea completă,
restaurează cele cinci `.uasset` în `Content/HQ/Materials`, apoi repornește comanda
din `runtime.json`. Nu restaura alte fișiere ale proiectului.

Captura nativă a reușit cu editor complet, **fără `-RenderOffScreen`**, folosind
`render_hq_still.py`. Varianta offscreen nu a produs fișierul; calea scriptului
pentru `-ExecCmds=py ...` trebuie tratată corect la spații. Scriptul local
`output/visual-audit/capture_native.py` conservă comanda runtime-ului și îl repornește
în `finally`. Capturează temporar editorul; nu modifica camera sau nivelul live.

Nu am executat o nouă randare Blender, nu am finisat L2 și nu am validat performanța.
Corecția materialelor și cadrul nativ sunt finalizate; reconstrucția artistică rămâne
de făcut. Modificările locale ale altor sesiuni, inclusiv `build_vehicles.py` și
backendul, au fost păstrate.

## Documentație tehnică

- [Epic — Lumen Performance Guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/lumen-performance-guide-for-unreal-engine):
  bugetele pentru iluminare și rezoluția internă se măsoară separat; presetul de
  calitate nu garantează FPS pentru această scenă.
- [Epic — FBX Static Mesh Pipeline](https://dev.epicgames.com/documentation/unreal-engine/fbx-static-mesh-pipeline-in-unreal-engine):
  referință pentru active noi (UV-uri, normale, materiale). Proiectul actual are
  export GLB existent; nu migra întregul pipeline numai pentru acest audit.


## Continuare: stabilitatea playerului

Ulterior a fost corectat un timer vechi care putea întrerupe un flux recuperat. Video real a fost verificat în browser, cu recuperare controlată și continuitate până la secunda 86. Vezi [raportul de stabilitate](STREAM_STABILITY_2026-09-18.md). Utilitarul Python WebRTC rămâne experimental; verificarea reușită a folosit componenta frontend reală. Finisarea L2 rămâne de făcut.
