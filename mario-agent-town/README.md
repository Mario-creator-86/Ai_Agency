# Mario Agent Town

Oraș local, privat, pentru Mario și zece agenți AI. Proiect independent în repository-ul `Mario-creator-86/Ai_Agency`, branch `mario-agent-town`, folder `mario-agent-town/`.

**Stadiu: prototip funcțional local, cu adaptoare AI implementate dar netestate pe conturi reale.** Nu este încă un sistem complet care administrează automat YouTube, Gmail sau Calendar. Vezi [HANDOFF.md](HANDOFF.md) pentru continuare. Pentru grafica v2 începe cu [art/README_CLAUDE.md](art/README_CLAUDE.md), care documentează harta nouă, cele zece sprite sheet-uri și atlasele.

## Pornire

1. Instalează Node.js **24 sau mai nou**. Nu sunt necesare pachete npm suplimentare.
2. Deschide folderul `mario-agent-town/`.
3. Windows: dublu click pe `start.cmd`. Alternativ: `npm start`.
4. Deschide `http://127.0.0.1:8012`.
5. Intră în **Setări** și alege furnizorul și modelul pentru fiecare agent.
6. Trimite un mesaj. Activează **Autonomie** când vrei cicluri de lucru automate.

Pe alte sisteme, copiază `.env.example` în `.env` dacă ai nevoie de configurare, apoi `npm start`. Aplicația folosește SQLite inclus în Node 24. Nu folosi Node 22 pentru acest proiect.

## Ce include

- Hartă RPG pictată originală: zece case tematice, Town Hall, parc central, bănci, fântână animată și reședință mai mare pentru CEO.
- Personaj Mario bazat pe fotografiile furnizate explicit în această conversație: cap ras, barbă grizonantă, pulover închis **cu fermoar scurt la gât**. Fotografiile originale nu sunt incluse.
- Săgeți / WASD, Shift pentru alergare, T pentru chat cu agentul apropiat, M pentru Alex. Click pe case/personaje; click pe teren pentru deplasare; drag pentru cameră; rotița pentru zoom.
- Personaje care se plimbă, se orientează spre CEO în apropiere și se adună la Town Hall. Alex îl însoțește. Deplasările sunt animație decorativă, nu dovadă de muncă AI.
- Chat individual și Town Hall; `@maria`, `@radu` etc. Mesajele generale fără destinatar merg la Alex.
- Sarcini, delegare între agenți, memorie per agent, documente/livrabile și jurnal persistente în SQLite.
- Coada de lucru execută un singur agent simultan pentru a limita consumul. Fiecare execuție poate folosi maximum trei runde de model și șase acțiuni per rundă. Delegarea este limitată la două niveluri.
- Cicluri autonome configurabile, limită zilnică, pauză și STOP; serverul lucrează și cu pagina închisă cât timp procesul Node este pornit.
- Fluxuri RSS fixe OpenAI / Hugging Face / arXiv. Erorile de rețea sunt raportate; nu există căutare web generală sau cotații bursiere live.

## Furnizori

| Furnizor | Configurare | Limită actuală |
| --- | --- | --- |
| ChatGPT / Codex CLI | Instalează aplicația oficială CLI, autentifică prin `codex login`; verifică `codex login status`; selectează Codex în oraș. | Adaptorul rulează CLI local; nu extrage tokenuri și nu automatizează chatgpt.com. Integrarea live trebuie verificată pe PC. |
| Claude / Claude Code | Instalează Claude Code oficial, deschide `claude` și autentifică abonamentul; selectează Claude în oraș. | Folosește `claude -p`; fără `--bare`, care nu utilizează loginul abonamentului. Respectă termenii și cotele contului; nu este un proxy pentru alți utilizatori. |
| Ollama local | Pornește Ollama, alege un model existent în `ollama list`, completează numele exact. | Implicit `http://127.0.0.1:11434`; nicio inferență reală verificată în mediul de dezvoltare. |
| Ollama Cloud prin Ollama local | Autentifică Ollama oficial și alege modelul cloud disponibil contului. | Numele modelului depinde de ruta locală și catalogul curent. |
| Ollama Cloud direct | Setează privat `OLLAMA_API_KEY` în `.env`, selectează modelul cloud exact. | Cheie Ollama necesară pentru acces direct; nu este o cheie OpenAI sau Anthropic. |

Aplicația nu include un abonament și nu îl face nelimitat. Cei zece agenți împart cota furnizorului. Numărul de execuții din oraș nu este contorul de tokenuri al furnizorului. Nu există trecere automată la API plătit. Adaptoarele CLI elimină din mediul copil variabilele API OpenAI/Anthropic uzuale, dar setările contului și eventualele opțiuni de extra usage trebuie verificate în aplicația oficială.

CLI execută promptul pe stdin, fără shell intermediar. În Windows, instalările npm sunt rezolvate spre intrarea `.js`; instalările native spre `.exe`. Dacă nu este găsit, setează `CODEX_BIN` / `CLAUDE_BIN` în `.env`. Nu indica un shim `.cmd`. Codex este lansat read-only, fără configurația de instrumente a utilizatorului; Claude are instrumentele native și MCP dezactivate. Instrumentele de lucru permise sunt cele implementate de oraș.

## Ce NU este conectat încă

YouTube/Analytics/OAuth, Gmail/Calendar, voice-over, generare imagini/video, FFmpeg, upload/publicare, notificări externe și prețuri de bursă. UI afișează aceste conexiuni ca neconectate. Rolul Mariei acoperă obiectivul integral, însă execuția reală a întregului canal necesită aceste integrări. 1.000.000 este ținta, nu o promisiune.

Există adaptoare media și YouTube în aplicația AMN-AI din repository-ul părinte. Următorul AI trebuie să le evalueze pentru reutilizare printr-un bridge explicit, păstrând politica Owner, secretele, costurile și identitățile separate.

## Date și verificări

`data/town.sqlite` păstrează istoricul; `workspaces/<agent>/IDENTITY.md` conține identitatea locală. Ambele directoare sunt excluse din Git. Backup: oprește serverul și copiază întreg folderul `data/`; exportul JSON din UI este un export lizibil, nu un mecanism de restore.

Rulează `npm test`. Testele folosesc baze temporare și un model fals, fără conturi sau inferență plătită. Ele nu demonstrează funcționarea live a furnizorilor. Nu publica serverul pe internet: nu include autentificare multiutilizator sau TLS. `npm run dev` activează modul exclusiv pentru preview de dezvoltare; folosește `npm start` pentru utilizare personală.

Documentație oficială consultată la 5 noiembrie 2026: [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode), [Claude Code headless](https://code.claude.com/docs/en/headless), [Claude Code legal](https://code.claude.com/docs/en/legal-and-compliance), [Ollama Cloud](https://docs.ollama.com/cloud), [Ollama authentication](https://docs.ollama.com/api/authentication). Referință de produs: videoclipul furnizat de Owner; transcrierea integrală a fost citită, dar imaginile playerului YouTube au rămas în buffering în browserul de dezvoltare. Nu sunt copiate grafica, codul sau promisiunile creatorului.
