# Loturi GPU pregătite și aprobate — 14 octombrie 2026

Cererea Proprietarului: pregătiți toate imaginile și videoclipurile eligibile înainte de
RunPod; trimiteți lucrările compatibile împreună când modelul este disponibil. Descărcarea
modelului nu trebuie repetată din cauza pregătirii scenei următoare după fiecare generare.

## Cauzele constatate

Generarea inițială avea deja liste de scene pentru imagini și mișcări. Refacerile după QC,
în `runbook.stages._apply_repairs`, făceau însă corectare, aprobare și `redo_scene` complet
pentru o scenă, apoi treceau la următoarea. Fiecare refacere RunPod deschidea propria sesiune.
Prima verificare completă a fiecărui segment de cerere era făcută chiar înainte de acel
segment: o eroare în segmentul 2 putea fi descoperită după ce segmentul 1 fusese trimis.
Legăturile imaginilor expirau după 7.200 de secunde, iar TTL-ul fiecărui job nu includea
timpul lucrărilor aflate înaintea sa în coadă.

## Fluxul implementat

1. Sarah verifică defectele și corectarea prompturilor pentru toate scenele propuse înainte
   de cumpărare. Nadia examinează fiecare recumpărare înainte de trimiterea lotului stratului.
2. Fiecare achiziție trece prin codul existent: plan actual, sursă/model, lint, imagine
   acceptată pentru video, aprobarea necesară, plafonul scenei/filmului/zilei, film deschis,
   protecția aprobărilor finale. Se păstrează rezervarea proprie și blocarea filmului.
3. Achizițiile RunPod se suspendă la limita GPU cu `RoundWork`, fără să raporteze o cumpărare
   fictivă. Abia după pregătirea tuturor se reunesc cererile compatibile.
4. Loturile de imagini sunt executate primele. Planurile video sunt recitite după acest pas;
   o imagine respinsă, nejudecată ori încă în tranzit ține în așteptare videoclipul acelei scene.
5. Cererile eligibile sunt rezervate, imaginile sunt încărcate în bucket, iar TOATE segmentele
   sunt validate înainte de GPU-on. Cererile pentru același model sunt alăturate. Segmentele
   necesare pentru limitele lucrătorului sunt trimise consecutiv, înainte de primul poll.
6. QC și decontarea revin fiecărei achiziții existente. Fiecare scenă primește rezultatul,
   costul și dovada sa; oprirea sesiunii GPU și probele cererilor incerte rămân obligatorii.

Compatibilitatea cere aceeași conexiune/configurație/transport, același tip imagine/video,
același spațiu de stocare și aceeași conversie a timpului GPU în credite. Nicio cerere video
nu este amestecată cu imaginile într-un singur job. Fiecare permis dintr-un lot este verificat
de Policy Kernel; sesiunea înregistrează planurile/aprobările participante.

Costul pornirii se estimează o singură dată pe rundă și se repartizează între achizițiile
participante. Plafoanele individuale nu pot împrumuta bani între scene. Costul măsurat peste
estimare rămâne în contabilitate. O cerere netrimisă restituie numai costul corespunzător;
un răspuns pierdut rămâne incert până la dovada că nu a fost pus în coadă.

## Fișiere și contract pentru următorul AI

- `backend/app/media/prepared_batch.py`: `purchase_flow` păstrează API-ul sincron; `flow_call`
  expune pregătirea cooperativă; `run_prepared` avansează toate achizițiile, apoi execută
  loturile compatibile. Generatorii păstrează contextul rezervărilor și blocării filmului.
- `backend/app/media/assembler.py` și `stills_stage.py`: aceeași pregătire/QC/decontare pentru
  apelul individual și cel grupat. Nu creați o a doua implementare a cumpărării.
- `backend/app/runbook/stages.py`: toate corectările înainte de GPU, apoi imagini, apoi
  videoclipuri eligibile. Blocarea exterioară a filmului persistă până când toate achizițiile
  grupului își încheie decontarea. Cota refacerilor contează achiziții pregătite efectiv;
  o întrebare fără aprobare nu ocupă locul unei alte scene aprobate.
- `backend/app/media/gpu_batch.py`: validare înainte de GPU-on, oprire/restituiri și identitate
  `(project_id, scene_id)`; contabilizarea grupată are aceeași semantică ca varianta individuală.
- `backend/app/providers/runpod/batch.py` și `adapters.py`: `prepare_round` / `submit_prepared`.
  Nu reconstruiți promptul la dispatch. O pregătire abandonată înainte de dispatch este UNSENT;
  cererile incerte ale unei sesiuni anterioare nu sunt șterse de această abandonare.
- `backend/app/providers/runpod/gpu_session.py`: verificarea fiecărui permis al lotului și
  înregistrarea participanților; GPU-off rămâne în `finally`.

Aplicarea automată de acum grupează scenele din etapa/refacerea filmului curent. Executorul
poate coordona cereri din filme diferite, cu identități și costuri separate; apelantul trebuie
să dețină blocarea fiecărui film până la decontare. Coada generală de taskuri nu este înlocuită
de un planificator global care așteaptă toate filmele agenției.

TTL-ul segmentelor include execuțiile anterioare și așteptarea cache-ului. Legăturile
imaginilor includ și așteptarea unei sesiuni GPU disponibile. Limitele de execuție/configurație
și durata maximă de șapte zile rămân validate; o durată imposibilă refuză întregul lot înainte
de GPU. Aceste perioade de așteptare nu sunt transformate în timp GPU facturat. RunPod
precizează că [TTL începe la trimitere și include coada](https://github.com/runpod/docs/blob/main/serverless/endpoints/endpoint-configurations.mdx).

## Verificare și activare

Verificările folosesc baze SQLite și transporturi simulate, inclusiv traseele reale de
achiziție, QC și decontare ale aplicației. Nu s-au făcut apeluri LLM plătite, porniri GPU,
modificări ale bazei de producție sau deployment de worker. Refolosirea efectivă a cache-ului
pe gazdele RunPod și calitatea imaginilor/video necesită observarea unei rulări reale.

Rezultatele finale ale verificărilor sunt în `CURRENT_STATUS.md`. Nu prezentați aceste teste
ca dovadă de generare reală pe GPU. Workerul și formatul contractului existent sunt păstrate.
Serverul deja pornit încarcă aceste schimbări la următoarea repornire; nu întrerupeți o
achiziție activă pentru activare.

O întrerupere a pregătirii trece mai întâi prin tratarea erorilor fiecărei achiziții suspendate:
restaurarea preluărilor, decontarea unei cereri posibil trimise ori eliberarea rezervării
necheltuite. Abia după aceea se închid generatorii și se eliberează blocările filmelor.
