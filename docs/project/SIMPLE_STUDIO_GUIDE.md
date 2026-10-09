# AMN-AI — pornire și autonomie

Proiectul existent are acum o interfață cu un studio pixelat. Trezoreria, finanțarea virtuală
și VendorShop au fost retrase din produsul activ. Rămân agenții, cercetarea, producția,
verificarea calității, distribuția, programarea, bugetele reale și aprobările.

Studioul păstrează biblioteca, echipamentele, masa de desen, canapeaua, plantele și luminile
din imaginea aprobată. Un etaj suplimentar oferă loc celor opt agenți existenți. Fiecare
angajat are un loc personal la mobilierul ilustrat și stă cu fața spre birou.
Numele apare la trecerea mouse-ului sau selecție. Lista de jos și inspectorul arată numele
și starea: în lucru, se gândește, verifică, în așteptare, blocaj, eroare sau în pauză.
Stările vin din backend. Lucrul animă tastarea/scrisul, gândirea aduce mâna la bărbie;
clipitul și respirația discretă dau viață și personajelor care așteaptă.
Pauza angajatului, blocajul, datele vechi și reluarea opresc gesturile.
Butonul **ANIMAȚII** din bara camerei pornește sau pune pe pauză mișcarea întregii scene.
Animațiile sunt pornite implicit, conform cererii tale; alegerea se păstrează la reîncărcare.
Studioul poate rămâne animat și când Windows reduce mișcarea interfețelor.
Pauza animațiilor nu modifică activitatea reală a agenților.
Birourile rămân aceleași la schimbarea stării, pauză, angajarea ori plecarea unui coleg.
Pentru mai mult de opt angajați apar birouri suplimentare, accesibile din lista de jos
sau butoanele de sus. Apasă un birou/nume pentru inspector și conversație; poți folosi
și săgețile cu Enter. Coafurile, culorile și accesoriile păstrează identitatea existentă.
Portretul din inspector arată fața personajului. Pe telefon, folosește zoomul pentru detalii.

## Ceasul și vremea de afară

Ceasul de pe trotuar arată ora Bucureștiului, inclusiv schimbarea sezonieră. Lumina de afară
urmează poziția soarelui pentru data și coordonatele configurate. Vremea este citită prin
serviciul existent și actualizată la zece minute: senin/nori, ploaie, ceață sau ninsoare.
Efectele rămân afară; mobilierul și luminile din camere își păstrează detaliile.

Dacă serviciul nu răspunde ori datele sunt prea vechi, apare „Vreme indisponibilă” și nu sunt
inventate precipitații. La reluarea unui moment, vremea de atunci rămâne necunoscută.
Mișcarea redusă păstrează efectele statice; fereastra ascunsă sau ieșirea opresc actualizările.
Ora continuă să se actualizeze și când agenții sunt în așteptare.

Setările existente din `.env`: `STUDIO_TIMEZONE`, `STUDIO_OFFICE_CITY`,
`STUDIO_OFFICE_LATITUDE`, `STUDIO_OFFICE_LONGITUDE`, `STUDIO_OFFICE_WEATHER_HOST`.
Bucureștiul este deja configurat; ceasul și vremea nu necesită datele RunPod.

## Pornește studioul

Din folderul proiectului real rulează `start.cmd` (în PowerShell: `.\start.cmd`).
Comanda `python start.py` este din nou compatibilă și folosește automat mediul proiectului.
Lansatorul principal rămâne `uv run --locked python scripts/start.py`.
Dacă mediul existent indică un Python lipsă, `start.cmd` reinstalează automat versiunea
cerută în `.python-version`. Recuperarea necesită internet și un `uv` actualizat; pe acest
calculator utilitarul a fost actualizat la 0.12.23. Folosește `start.cmd` când Pythonul
din terminalul activat nu poate porni. Un mediu sănătos nu este reinstalat.
Deschide adresa locală afișată și introdu cheia Proprietarului din `.env`.
Pagina poate fi închisă după configurare; lucrătorul din backend execută programarea.
Calculatorul și procesul studioului trebuie să rămână pornite.

## Configurează o dată

Conexiunea Ollama Cloud și modelele celor opt angajați sunt deja verificate și alocate.
Lista completă, ce oferă fiecare model și motivele alegerilor sunt în
[OLLAMA_ROLE_ALLOCATION.md](OLLAMA_ROLE_ALLOCATION.md). Alegerile salvate rămân protejate
la actualizarea catalogului; le poți modifica din Setări. LLM-ul Lyrei pregătește textul
și regia vocală; pentru sunet este folosit furnizorul de voce existent.

1. **Setări → Furnizori AI:** verifică furnizorul și alege modelele angajaților.
2. **Setări → Video și sunet:** conectează furnizorii media și selectează imagine, video și voce.
3. **Autonomie → Buget:** setează limita zilnică și, opțional, limita lunară în USD.
4. **Autonomie → Prețuri:** completează doar prețurile care lipsesc; un cost necunoscut rămâne necunoscut.
5. **Autonomie → Mod și permisiuni:** alege nivelul de autonomie și când se cere aprobarea
   unui pas plătit. Comutatorul AUTONOMIE oprește lucrul automat.
6. **Autonomie → Program zilnic:** pornește programarea și verifică următoarea rulare.
7. **Setări → Conturi și e-mail / Canale:** configurează publicarea și drepturile Directorului.
8. **Autonomie → Verificări:** rezolvă punctele care blochează. TEST și PRODUCTION sunt moduri
   separate; interfața afișează întotdeauna modul real.

Ora și limitele de producție se configurează în `.env`:

| Setare | Scop |
|---|---|
| `STUDIO_TIMEZONE` | Fusul orar al programării |
| `STUDIO_DAILY_RUN_HOUR_LOCAL` | Ora rulării zilnice |
| `STUDIO_WORKER_ENABLED` | Lucrătorul automat |
| `STUDIO_FILM_BUDGET_USD` | Limita totală pentru un film |
| `STUDIO_MOTION_BUDGET_USD` | Limita mișcării video |

După modificarea configurației de pornire, repornește studioul. Limitele și permisiunile
salvate din interfață sunt păstrate în baza de date. Setările existente nu au fost ridicate
automat la niveluri mai permisive.

## RunPod

Integrarea este pregătită și rămâne dezactivată până la introducerea datelor reale.
Pașii și câmpurile exacte sunt în [RUNPOD_HANDOFF.md](RUNPOD_HANDOFF.md) și
[RUNPOD_INTEGRATION.md](../RUNPOD_INTEGRATION.md). Folosește cheia API și endpointurile tale
în Setări, verifică conexiunea, apoi selectează modelele disponibile. Nu a fost pornit niciun GPU.
Modelele locale ComfyUI au fost dezinstalate în etapa precedentă.

## Ce s-a verificat prin scenarii

Cei opt agenți au fost testați cu modelele reale: verificare independentă a faptelor,
contradicții, instrucțiuni injectate în surse, buget insuficient, STOP, pauză și upload cu
rezultat necunoscut. Scenariul factual a fost rescris și acceptat. Serialul a trecut la
ultimul draft, dar după prea multe rescrieri pentru fluxul autonom obișnuit; versiunile
necorespunzătoare au fost oprite înainte de producție. Proba cu cele două încercări normale
a rămas respinsă; un model alternativ a expirat și nu a fost promovat. Nu au fost consumate
resurse RunPod.
Rezultatele, corecțiile și limitele sunt în [AGENT_SCENARIO_REPORT.md](AGENT_SCENARIO_REPORT.md).
Configurația reală raportează momentan DEGRADED: nu este ales serviciul pentru imagini și
`STUDIO_AGENT_DAILY_TOKEN_BUDGET` nu este setat. Plafonul de tokeni este suplimentar bugetului
în USD și se pune în `.env`, cu o limită aleasă pentru rularea zilnică. Referințele personajelor
pentru filme se configurează separat de personajele deja animate în interfață.


## Unde se află codul esențial

| Componentă | Fișiere |
|---|---|
| Decor, birouri și personaje | `frontend/src/pixel_office.js`, `pixel_desks.js`, `pixel_people.js`, `pixel_studio.css` |
| Repartizarea birourilor | `config/pixel_office.json`, `backend/app/office/services.py` |
| Rezumatul autonomiei | `frontend/src/autonomy_overview.js` |
| Meniuri și conversații | `frontend/src/main.js`, `frontend/src/settings.js` |
| Bugete și costuri | `backend/app/economy/router.py`, `budget.py`, `prices.py` |
| Lucru automat | `backend/app/workflows/`, `backend/app/runbook/` |
| RunPod | `backend/app/providers/runpod/` |

Datele și materialele produse rămân în locațiile existente. Vechile registre financiare și
surse grafice sunt păstrate pentru recuperare; interfața curentă nu le folosește.
