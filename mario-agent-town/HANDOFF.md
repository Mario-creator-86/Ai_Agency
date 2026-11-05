# Preluare proiect — Mario Agent Town

## Actualizare v3 — oraș viu, ședințe, angajări — 5 noiembrie 2026

Cerut de Mario. Higgsfield NU a fost folosit (fără credite; Mario a cerut explicit să lucrăm cu grafica ChatGPT). Nicio casă nu a fost redesenată și nimic nu a fost generat la 4K.

**Roluri (mapare aleasă de Mario):** Maria YouTube · Ana inbox & email · Irina money · Radu research · David products · Tudor family · Victor trading (casa ceasului) · Sofia AI news · Elena outreach · Alex Chief of Staff în Town Hall. Casa-studio din dreapta jos a rămas anexa de producție YouTube (fără locatar). Casele pictate se potrivesc deja aproximativ cu meseriile noi; nu au decor nou pictat.

**Implementat și verificat offline (19/19 teste, Node 22.23 Linux) + inspectat în Chrome desktop/telefon:**
- `public/village-layout.js`: uși, curți, porți, obstacole (bănci, ghivece), recuzită plasată pe iarbă (testat: nicio piesă pe alei), coordonatele efectelor, sala Town Hall cu 12 scaune și locuri fixe (Mario în capul mesei, Alex la dreapta lui, scaunul de la capăt pentru candidați).
- `public/assets/props/*.webp`: cele 12 obiecte tăiate din atlasul ChatGPT, cu halo-ul colorat eliminat. Butoaie, lăzi și automatul retro „POP!” sunt desenate în cod.
- `public/town.js` (rescris): reguli de mișcare (lucru = merge acasă, intră pe ușă, ascuns + „lucrează la birou”; director liber = stă în curte și se plimbă; când Mario e aproape, se opresc și se uită la el; muncitorii hoinăresc și, la prima întâlnire din zi, se opresc, întreabă la ce lucrează celălalt și își notează; nimeni nu se teleportează, ocolire între personaje, A* + string-pulling); sala de ședințe desenată în cod cu personajele așezate (rândul „șezut” din sheet, picioarele sub masă); efecte: fum din 9 coșuri reale, apă în fântână și pârâu, steaguri fluturând (deformarea picturii), felinare și ferestre la noapte, ecrane pâlpâind, frunze, petale, păsări, licurici, zi/noapte după ora București (`?hour=21` pentru test); sunet ambiental foarte încet generat cu WebAudio (vânt, păsări rare, greieri noaptea). Fără foc: nu există șemineu vizibil în pictură.
- Server/runtime: `/api/meeting`, `/api/meeting/say` (toată sala sau o persoană), `/api/meeting/discuss` (runde + strategie salvată ca livrabil + sarcini), `/api/encounter` (notițe reale din tabla de sarcini fără AI; conversație AI dacă ambii au creier), `/api/staff/request|decide` (Alex propune, Mario decide; la „da”: folder `workspaces/<id>/` cu IDENTITY.md, INSTRUCTIONS.md, NOTES.md, agent nou cu creierul directorului), proiecte comune, ședință zilnică și conversații spontane (doar cu autonomia pornită).
- UI: buton „Convoacă ședința” în bara de sus, chat de ședință în stânga (redimensionabil, mărime poze/nume, pliabil pe telefon), alegerea creierului direct în profilul fiecărui personaj, tab Proiecte, sunet on/off.

**Limite reale:** candidații/angajații refolosesc un sheet existent cu o vestă galbenă pictată în cod (nu un sheet Higgsfield). Interioarele caselor nu există: „la birou” = personajul intră pe ușă și apare indicatorul. Mario nu are rând „șezut”: la masă e desenat în picioare cu masa acoperindu-l de la talie. Furnizorii reali (Codex 0.166.0 / Claude Code 2.1.318: flag-urile CLI au fost verificate cu `--help`, autentificarea nu) rămân neverificați live.

**Următorul pas:** pe PC-ul lui Mario, alege Claude Code sau Codex pentru doi agenți, convoacă ședința și apasă „Discutați”; verifică strategia salvată.

## Actualizare grafică v2 — 5 noiembrie 2026

Mario a respins aspectul geometric/pastel și a cerut un sat bogat în culori, cu volum și detalii ca în imaginile furnizate, apoi a precizat că dorește imaginile pregătite pentru continuarea în Claude. Au fost desenate: o hartă completă fără personaje în fundal; zece sprite sheet-uri distincte (16 cadre fiecare); atlas cu 12 clădiri; atlas de obiecte cu fântână, bancă, copaci, felinar, flori, pod și alte obiecte. Avatarul CEO cu fermoar este păstrat.

**Începe partea grafică din `art/README_CLAUDE.md` și `art/manifest.json`.** Harta și personajele sunt integrate în Canvas; galeria este `/art-preview.html`. `public/village-layout.js` înlocuiește coordonatele izometrice ale v1. Backendul și conturile nu au primit integrări noi.

Verificare: 12/12 teste offline trecute, inclusiv traseele fiecărei case spre piață și blocarea acoperișurilor/fântânii. Pagina și noua scenă cu toate cele zece personaje au fost inspectate în browser desktop. Atlasul de clădiri și cel de obiecte sunt disponibile pentru continuare, nu se dublează peste harta pictată. Interioarele nu sunt desenate; ședința rămâne în piață.


## Unde este proiectul

- Repository: `Mario-creator-86/Ai_Agency` (privat).
- Branch: `mario-agent-town`.
- Director: `mario-agent-town/`.
- Primul fișier de citit: acesta, apoi `AGENTS.md`, `README.md`, `PROJECT_STATE.json`.
- Data: 5 noiembrie 2026. Stadiu: prototip; integrarea live și întregul flux YouTube sunt încă de construit/verificat.

```sh
git clone --branch mario-agent-town --single-branch https://github.com/Mario-creator-86/Ai_Agency.git
cd Ai_Agency/mario-agent-town
node --version
npm test
npm start
```

Windows: Node 24+, apoi `start.cmd`. Fără `npm install`: nu există dependențe externe. Port 8012. Nu porni scriptul de la rădăcina Ai_Agency pentru acest proiect; acela pornește studioul AMN-AI existent.

## Cerințe confirmate de Mario

1. Oraș de tip joc: zece case individuale, toate legate prin alei de Town Hall. În centru parc cu bănci și fântână. Reședința CEO este cea mai mare.
2. Zece agenți autonomi, fiecare cu nume, identitate, personalitate și job clar, capabili să meargă și să comunice. Mario poate da ordine din chat individual sau general.
3. Maria administrează întregul canal YouTube spre ținta 1M: strategie, producție, marketing, postări și creștere; ținta nu este garantată. Ana gestionează email/calendar/întâlniri. Radu cercetează AI/bursă/subiecte relevante.
4. Ceilalți șapte: Alex (Chief of Staff), Elena (scenarii), Victor (video/design), David (engineering/automatizări), Irina (finanțe/piețe), Sofia (QA/fact-check), Tudor (cunoștințe/învățare). Contractele exacte sunt în `src/agents.mjs`.
5. Mario este CEO; avatar bazat pe fotografiile confirmate în conversație: cap ras, barbă grizonantă, pulover închis CU FERMOAR SCURT LA GÂT. Nu folosi fotografia mai veche a bărbatului cu păr scurt, explicit respinsă. Fotografiile originale nu sunt în Git.
6. Inteligența trebuie să folosească abonamentele ChatGPT/Claude prin aplicațiile lor oficiale, ori Ollama local/cloud. Nu introduce automat API-uri OpenAI/Anthropic plătite.
7. User a autorizat folosirea unui repository existent. Folosim branch separat și director separat, nu înlocuim studioul existent.
8. Referințe: CityRT și video YouTube `-mb6buCbv8E`. Transcriere integrală citită. Video prezintă case/agenți, chief of staff, deplasare, chat, sarcini și ședințe; playerul video în sine a rămas în buffering aici. Grafica v2 este o pictură RPG originală, cu personaje animate separat pe Canvas; nu este o captură copiată din video.

## Fișiere și flux

| Fișier | Responsabilitate |
| --- | --- |
| `server.mjs` | HTTP local, API JSON, SSE, verificare Host/Origin, fișiere statice |
| `src/store.mjs` | SQLite: setări, mesaje, sarcini, memorie, artefacte, evenimente, execuții |
| `src/runtime.mjs` | Coada, scheduler, context, runde AI, instrumente validate, delegare, STOP |
| `src/providers.mjs` | Codex CLI, Claude Code CLI, Ollama local/cloud, detectare instalări |
| `src/agents.mjs` | Cele zece identități, case, misiuni, KPI, obiective autonome |
| `public/town.js` | Pictură RPG, sprites separate, efecte decorative, mișcare și orientare; geometria/A* sunt în village-layout.js |
| `public/app.js` | Chat, misiuni, jurnal/livrabile, setări, SSE |
| `public/assets/mario-sprites.webp` | Sprite 4 coloane × 3 rânduri; versiunea cu fermoar |
| `tests/core.test.mjs` | Douăsprezece teste fără conturi sau plăți |

Rutare: chat general → Alex sau agenții menționați cu `@id`; chat direct → agentul ales. O singură execuție simultană. Răspunsul furnizorului conține `reply` și maximum șase `actions`. Instrumente: `remember`, `write_artifact`, `create_task`, `send_message` intern, `read_feed`, `read_artifact`. Maximum trei runde de model per execuție și două niveluri de delegare. Joburile de chat sunt în memorie; sarcinile propriu-zise sunt persistate și reîncărcate după restart.

Autonomia este oprită implicit, furnizorii sunt Demo. Mișcarea locală nu folosește AI și nu indică muncă efectuată. UI etichetează configurația, fără a declara furnizorul autentificat doar pentru că binarul există.

## Verificări efectuate

- `npm test`: **12/12 trecute** pe Node 24.22.1, Linux. Testele acoperă unicitatea rolurilor, persistență/restart, demo fără apeluri, artefacte și delegare cu model fals, limitele de instrumente/delegare, STOP înaintea mutațiilor, plafon zilnic, eliminarea cheilor API din mediul CLI și parsarea erorilor.
- Verificări de sintaxă JavaScript executate în dezvoltare; repetă pentru toate fișierele înainte de modificări.
- Avatarul cu fermoar a fost inspectat vizual înaintea optimizării assetului.
- Prima încercare de preview a eșuat deoarece serverul nu interpreta argumentele `--host/--port` ale mediului. A fost adăugat suport și preview-ul a pornit. Verificare browser desktop reușită: hartă, avatar CEO, chat Maria cu răspuns Demo corect etichetat, control ședință și setări/diagnostic furnizori. Mobilul și furnizorii live nu au fost testați.
- Nicio execuție reală ChatGPT/Codex, Claude, Ollama, email, calendar, YouTube sau FFmpeg nu a fost demonstrată aici. Nu transforma testele cu modele false în afirmații de integrare live.
- Suita studioului AMN-AI părinte nu a fost executată: codul său nu este modificat, acesta este un proiect nou izolat.

## Pași clari de continuare, în ordine

### 1. Verifică interfața pe PC-ul Owner

Pornește pe o bază temporară (`TOWN_DATA_DIR`) sau într-un checkout nou. Verifică layout desktop/mobil, exact 11 case (10 agenți + CEO) și un Town Hall, parc, patru bănci și fântână. Verifică mișcarea CEO, pereții, mersul agenților, Alex, orientarea spre CEO și ședința. Verifică alinierea sprite-urilor pe toate direcțiile și ținuta cu fermoar. Nu redesena fotografia.

### 2. Confirmă un singur furnizor live, apoi extinde

Instalează/autentifică aplicația oficială locală. Începe cu un agent, un mesaj scurt și un singur artefact. Pentru Codex verifică loginul ChatGPT; pentru Claude verifică abonamentul în aplicația oficială. Ollama poate folosi un model local sau cloud după autentificare. Păstrează limitele mici. Înregistrează versiunea CLI/modelul, comanda și rezultatul, fără tokenuri. Nu instala un proxy OAuth neoficial și nu copia credentiale în oraș. Verifică termenii curenți pentru orchestrarea prin abonamente; nu promite acces nelimitat.

### 3. Întărește execuția înainte de autonomie de lungă durată

Persistă joburile de chat, nu doar sarcinile. Adaugă idempotency keys pentru acțiuni și deduplicare la replay: un crash după un efect poate relua o sarcină. Adaugă lease unic pe bază, pentru a preveni două procese pe același fișier. Înregistrează numărul real de cereri/tokens dacă furnizorul îl expune; acum limita este per execuție, maximum trei cereri. Adaugă backoff/circuit breaker pentru cote. Păstrează STOP persistent și verifică anularea înaintea fiecărui efect.

### 4. Reutilizează integrările existente printr-un bridge explicit

Repository-ul părinte are FastAPI, vault, politici, research/media și YouTube. Citește instrucțiunile părintelui și modulele relevante înainte de integrare. Evaluează un bridge HTTP/MCP între oraș și AMN-AI, păstrând autentificările, jurnalul, bugetele și proveniența. Nu copia secrete și nu șterge backendul existent. Dacă devine integrare de produs, documentează migrarea și compatibilitatea; nu lăsa două sisteme să publice același video.

### 5. Conectează conturile, pe rând

Ana: stabilește Gmail versus Outlook, implementează OAuth oficial, începe cu read-only și drafturi; calendar cu verificare de disponibilitate. Maria: stabilește canalul exact, conectează YouTube/Analytics, citește metrici reale și pregătește o primă livrare. Scopurile OAuth și acțiunile permise trebuie configurate de Owner. Conturile conectate în această conversație nu sunt automat accesibile aplicației locale.

### 6. Construiește fluxul complet pentru Maria

Brief → research și surse → scenariu Elena → review Sofia → asseturi și voice-over Victor → randare reală FFmpeg → QC → upload YouTube → verificare ID/status remote → analytics. Marchează explicit pașii blocați când lipsesc capabilități. Adaugă buget, scheduler durabil și prevenirea publicării duplicate. Autonomia largă cerută de Owner se aplică în limitele capabilităților și permisiunilor efectiv configurate; nu pretinde că rolul scris echivalează cu o integrare funcțională.

### 7. Închide milestone-ul cu dovadă

Un agent real produce un livrabil persistat; doi colaborează real; un restart păstrează sarcinile; STOP oprește efectele; apoi un video real privat ajunge într-un cont de test autorizat și ID-ul remote este verificat. Abia apoi descrie sistemul drept capabil de administrare autonomă YouTube. Păstrează retrospectiva scurtă și următorul task exact în acest document.

## Limite și riscuri cunoscute

- Nu este un runtime de producție și nu este un serviciu multiutilizator. Nu expune portul public.
- Personajele se pot suprapune între ele; A* evită casele/fântâna, nu rezervă dinamic spațiul între persoane. Interioarele caselor/Town Hall nu sunt construite; ședința este în fața clădirii.
- Mișcarea și camera sunt în browser. Poziția CEO este raportată serverului, dar nu este persistată în SQLite. Nu influențează rezultatele muncii.
- Nu există încă cifrare la nivel de aplicație pentru documentele din SQLite; nu stoca secrete în chat sau memorie.
- Joburile sunt seriale. Nu există failover automat, măsurare a calității modelului, căutare bursieră live sau acces arbitrar la browser/shell.
- Consumatorii CLI au fost implementați după documentația oficială, dar trebuie validați împreună cu versiunile și abonamentele Owner pe Windows.
- Plafonul zilnic folosește ziua locală a procesului server. Configurează fusul Europe/Bucharest pe PC.
- Exportul JSON nu este un restore. Backupul complet se face cu procesul oprit și întreg directorul `data/`.

## Prompt scurt pentru următorul AI

> Continuă proiectul Mario Agent Town din repository-ul Mario-creator-86/Ai_Agency, branch mario-agent-town, folder mario-agent-town/. Citește AGENTS.md, HANDOFF.md și PROJECT_STATE.json. Nu modifica studioul AMN-AI existent. Rulează baseline-ul, verifică interfața și fă mai întâi acceptanța unui singur agent prin Codex/Claude Code autentificat oficial sau Ollama. Păstrează identitatea CEO și puloverul cu fermoar. Nu pretinde că YouTube/email/calendar funcționează până la o integrare și verificare reale. Actualizează handoff-ul cu dovezi și următorul pas.
