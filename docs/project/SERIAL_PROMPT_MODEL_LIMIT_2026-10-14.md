# Limita prompturilor serialului — 14 octombrie 2026

Owner cere limita permisă de traseul modelului, fără scurtarea locală la 980 de caractere.
Configurația serialului este versiunea 3 și permite 20.000 de caractere: aceeași limită ca
cererea `ImageRequest` și contractul workerului `runpod_worker.contract.MAX_PROMPT`.
Loaderul nu mai reduce configurația la 2.000 de caractere. Stilul artistic rămâne același.

Aceasta este limita verificată a cererii pe traseul GPU, nu o promisiune că un prompt de
20.000 de caractere produce o imagine bună. Workflow-urile existente folosesc Qwen-Image-2512
și Qwen-Image-Edit-2511 prin ComfyUI. În sursa ComfyUI fixată de proiect nu există tăierea
la 980/1.000 de caractere în tokenizerul Qwen:
[sursa oficială la commitul fixat](https://github.com/Comfy-Org/ComfyUI/blob/3c1b7a17fdf239d35ce98cc777756f572d089795/comfy/text_encoders/qwen_image.py).
Limitele de context în tokeni și comportamentul imaginii nu sunt certificate prin aceste
teste locale; nu s-a pornit infrastructură și nu s-a trimis o generare plătită.

## Schimbarea

Compozitorul păstrează descrierea personajelor, primul moment al fiecărei acțiuni,
expresia, fundalul și continuitatea. Nu taie textul ca să încapă. Dacă rezultatul depășește
limita, verificarea produce `OVER_CAP`, iar cererea este oprită pentru reformulare.
Separarea primului cadru de momentele ulterioare rămâne: acestea aparțin clipului.

Lint-ul recunoaște modelele din contractul workerului și măsoară caracterele în aceeași
unitate ca cererea. Termenii expliciți ai altui furnizor au prioritate; fallback-ul Runway
de 1.000 unități UTF-16 rămâne pentru traseele care îl folosesc. Foaia de filmare transmite
modelul imaginii și modelul video, iar verificarea unei rescrieri de serial folosește noua
limită a imaginii. Etapele inițiale de imagini și de regenerare primesc și ele modelul
imaginii în lint, ca să nu reintroducă implicit limita Runway de 1.000. Agenții primesc
noul plafon și instrucțiunea de a păstra condițiile.

Verificarea extinsă a reprodus două eșecuri și în codul comis anterior: o clauză cu `then`
ștergea vecinii independenți, iar limita de 14 cuvinte pentru mișcarea mediului ștergea
condiția că liniile creionului rămân vizibile. Corecturile păstrează clauzele independente
și propoziția completă, fără să rupă listele de obiecte ori domeniul unei negații.

## Dovezi din filmul existent

Snapshot citit fără scriere: `Storyboard: The Zero Script Club`,
`f06808c9-40d4-4f40-a980-84b6a5540348`. Textele exacte înainte/după sunt în
`SERIAL_PROMPT_MODEL_LIMIT_2026-10-14.json`; „după” este recompunere locală, neaplicată în DB.

| Scenă | Caractere înainte | După | Condiții pierdute înainte | După |
|---|---:|---:|---:|---:|
| 1 | 973 | 1838 | 1 | 0 |
| 2 | 965 | 1933 | 2 | 0 |
| 3 | 974 | 1922 | 2 | 0 |
| 4 | 976 | 1762 | 1 | 0 |
| 5 | 972 | 1800 | 1 | 0 |
| 6 | 979 | 1877 | 3 | 0 |
| 7 | 973 | 1921 | 3 | 0 |
| 8 | 980 | 1429 | 0 | 0 |

Total: 13 pierderi obligatorii → 0. Acesta este un rezultat de compunere și validare;
imaginile noi și acceptarea lor vizuală nu sunt încă demonstrate.

## Verificare și activare

Cele 15 regresii noi verifică actorii/acțiunile complete, plafonul loaderului, condițiile
lungi păstrate pentru refuz explicit, caracterele Unicode, limita exactă a cererii și
transferul identic până la nodurile ambelor workflow-uri Qwen. Două teste trec prin
etapa efectivă de imagini cu 2.673 de caractere până la aprobarea normală, fără generare.
Aceleași teste, rulate separat cu implementarea HEAD, pică la limita veche de 1.000.
Suita extinsă de compunere/rescriere/foaie/contract: 249 teste trecute; după conectarea
etapelor de imagini și redo: 80 teste trecute (cu suprapunere față de suita anterioară).
Reverificarea finală a celor 15 regresii noi a trecut. Ruff/format, mypy pe cele cinci
module de prompturi, diferențele Git și integritatea documentației au trecut.
Scanarea secretelor: 1.296 fișiere, doar rezultate deja revizuite; reverificarea finală
a celor 17 fișiere schimbate nu are rezultate noi. Rezultatul este și în `CURRENT_STATUS.md`.

La ultima verificare, serverul nu răspundea pe portul 8000 și nu existau rulări de agenți
sau generări GPU active. Nu s-a schimbat această stare. Codul nou se încarcă la următoarea
pornire; versiunea 3 declanșează descrierea normală a scenelor deschise, prin fluxul existent.
Nu copiați propunerile offline direct în scene și nu modificați acceptările, bugetele ori
filmele închise. Sarah continuă să verifice corectura înaintea unei regenerări.

Revenire: restaurați fișierele acestei schimbări din Git. Oprirea buclei de acceptare la
Kelvin și bugetul depășit al serialului sunt probleme separate, neadresate aici.
