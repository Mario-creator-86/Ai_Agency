# Ollama Cloud — catalog și alocare, 8 octombrie 2026

Catalogul și cheia conexiunii existente au fost verificate direct la Ollama Cloud.
`/api/tags` a returnat 18 variante din 17 familii; `/api/show` a confirmat capabilitățile
fiecărei variante. Lista publică singură nu dovedește accesul unui cont: proiectul verifică
separat autentificarea, iar cele cinci modele alese au răspuns efectiv prin cheia salvată.
Sursa listei: [Ollama Cloud](https://docs.ollama.com/cloud),
[catalogul API](https://ollama.com/api/tags).

## Alocarea salvată

| Agent | Model principal | Motivul alegerii |
|---|---|---|
| Sarah — Director | `kimi-k3` | Context amplu, coordonare și verificare editorială inclusiv pe imagini. |
| Dr. Aris — Researcher | `minimax-m3` | Cercetare, extragerea informațiilor și urmărirea mai multor surse. |
| Elena — Fact Checker | `deepseek-v4-pro:0813` | Raționament și verificarea logică a afirmațiilor față de dovezi; model distinct de cercetător. |
| Marcus — Script Writer | `kimi-k3` | Structura poveștii, scenarii documentate și continuitatea personajelor. |
| Lyra — Voice Artist | `mistral-large-4` | Adaptare multilingvă, pronunție și indicații pentru interpretarea vocală. |
| Kael — Video Editor | `kimi-k3` | Înțelegerea cadrelor, planuri de montaj și continuitate vizuală. |
| Vera — Publisher | `nemotron-3-ultra` | Proceduri cu mai mulți pași și respectarea condițiilor de publicare. |
| Nadia — Accountant | `mistral-large-4` | Interpretarea documentelor financiare și explicarea bugetului. |

Sarah păstrează `nemotron-3-ultra` ca al doilea model pentru analiza critică a deciziilor
importante: REVIEW / IMPORTANT_ONLY / STRATEGIC. Ceilalți șapte folosesc un singur model.
Sarah, Marcus și Kael aveau deja alegerea potrivită și au păstrat-o; cinci agenți au primit
o alocare nouă. Toate cele opt alocări au fost citite din nou după salvare.

Aceste alegeri sunt o evaluare pentru rolurile acestui studio, bazată pe capabilitățile
declarate, documentația producătorilor și probele locale. Nu reprezintă un clasament general
sau un benchmark complet între toate modelele. Mistral Large 4 este un preview recent,
[anunțat de Mistral la 6 octombrie](https://mistral.ai/news/mistral-large-4/); va trebui
reevaluat dacă furnizorul schimbă versiunea ori comportamentul.

Lyra folosește LLM-ul pentru text și regie vocală; sunetul real rămâne la furnizorul de voce
existent. Kael planifică și analizează; instrumentele media execută montajul și generarea.
Nadia interpretează datele; calculele contabile și limitele autorizate rămân în backend.
O capabilitate «tools» declarată nu acordă automat acces la instrumente sau permisiuni.

## Ce oferă fiecare variantă disponibilă

«Text» și «imagini» sunt capabilități confirmate de `/api/show`. Contextul de mai jos este
cel publicat pentru ruta Cloud, nu o măsurătoare locală; unele prezentări generale ale
producătorilor indică un context mai mare decât ruta oferită de Ollama.

| Identificator API | Intrare | Context publicat | Utilizare potrivită și sursa |
|---|---|---|---|
| `kimi-k3` | Text, imagini | 1M | Coordonare, lucru cu documente și context vizual; ales pentru Director, scenarii și montaj. [Ollama](https://ollama.com/library/kimi-k3) |
| `minimax-m3` | Text, imagini | 512K | Căutare asistată de instrumente, cercetare și sarcini autonome ample. [Ollama](https://ollama.com/library/minimax-m3) |
| `deepseek-v4-pro:0813` | Text | 1M | Analiză logică și raționament complex; ales pentru verificator. [Ollama](https://ollama.com/library/deepseek-v4-pro) |
| `deepseek-v4.1-flash` | Text, imagini | 1M | Analiză/căutare cu context mare și utilizare mai moderată; alternativă pentru cercetare. [Ollama](https://ollama.com/library/deepseek-v4.1-flash) |
| `mistral-large-4` | Text, imagini | 1M | Lucru multilingv, documente și analiză financiară; ales pentru voce și contabilitate. [Mistral](https://mistral.ai/news/mistral-large-4/) |
| `nemotron-3-ultra` | Text | 256K | Raționament și proceduri autonome lungi; Publisher și criticul Directorului. [Ollama](https://ollama.com/library/nemotron-3-ultra) |
| `glm-5.3` | Text | 1M | Programare, proiecte ample și lucru susținut cu instrumente. [Ollama](https://ollama.com/library/glm-5.3) |
| `glm-5.3-flash` | Text, imagini | 1M | Programare și sarcini vizuale cu utilizare mai moderată. [Ollama](https://ollama.com/library/glm-5.3-flash) |
| `glm-5.2` | Text | 976K | Inginerie și sarcini de lungă durată; generația anterioară față de GLM-5.3. [Ollama](https://ollama.com/library/glm-5.2) |
| `kimi-k2.7-code` | Text, imagini | 256K | Specialist în programare și lucrul autonom în depozite de cod. [Ollama](https://ollama.com/library/kimi-k2.7-code) |
| `kimi-k2.6` | Text, imagini | 256K | Sarcini autonome, programare și analiză vizuală; generație anterioară față de K3. [Ollama](https://ollama.com/library/kimi-k2.6) |
| `minimax-m2.7` | Text | 192K | Programare și productivitate profesională cu instrumente. [Ollama](https://ollama.com/library/minimax-m2.7) |
| `mistral-large-3:675b` | Text, imagini | 256K | Multilingv, documente, imagini și ieșiri structurate; alternativă la Large 4. [Ollama](https://ollama.com/library/mistral-large-3) |
| `nemotron-3-super` | Text | 256K | Coordonarea agenților cu accent pe eficiență; alternativă mai economică la Ultra. [Ollama](https://ollama.com/library/nemotron-3-super) |
| `nemotron-3-nano:30b` | Text | 256K | Clasificări, extragere și sarcini rapide cu instrumente. [Ollama](https://ollama.com/library/nemotron-3-nano) |
| `gemma4:31b` | Text, imagini | 256K | Model general compact, bun pentru interpretări vizuale și sarcini de rutină. Ruta 31B nu declară audio. [Ollama](https://ollama.com/library/gemma4) |
| `gpt-oss:120b` | Text | 128K | Raționament general, instrumente și răspunsuri structurate. [Ollama](https://ollama.com/library/gpt-oss) |
| `gpt-oss:20b` | Text | 128K | Varianta mai mică pentru sarcini scurte și latență redusă. [Ollama](https://ollama.com/library/gpt-oss) |

Cele 18 variante declară tools; toate în afară de Mistral Large 3 declară și thinking.
Acestea sunt declarații ale furnizorului. Proiectul păstrează comportamentul existent pentru
cereri scurte, care evită consumarea întregului buget de răspuns pe raționament intern.
Modelele de mai sus nu înlocuiesc serviciile dedicate de TTS sau generare video/imagine.
Qwen3.5:397b și qwen3-coder:480b nu apar în catalogul Cloud actual; nu au fost realocate.

## Verificarea efectivă și recuperarea

- Autentificare reală și catalog: cheia existentă validă, 18 variante și capabilități încărcate.
- Două probe sintetice distincte pentru fiecare rol: **16/16 trecute**. Au fost făcute 18
  apeluri reale în total; două probe inițiale de extragere/calcul au fost înlocuite cu variante
  care nu furnizează deja rezultatul așteptat. Celelalte 14 rezultate au fost reutilizate.
- Probele verifică extragerea/contradicția surselor, respingerea unei afirmații nesusținute și
  a instrucțiunilor din surse, scenariu/continuitate, regie vocală în română, goluri în montaj,
  oprirea publicării la QC/proveniență lipsă și buget/preț necunoscut. Directorul și Editorul
  au analizat efectiv o imagine; amândoi au identificat cele trei niveluri ale studioului.
- Apelurile au trecut prin `run_agent_task`, politica și istoricul existent. Nu a fost pornit
  workerul; nu au fost trimise mesaje între angajați, publicate materiale sau generate media.
  Tokenii și costurile au fost înregistrate după tarifele existente din proiect; acestea nu
  reprezintă o factură confirmată de Ollama. Tarifele, bugetele și permisiunile nu au fost modificate.
- Alocare: comenzile existente, cu verificarea versiunii și capabilităților. Cinci schimbări
  auditate și trei alocări păstrate; toate recitite, toți agenții ACTIVE/IDLE la final.
- Cele opt alegeri sunt înregistrate explicit ca OWNER în istoricul alocării. S-a corectat
  protecția alegerilor care coincid cu configurația inițială: actualizarea catalogului nu
  le mai tratează drept alocări automate. Originea SEED_ALLOCATION este folosită numai de
  aplicarea internă a configurației; nu este un câmp nou în formularul/API-ul utilizatorului.
- **103 teste backend vizate trecute**, inclusiv cele două regresii noi, conexiuni, rutare,
  preferințe și comenzi de Setări. Lint/formatare trecute; mypy: 197 fișiere fără probleme.
  Lista reală din Setări și repartizarea birourilor afișează aceleași opt modele disponibile.
  Pagina compilată este actuală; inventarul/hash documentației, secretele și diff sunt verificate.
- Configurație actualizată: `config/workforce_seed.json`. Identificatorii API fără sufix cloud
  sunt folosiți de conexiunea directă; propunerile pentru aplicația locală folosesc taguri cloud.
  Configurația rămâne date; nu s-au introdus nume de modele în logica backendului.

Dovezi locale: `data/model-routing-2026-10-08/catalog.json`, `connection-check.json`,
`role-samples.json`, `allocation.json`, `origin-confirmation.json`, `ui-readback.json`
și logurile aferente. Copia SQLite consistentă de
dinaintea modificării: `before-allocation.db`; configurația veche: `workforce-before.json`.
Nu copia baza de date peste studioul activ ca metodă de revenire: ar pierde istoricul nou.
Pentru revenire, folosește alocările din `agents-before.json` prin comenzile din Setări.

## Verificare ulterioară prin scenarii — 8 octombrie 2026

Cei opt agenți au folosit modelele alocate prin serviciile reale în baze izolate, cu 30 de
încercări Cloud suplimentare, inclusiv un timeout. Cercetarea, verificarea independentă, rescrierea factuală și
refuzurile de politică au reacționat corect. Serialul a trecut ultimul draft, dar numai
după cinci rescrieri; limita obișnuită de încercări nu a fost ridicată. Kimi rămâne modelul
salvat, iar proba normală cu două drafturi a fost respinsă corect. Alternativa Nemotron a
expirat la 600 de secunde și nu a fost promovată; fiabilitatea serialului rămâne de demonstrat.
Nu sunt certificate generații RunPod sau uploaduri reale. Rezultate și istoric complet:
[AGENT_SCENARIO_REPORT.md](AGENT_SCENARIO_REPORT.md).
