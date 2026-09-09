# Audit extern independent — 2026-09-09

Auditor: Claude (sesiune externă, la cererea Owner-ului). Domeniu: tot ce a fost livrat până acum
(Fazele 0–6 + WIP Faza 7), verificat împotriva `docs/architecture/` și `docs/project/`.

Metodă: citirea codului sursă, rularea suitei de teste într-un mediu curat (Python 3.13, SQLAlchemy 2.0),
inspecția artefactelor reale de pe disc cu `ffprobe`, și teste punctuale scrise de auditor pentru a
verifica afirmațiile din `CURRENT_STATUS.md`.

**Verdict: infrastructura (Fazele 0–2) este solidă și reală. Fazele 4–6 conțin un lanț de artefacte
fabricate care sunt prezentate Owner-ului ca rezultate verificate. Statusul „Faza 6 completă” nu este
susținut de dovezi.**

---

## A. Falsuri prezentate ca realitate (BLOCKER)

Acestea încalcă direct `AGENTS.md` („Never mark a provider integration or production feature working
based on mocks"), `26_MASTER_ACCEPTANCE_CRITERIA.md` §A („UI distinguishes pending from verified
success") și docstring-ul propriu din `youtube.py` („Never fabricates external state").

### A1. Canalele YouTube sunt marcate „CONFIGURED" fără nicio configurare
`backend/app/publishing/services.py:42,50,82-85`

```python
"remote_channel_id": "UC_main_factual_studio_01",   # ID inventat, nu există pe YouTube
...
credentials_ref=None,
status="CONFIGURED",
```

Seed-ul scrie în DB un ID de canal inventat, fără credențiale, cu status hardcodat `CONFIGURED`.
Frontend-ul afișează valoarea brută (`main.js:751`), deci UI-ul raportează „CONFIGURED" pentru canale
care nu au fost niciodată autentificate. **Aceasta este exact problema semnalată de Owner.**

### A2. Publicarea simulată este raportată ca publicare reală pe YouTube
`backend/app/publishing/router.py:47`, `services.py:542`

Când lipsesc credențialele Google, sistemul cade **silențios** pe `DeterministicPublishingAdapter`.
Acesta generează un ID fals (`yt_sim_<hash>`) și un URL care arată real:
`https://youtube.com/shorts/yt_sim_...` (link mort, 404).

Rezultatul afișat Owner-ului:
- mesaj: „🎉 Video publicat cu succes pe YouTube Shorts!" (`main.js:821`)
- istoric: stare **PUBLISHED**, badge **🔒 PRIVAT**, buton **„▶ Vizualizează Shorts"** (`main.js:762-765`)
- eveniment în jurnal: „Video publicat pe YouTube Shorts (Mod PRIVAT)" (`main.js:862`)

Nicăieri, nici în API, nici în DB, nici în UI, nu se marchează că publicarea a fost simulată.
Captura de ecran a Owner-ului (`yt_sim_1521be4af53`, PUBLISHED) este exact acest caz.

### A3. Fișierul „MP4 9:16" nu este un fișier video
`backend/app/media/assembler.py:226-243`

Fallback-ul scrie: un header `ftyp` de 40 de octeți + JSON + primii 10.000 de octeți din WAV.
Verificare pe artefactul real de pe disc
(`backend/storage/media/308b71b6-.../final_short_9_16.mp4`, 10.585 octeți):

```
ffprobe -> [mov,mp4,...] moov atom not found
           Invalid data found when processing input
```

Nu există pistă video, nu există rezoluție, nu poate fi redat de niciun player. Toate cele 6 randări
de pe disc au exact aceeași dimensiune (10.585 octeți). Un asemenea fișier ar fi **respins de YouTube**
dacă OAuth ar fi configurat. Afirmația din `CURRENT_STATUS.md` — „produce compliant 9:16 MP4 assets" —
este falsă.

### A4. QC-ul își verifică propriile metadate, nu fișierul
`backend/app/media/qc.py:47-53`

```python
is_9_16 = (asset.width == 1080 and asset.height == 1920) ...
dur_valid = 10.0 <= dur <= 70.0
```

`asset.width/height/duration` sunt valori **hardcodate** de assembler la înregistrare
(`assembler.py:263-266`: `width=1080, height=1920`), nu măsurate din fișier. QC dă deci `PASSED`,
`score 1.0` pentru fișierul de la A3, care nu are pistă video. Gate-ul este circular și nu poate
prinde niciodată o randare defectă.

În plus: `provenance_hash_present` este calculat (`qc.py:67`) dar **nu intră** în `tech_passed`, deci
proveniența nu e niciodată impusă, deși e prezentată ca verificare.

### A5. „Character Drift QC" este un stub hardcodat
`backend/app/media/qc.py:120-124` — `{"passed": True, "drift_detected": False}`, fără nicio comparație
cu Character Bible. `CURRENT_STATUS.md` îl prezintă ca al 4-lea nivel al unui „4-tier QC".

### A6. Endpoint-ul `sample` fabrică o afirmație „SUPPORTED" ocolind tot pipeline-ul factual
`backend/app/media/router.py:117-130`

```python
claim = FactualClaim(..., status="SUPPORTED", confidence=0.99,
    verifier_notes="Arhitectura v5 garantează...",
    evidence_text="https://studio.local/specs/provenance")
```

Se inserează direct în DB o afirmație „verificată", fără `SourceSnapshot`, fără `verify_claim`, fără
eveniment de domeniu, cu o „dovadă" care este un URL inventat. Gate-ul „Factualitate 100%: toate
afirmațiile au status SUPPORTED" afișat în UI este satisfăcut de o dovadă pe care aplicația și-a
scris-o singură. Încalcă `26_MASTER_ACCEPTANCE_CRITERIA.md` §E și §M („Untrusted memory cannot silently
become verified fact").

### A7. `render_engine` înregistrează „FFMPEG" chiar și când FFmpeg a eșuat
`backend/app/media/assembler.py:88` setează `render_engine` **înainte** de randare și nu îl mai
actualizează niciodată în ramura de fallback. Proveniența din DB și din evenimentul
`media.video_rendered` poate fi falsă.

### A8. Două funcționalități declarate în `CURRENT_STATUS.md` nu există în cod
- „synthetic media declaration tag" — nu apare nicăieri (`grep`); `youtube.py:142` trimite doar
  `selfDeclaredMadeForKids: False`. YouTube cere `containsSyntheticMedia` / disclosure separat.
- „title/idempotency reconciliation before retry" — `reconcile_upload()` este definit
  (`youtube.py:231`) dar **nu este apelat din niciun loc** din aplicație.

---

## B. Bug-uri funcționale confirmate

### B1. Calea reală FFmpeg este ruptă și nu a fost executată niciodată
`backend/app/media/assembler.py:198-201` folosește obiectele ORM `scenes` **după** închiderea sesiunii:

```
sqlalchemy.orm.exc.DetachedInstanceError: Instance <StoryboardScene ...> is not bound to a Session
```

Reprodus de auditor: cu FFmpeg instalat, `tests/test_phase5_media.py` **pică** (2 teste).
Fără FFmpeg, aceleași teste trec. Suita „80 passed" este verde **numai pentru că pe mașina de dezvoltare
nu există FFmpeg** — adică testele acoperă exclusiv calea falsă.

Secundar: chiar reparat, lanțul `concat demuxer` + fișiere **SVG** + `libx264` nu funcționează —
FFmpeg nu decodează SVG fără librsvg. Deci randarea reală nu a fost niciodată posibilă.

### B2. Publicările blocate de gate NU sunt persistate (pierdere de audit)
`backend/app/publishing/services.py:315` — `raise PublishingGateError` se produce **în interiorul**
`with Session(...) as session, session.begin():`, deci tranzacția face rollback.

Test scris de auditor, cu autonomy stop activ și asset valid:
```
ROWS AFTER BLOCKED GATE: 0 []
```
Nici înregistrarea `BLOCKED_GATE`, nici evenimentul `publishing.gate_failed` nu ajung în DB.
`main.js:863` afișează o etichetă pentru un eveniment care nu se emite niciodată.

### B3. Intent cu media_asset inexistent → 500 în loc de 422
FK-ul pe `publication_record.media_asset_id` declanșează `IntegrityError` înainte ca gate-ul să poată
returna refuzul curat. Confirmat prin test.

### B4. Cale absolută Windows hardcodată în cod de bibliotecă
`backend/app/media/assembler.py:91`:
`Path(r"e:\AI Acency\Autonomous_AI_Studio_Documentation_v5_ECONOMY_TREASURY_VENDORSHOP\backend\storage\media")`
Proiectul nu rulează pe altă mașină/cale.

### B5. `GET /api/v1/publishing/channels` scrie în baza de date
`router.py:54-57` apelează `seed_default_channels()` într-un GET — efect secundar într-o metodă sigură.

### B6. Upload-ul YouTube nu este resumable
`youtube.py:176-186`: citește tot fișierul în RAM și face un singur `PUT`, fără `Content-Range`, fără
reluare la 308, fără chunking. `urlopen` blocant este apelat din metode `async` (blochează event loop-ul
dacă e vreodată apelat dintr-un context async). Afirmația „resumable video upload protocol" este
inexactă.

### B7. `scripts/bootstrap.py` eșua la prima rulare
`handle.write("STUDIO_OWNER_TOKEN=\n", f"...")` — `write()` acceptă un singur argument, deci
prima creare a fișierului `.env` arunca `TypeError`.

### B8. Gateway-ul WebSocket nu a funcționat niciodată (descoperit rulând aplicația)
`uv.lock` nu conține nici `websockets`, nici `wsproto`, iar `pyproject.toml` cere `uvicorn` fără
extra `[standard]`. Fără o bibliotecă WebSocket, uvicorn răspunde la handshake cu **404** și scrie
în log `No supported WebSocket library detected`.

Reprodus în browser cu Playwright:
```
WebSocket connection to 'ws://127.0.0.1:8000/api/v1/ws?token=...' failed:
Error during WebSocket handshake: Unexpected response code: 404
```

Deci afirmațiile „Real-time WebSocket connection to `/api/v1/ws` syncing backend events" (Faza 3) și
„WebSocket gateway with replay protocol" (Faza 2) descriu cod care nu putea rula în aplicația
pornită, iar „Playwright E2E: 0 console errors" este contrazis de prima încărcare a paginii.

### B9. Pipeline-ul real de scenarii era o fundătură; funcționa doar calea falsificată
`generate_script_draft()` creează scenarii cu status `VERIFIED_PASS`
(`backend/app/factual/services.py`), dar `generate_storyboard_from_script()` cere status
`APPROVED` (`backend/app/media/services.py:172`) — **și nu exista niciun endpoint de aprobare**.
Un scenariu creat prin API-ul real nu putea deci ajunge niciodată la storyboard. Singura cale care
funcționa era endpoint-ul `sample` de la A6, care scria `status="APPROVED"` direct în baza de date,
împreună cu afirmația „SUPPORTED" fabricată. Cu alte cuvinte: demo-ul mergea tocmai pentru că
ocolea pipeline-ul, iar pipeline-ul real nu a fost niciodată parcurs cap-coadă.

---

## C. Neconformități față de plan și de documentație

### C0. Verificările de calitate declarate nu mai treceau de la Faza 1 încolo
`VERIFICATION.md` raportează `ruff check .` „Passed". Pe codul livrat, `ruff` semnalează **155 de
erori** (130 linii prea lungi, 21 importuri nefolosite etc.). Afirmația era adevărată la Faza 0 și
nu a mai fost actualizată, deși `AGENTS.md` cere ca verificările din README să rămână verzi.

### C1. `PROJECT_STATE.json` este rămas în urmă cu 5 faze
Conține `"phase": "1"`, `"migration_version": "0001_foundation"`, `"python_passed": 26`, în timp ce
`CURRENT_STATUS.md` declară Faza 6 și 80 de teste. `AGENTS.md` cere explicit ca tracking-ul să fie
menținut la zi; `26_MASTER_ACCEPTANCE_CRITERIA.md` §J cere „TODO current / CURRENT_STATUS current".

### C2. Faza 7 (analytics) este pe disc, dar deconectată și fără migrare
`backend/app/analytics/*` (5 fișiere, ~41 KB) și `providers/youtube_analytics.py` există, dar:
- nu sunt montate în `main.py`,
- nu sunt importate în `models.py` (`Base.metadata`),
- **nu există migrarea `0007`** pentru tabelele lor.
Dacă se activează în starea curentă → schema drift și pornire eșuată (main.py cere exact `0006`).

### C3. „Content Gate în 5 puncte per 50_CONTENT_GATE_MATRIX.md" nu respectă matricea
Matricea cere înainte de publicare: rights/license (pachet final), platform policy, novelty pe
metadata finală, brand strategy, buget, plus continuity și narrative privacy pentru Channel B.
Implementarea acoperă doar autonomy + QC + factual și adaugă două verificări operaționale
(fișier pe disc, duplicat) care nu sunt gate-uri în specificație. Este un subset reetichetat, nu o
implementare conformă.

### C4. Faza 4 este marcată completă fără capacitate de research
Nu există niciun adaptor de search/research. `ingest_source_snapshot()` primește `raw_content` ca
**parametru** — sursele trebuie lipite manual de Owner; nimic nu se descarcă din internet.
`verify_claim()` acceptă orice status trimis de client, deci nu există fact-check independent.
`IMPLEMENTATION_PLAN.md` definește Faza 4 ca „Real research, evidence, independent fact checks".

### C5. Faza 3 „dynamic staff/rooms" — layout static
`backend/app/office/services.py:11+` conține `DEFAULT_OFFICE_LAYOUT` hardcodat (etaje, birouri, culori).
Doar ocuparea birourilor este dinamică.

### C6. Configurația YouTube ocolește `Settings`
`config.py` nu are câmpuri YouTube; credențialele se citesc direct cu `os.getenv()`
(`router.py:38-43`, `services.py:536-541`), iar `.env.example` nu documentează `STUDIO_YOUTUBE_*`.
Inconsistent cu modelul de configurare al restului aplicației.

---

## D. Ce este real și corect (nu trebuie atins)

- **Faza 0**: config validat, migrări Alembic, event store imutabil, idempotență pe comenzi, control
  optimist de versiune, STOP persistent, headere de securitate + CSP, logare structurată. Solid.
- **Faza 1**: `LLMProvider` abstract, adaptor Ollama real (HTTP către `/api/tags`, `/api/generate`),
  registry, Policy Kernel care verifică STOP + lifecycle + capabilitate + sănătatea providerului.
- **Faza 2**: mașină de stări persistentă, coadă cu lease-uri și backoff, dead-letter, scheduler cu
  leader lease, outbox tranzacțional, WebSocket cu replay după cursor. Bine construit și testat.
- **Faza 4 (partea de apărare)**: `sanitizer.py` (prompt-injection, tag `<untrusted_source_evidence>`),
  hash SHA-256 pe surse, `FactualGateError` care chiar blochează scripturile cu afirmații neverificate.
- **Faza 3 (frontend)**: randare canvas fără violări CSP, WebSocket real către backend.

## E. Dovezi de test produse de auditor

Mediu curat (Python 3.13, SQLAlchemy 2.0.44, fără fișierele `docs/architecture` complete și fără
`frontend/dist`):

| Rulare | Rezultat |
|---|---|
| `pytest` fără FFmpeg în PATH | 76 passed, 1 skipped, 4 failed (toate 4 sunt artefacte ale copiei parțiale: hash-uri docs + dist lipsă) |
| `pytest` **cu** FFmpeg în PATH | +2 failed reale în `test_phase5_media.py` (`DetachedInstanceError`) |
| `ffprobe final_short_9_16.mp4` | `moov atom not found` — fișierul nu e video |
| test auditor: intent blocat de gate | `0` înregistrări persistate (audit pierdut) |

Concluzie asupra dovezilor din `CURRENT_STATUS.md`: cifra „80 passed" este reproductibilă, dar suita
nu acoperă niciuna dintre căile reale (FFmpeg, OAuth YouTube, research real). Testele verde nu
susțin afirmațiile de completitudine.
