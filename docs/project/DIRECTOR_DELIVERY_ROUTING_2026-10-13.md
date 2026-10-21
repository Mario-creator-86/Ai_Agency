# Kelvin: eșecul de livrare este preluat de Directoare

La 13 octombrie, 23:18 București, Kelvin era din nou raportat ca așteptând
Proprietarul pentru scena 2. Take-ul `eeeab831-808d-4050-be60-d872c40c2212`
era `REFUSED / RUNPOD.EXPIRED_UNDELIVERED`, fără fișier. Ultima reluare repeta
blocajul de la 17:41. Owner permisese din nou GPU-ul la 22:00:38; oprirea veche
nu era motivul pentru care scena continua să aștepte decizia lui.

## Cauză și corecție

Circuitul Sarah → Kael → prompt rescris → generare exista deja. `quality_refused`
alegea numai `QC.CLIP` și `LOCAL.STILL_GATE`. Eșecul terminal de livrare intra
în `UNKNOWN`, scena rămânea blocată pentru Owner, iar raportul media numea orice
film WAITING drept așteptând Proprietarul, inclusiv când Directoarea lucra.

Corecția reutilizează același circuit:

- Eșecul terminal `RUNPOD.EXPIRED_UNDELIVERED` intră în analiza lui Sarah.
- Brief-ul poate cere `retry_delivery` numai pentru acest eșec. Pentru QC vizual
  cere în continuare o rescriere verificată; reîncercarea livrării nu poate ocoli QC.
- Jurnalul trebuie să confirme FAILED / EXPIRED_UNDELIVERED, fără fișier livrat.
  O cerere activă, ambiguă sau fără acest jurnal nu se trimite încă o dată.
- Promptul, take-ul refuzat, costurile și numărul de încercări plătite se păstrează.
  Decizia ridică blocajul tehnic specific și transmite lui Kael planul de reluare.
- Reluarea revine la scara existentă: buget, aprobare, STOP și politica GPU.
- Dacă procesul moare înainte să scrie blocajul pasului, take-ul expirat tot trebuie
  analizat de Sarah înainte de cumpărare.
- O schimbare a promptului sau a take-ului în timpul analizei invalidează reluarea.
- Întrebarea tehnică veche către Owner se închide după preluare. O aprobare reală
  de cheltuieli rămâne deschisă. Registrul spune „reluarea livrării”, nu pretinde
  că s-a rescris un prompt sau că s-a generat un clip.
- Raportul filmelor în așteptare distinge remedierea Directoarei de deciziile Owner.

Fișiere: `media/scene_rewrite.py`, `media/assembler.py`, `runbook/stages.py`,
`events_feed.py`; regresii în `tests/test_director_delivery_routing.py`.

## Verificare

Teste în baze temporare și cu furnizori controlați; fără generări reale lansate de teste:

- Cele trei regresii inițiale au eșuat pe codul vechi pentru lipsa rutării,
  autorizării recuperării și separării față de QC.
- 11 teste noi: recuperare, jurnal activ, întreruperea procesului, schimbarea promptului,
  raportul/registrul, închiderea întrebării tehnice, păstrarea aprobării și revenirea
  la verificarea normală de cheltuieli.
- Suita fluxului existent: 91 teste trecute; reluări/serial/limite: 33 trecute;
  ultima suită combinată rutare/registru/rescriere: 44 trecute.
- Ruff și inventarul/hashurile documentelor trec.
- Verificarea tipurilor are aceleași cinci erori existente în cele trei module
  urmărite, confirmate prin comparație cu HEAD într-o copie temporară. Nu au fost
  adăugate erori de tipuri. Erorile globale din modulele importate sunt în afara
  acestei modificări; nu se declară mypy verde.

## Activare

La verificarea activării era o generare activă. Citirea jurnalului a arătat că era
chiar noua cerere Kelvin, pornită pe ruta corectată, deci restartul suplimentar nu
mai era necesar pentru preluare; helperul de restart a fost oprit fără să atingă
studioul sau generarea. Această sesiune nu a schimbat politica Owner și nu a repornit
studioul. Refinările ulterioare ale registrului și verificarea suplimentară a unui
prompt schimbat în timpul analizei se încarcă la următorul restart normal.

Dovadă live, București, 13 octombrie:

- **23:38:58–23:39:04**: Sarah, `director_scene_brief`, run
  `e8aceeae-ad90-4739-b904-a2375fe7fbea`, SUCCEEDED.
- **23:39:04**: `media.delivery_retry_authorized`, scena 2, take-ul expirat
  `eeeab831-808d-4050-be60-d872c40c2212`, decis de Director, număr plătit păstrat 0.
  Brief-ul înregistrează `action=retry_delivery`, `resumed=true`, `rewritten=false`.
- Sarah → Kael, mesaj `bd316131-8f06-467c-83ce-2d9514750e44`: reia livrarea
  cu prompturile aprobate, verificând limitele normale înainte de cumpărare.
- **23:39:10**: take nou `9cc89ba6-1e12-4b2b-a9bd-2ace6f94079a`, SUBMITTED;
  job `62c300bb-777d-418e-9880-5f685cb3a39a`, LTX-2.5.
- **23:50:57**: job încă QUEUED. Promptul cererii reale este identic cu cel din
  cererea expirată, SHA-256 `d8c5e0c6403d208d08e399884d79651badc60ee9a6383ed4fee8b3c4393473d5`.
  Este recuperare de livrare. Nu există încă un clip nou livrat și acceptat vizual.
- Întrebarea veche către Owner fusese închisă de Owner la 20:56:38; nu atribuim
  acea închidere corecției. Închiderea automată a unei întrebări tehnice încă deschise
  și păstrarea aprobărilor sunt dovedite separat prin teste.

Probe citite din DB live: în folderul auxiliar `output/delivery-live-proof.json`.
