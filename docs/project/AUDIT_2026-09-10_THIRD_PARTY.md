# Audit independent al lucrărilor făcute de ceilalți AI — 2026-09-10

Verificare făcută pe o copie curată a proiectului, rulând eu însumi fiecare test și citind
codul nou linie cu linie. **Nu am luat de bun nimic din documentele de urmărire** (CURRENT_STATUS,
PROJECT_STATE, CHANGELOG): fiecare afirmație de mai jos e verificată direct.

## Verdict scurt

Munca celorlalți AI (Codex și ZCode) este, în cea mai mare parte, **onestă și de calitate bună**.
Am găsit **o singură minciună reală** — dar exact din specia pe care ai reclamat-o de la început
("scrie configured, dar nu e configurat") — și am corectat-o. Restul sunt inexactități în
documentele de urmărire și o zonă de cod mort.

## A. Ce am verificat eu, nu ce scrie în documente

| Verificare | Rezultat |
|---|---|
| `pytest` | 146 trecute, 1 sărită (înainte de modificările mele) |
| `ruff check .` | curat |
| `ruff format --check .` | curat |
| `mypy` | curat, 69 fișiere |
| `tsc -p tsconfig.json` | curat |
| `npm test` (frontend) | 11 trecute |
| `npm run build` | reușit |
| Integritatea documentației (hash SHA-256) | trecută, toate cele 83 de documente |
| Playwright — E2E post-audit | 27/27 |
| Playwright — design și contrast | 14/14 |
| Playwright — fullscreen și butoane | 10/10 |

**Nicio regresie.** Toate cele 51 de verificări Playwright pe care le-am construit în sesiunea
anterioară trec în continuare după modificările lor.

## B. Defectul real găsit și reparat

### B1. Baza de date pretindea că furnizorul Ollama e „HEALTHY" fără să-l fi contactat vreodată

`seed_initial_workforce` scria, la bootstrap, fără niciun apel de rețea:

- `provider_record`: `local-ollama` cu `status = 'HEALTHY'` și `last_health_check = <acum>`;
- `model_record`: trei modele cu `is_available = 1`, `last_verified = <acum>` și
  `discovery_method = 'DECLARED_BY_PROVIDER'`.

**Dovada:** am pornit studioul pe o mașină fără Ollama instalat. `curl` pe `/api/v1/providers/`
returna `"status":"HEALTHY"` cu un timestamp precis de health-check, iar cele trei modele apăreau
verificate. Nimic nu contactase Ollama.

Este exact tiparul pe care l-ai reclamat tu la canalul YouTube, reprodus în alt subsistem.

**Agravant:** furnizorul respectiv nu avea niciun adaptor înregistrat la pornire, deci și
verificarea și sincronizarea modelelor eșuau cu „no adapter registered" — adică **nu aveai nicio
cale să înlocuiești minciuna cu adevărul**. Iar orice agent alocat pe acele modele „disponibile"
eșua la execuție cu același mesaj, în timp ce interfața spunea că modelul e gata.

**Ce am făcut:**

1. Seed-ul scrie acum doar *intenție*: furnizorul `NOT_CONFIGURED`, fără timestamp; modelele
   `is_available = False`, fără `last_verified`, cu `discovery_method = 'SEEDED_UNVERIFIED'` —
   o valoare nouă care spune adevărul: lista vine din configurație, nu de la furnizor.
2. `sync_provider_models` — singurul cod care chiar sună endpoint-ul — e acum singurul care
   poate scrie `HEALTHY`, `last_verified` sau `DECLARED_BY_PROVIDER`.
3. Ai un buton care funcționează: adaptorul se înregistrează la pornire, `GET /settings` întoarce
   furnizorii moșteniți, iar Settings afișează un card cu „Verifică și încarcă modelele". Până
   îl apeși, cardul spune explicit că endpoint-ul nu a fost contactat niciodată.
4. Dacă endpoint-ul nu răspunde primești 503 cu „Furnizorul nu a răspuns, deci nu s-a înregistrat
   niciun model", nu un 500 generic.
5. Migrarea `0009_unverified_seeded_provider` retrage afirmația și din bazele de date existente.

Șase teste noi de guvernanță plus o suită Playwright nouă (`verify_provider_honesty.mjs`, 8/8)
blochează revenirea defectului.

## C. Inexactități în documentele de urmărire (nu în produs)

1. **`PROJECT_STATE.json` raporta greșit testele:** scria `python_passed: 137, python_skipped: 3`;
   realitatea era 146 trecute, 1 sărită. Corectat la 152/1 după modificările mele.
2. **`configured_provider_names: ["ollama (Ollama Cloud, VERIFIED)"]`** — o afirmație despre
   starea unei mașini anume, scrisă ca și cum ar fi o proprietate a proiectului. Golită: starea
   reală se citește acum din Settings, unde e măsurată.
3. **Blocantul despre analytics era formulat prea blând.** Vezi D de mai jos.

## D. Cod mort: modulul Analytics (Faza 7)

Aproximativ 40 KB de cod există pe disc și trece de ruff, mypy și pytest, dar **nu rulează
niciodată**:

- `backend/app/analytics/` (models 6,8 KB · services 25,6 KB · router 5,9 KB · schemas 3,1 KB)
- `backend/app/providers/analytics_base.py`, `deterministic_analytics.py`, `youtube_analytics.py`

`main.py` nu importă și nu montează routerul; modelele nu sunt în `Base.metadata`; nicio migrare
nu creează tabelele. Verificat prin `grep` pe `main.py`, `models.py`, `migrations/env.py` și pe
toate migrările. Nu e o minciună — `PROJECT_STATE.json` îl declara ca blocant — dar e o suprafață
mare de cod care poate crea impresia că funcționalitatea există. Următorul pas firesc: ori îl
cablezi complet cu migrare, ori îl scoți.

## E. Ce am verificat și am găsit corect (codul nou al celorlalți AI)

- **`integrations/vault.py`** — criptare Fernet, cheia împachetată cu DPAPI per-utilizator pe
  Windows. Corect pentru un desktop Windows. *Limitare de notat:* pe non-Windows cheia stă în
  clar lângă baza de date, deci criptarea nu protejează împotriva cuiva care copiază directorul.
- **`integrations/services.py`** — o conexiune salvată primește `SAVED`, `checked_at = None`,
  furnizorul `UNKNOWN` și modelele marcate indisponibile. „Salvat" nu înseamnă „verificat".
  Concurență optimistă pe versiune. Validare care refuză token în URL și HTTP non-local.
- **`integrations/probes.py`** — verificări reale de credențiale (TikTok, Instagram, Facebook,
  ElevenLabs, Replicate, OpenAI, SMTP/IMAP). Nu publică și nu generează nimic. Nicio verificare
  falsă.
- **`integrations/router.py`** — `VERIFIED` pentru LLM se scrie doar după ce `list_models()` a
  făcut un apel HTTP real care ridică excepție la eșec. `bind_channel` refuză o conexiune care
  nu e `VERIFIED`. Ștergerea refuză o conexiune încă alocată.
- **`research/retrieval.py`** — apărare SSRF serioasă și corectă: doar HTTPS, doar port 443, doar
  gazde din listă albă, fără credențiale în URL, DNS rezolvat și **toate** adresele trebuie să fie
  publice, conexiune fixată pe IP-ul validat cu TLS autentificat pe numele original, redirecturile
  re-validate prin aceeași funcție, limite de dimensiune/timp/redirect, doar `identity` encoding.
  Nu am găsit o cale de ocolire.
- **`factual/agent_pipeline.py`** — sursa e încapsulată în frontieră inertă anti-injecție,
  ieșirea modelului e validată strict împotriva schemei, iar `extract_claims` scrie
  `status = 'UNVERIFIED'`. Un JSON trunchiat păstrează doar obiectele complete, nu ghicește.
- **Bulele de dialog live** — textul vine din răspunsul real al modelului și se emite doar pe
  `SUCCEEDED` cu text vizibil. Nu se inventează replici.
- **Documentația** — cele două documente de arhitectură editate (`02_SRS.md`,
  `V3_FILE_BY_FILE_REVIEW.md`) au hash-urile actualizate *explicit*, cu decizie înregistrată
  (D-DOC-001) și `original_sha256` păstrat, exact cum cere procesul. Am verificat eu hash-urile
  și unicitatea identificatorilor FR: corecte.
- **Biroul 2D** — cerințele tale sunt respectate în continuare: pietonii stau sub baza clădirii
  (test de regresie), liftul se mișcă doar când un token schimbă etajul, mașinile au scară
  corectă față de oameni (sedan 90×30 px la un om de 37 px), magazinul de la parter există pe
  parterul înalt, plăcuțele cu nume sunt cartonașe albe cu text închis. ZCode a adăugat
  car-following (mașinile nu mai trec una prin alta) cu trei teste noi — verificate, corecte.

## F. Rămâne de făcut

1. Analytics (Faza 7): cablat complet sau scos.
2. Parterul (zonele commons/infra) e încă mai gol decât celelalte etaje.
3. Personajele nu intră/ies vizibil din cabina liftului.
4. Fotografiile de referință pentru direcția artistică nu au ajuns niciodată — dacă mai contează,
   trimite-le.
