# Ghidul operatorului AMN-AI

Acest ghid este pentru cel care conduce studioul în fiecare zi: Proprietarul. Instalarea pas cu
pas și cerințele tehnice sunt în [README](../README.md); toate setările, cu explicația lor, sunt
în [.env.example](../.env.example).

## 1. Ce face studioul și ce nu face singur

Studioul cercetează un subiect, verifică afirmațiile în surse, scrie un film scurt documentar și
episodul serialului de birou, planifică cadrele, cumpără imaginile, mișcarea și vocea de la
furnizorii pe care i-ai conectat, montează filmul cu FFmpeg, îl măsoară și îl urcă pe YouTube.

Singur, studioul **nu** schimbă niciodată: mediul (TEST/PRODUCTION), modul de autonomie, regula
pentru pașii plătiți, bugetele, vizibilitatea canalelor. Acestea sunt deciziile tale și rămân în
istoric. Un studio nou pornește oprit, în modul MANUAL, în TEST, cu programarea zilnică oprită.

## 2. Prima pornire

1. Instalează FFmpeg (Windows: `winget install Gyan.FFmpeg`; Linux: `sudo apt install ffmpeg`;
   macOS: `brew install ffmpeg`). Fără el studioul nu face filme.
2. Rulează `start.cmd` (sau `uv run python scripts/start.py`). La final, lanseratorul afișează
   verificarea studioului: fiecare rând marcat «OPRIT» împiedică ziua, «atenție» o slăbește, și
   spune unde în pagină se repară.
3. Deschide http://127.0.0.1:8000 și lipește cheia din `.env` (`STUDIO_OWNER_TOKEN`).
4. În `.env`, pune locul studioului: `STUDIO_TIMEZONE`, `STUDIO_OFFICE_LATITUDE`,
   `STUDIO_OFFICE_LONGITUDE`, `STUDIO_OFFICE_CITY`, `STUDIO_HOLIDAY_COUNTRY`. Ceasul, cerul și
   strada din pagină le urmează. Repornește studioul după orice schimbare în `.env`.

Vrei să vezi întâi cum merge, fără niciun cont? `uv run python scripts/start.py --demo` pornește
demo-ul pe http://127.0.0.1:8010: un studio separat, cu furnizori simulați, care face un film
local și nu publică și nu plătește nimic.

## 3. Conturile

| Ce | Unde în pagină | De reținut |
|---|---|---|
| Modelul de limbaj | Setări → Furnizori AI, apoi Setări → Angajați | Fiecare angajat are nevoie de un model disponibil. Angajații vin legați de modelele Ollama Cloud ale primului studio; după ce îți conectezi furnizorul, alege-le modelele (sau `scripts/apply_llm_allocation.py`). |
| Runway, ElevenLabs | Setări → Video și sunet | Spune pe fiecare conexiune dacă planul tău permite folosire comercială; altfel filmul poate fi urcat doar privat. |
| YouTube | Setări → Conturi și e-mail, apoi Distribuție → Sloturi de canal | Proiectul tău Google Cloud trebuie să fie «In production» (altfel cheia expiră în 7 zile) și auditat pentru încărcări publice. Detalii: [YOUTUBE_CONNECTIONS](project/YOUTUBE_CONNECTIONS.md). |
| Sursele cercetării | Cercetare → Surse și afirmații | Doar site-urile pe care le adaugi și le testezi tu. |
| Muzica | `config/music_library.json` | Doar piese cu licență comercială, fiecare cu suma SHA-256 a fișierului. |

Cheile stau criptate lângă baza de date, niciodată în `.env`. Dacă studioul nu le mai poate citi
(altă mașină, alt cont Windows), pornește totuși, iar pagina îți cere să le introduci din nou.

## 4. Comenzile tale

- **AUTONOMIE (STOP):** oprește tot ce e programat; un pas plătit în curs se oprește după scena
  în lucru.
- **Modul:** MANUAL (muți tu fiecare etapă), SUPERVISED (rutina merge singură, scrierile externe
  te întreabă), AUTONOMOUS_CEO (Directorul acționează în limitele politicii tale). Acțiunile T4
  sunt mereu ale tale.
- **MEDIU:** în TEST ziua nu cumpără nimic de la furnizorii reali; în PRODUCTION urcă foaia de
  filmare pas cu pas.
- **Regula pașilor plătiți** (pe foaia de filmare, «Când te întreabă un pas plătit al unui
  film»): EVERY_PAID_STEP — te întreabă la fiecare pas (imaginile, cadrul de probă, restul
  mișcării, refacerile); OVER_USD — te întreabă peste suma ta; MODE — urmează modul.
- **Bugetul zilnic** (Trezorerie → Buget și cheltuieli): fără un buget zilnic activ, în
  PRODUCTION regulile MODE și OVER_USD sunt refuzate (BLOCKED_NO_BUDGET).
- **Plafonul unui film** (`STUDIO_FILM_BUDGET_USD`): cât poate costa un film cu totul. Valoarea
  implicită (15,24 USD) este sub ce costă un film de patru scene de 10 secunde la 1080p; pune-ți
  propria sumă.

Un «da» al tău la un pas plătit continuă filmul imediat, nu la rularea de a doua zi; întrebarea
stă deschisă 48 de ore.

## 5. Ziua

- Pornește programarea din Rularea zilei → «Pornește programarea zilnică». Ora este
  `STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) în fusul `STUDIO_TIMEZONE`, afișată în aceeași fereastră.
- Ziua face un singur film documentar: primul care poate merge. Un film blocat nu le mai oprește
  pe cele din spate; un film care stă pe loc `STUDIO_FILM_WAIT_DAYS` zile este retras de Director,
  cu o scrisoare care spune ce s-a cumpărat pentru el.
- Fiecare oprire îți lasă o scrisoare în română, cu motivul și locul în care decizi.
- Dacă oprești studioul în timpul zilei, ziua se încheie după scena în lucru, ca «întreruptă», și
  nu este reluată singură. O nouă rulare în aceeași zi este decizia ta.

## 6. Ca serviciu

- **Windows:** `scripts\install_studio_service.ps1` (PowerShell ca administrator). Rulează la
  autentificare și la pornire. Cu `-RunWhenLoggedOff` cheia salvată poate deveni ilizibilă; varianta
  sigură este autentificarea automată în contul tău.
- **Linux:** `scripts/amn-ai.service` (pașii sunt în fișier). Pe Linux cheia stă necriptată, cu
  drepturi 0600: folosește un disc criptat.

Serviciul nu pornește programarea zilnică și nu ține calculatorul treaz.

## 7. Copii de siguranță

- Automat, în fiecare zi la `STUDIO_BACKUP_HOUR_LOCAL`, și înaintea fiecărei migrări.
- La cerere: `uv run python scripts/backup.py` (merge și cu studioul pornit).
- Restaurare: oprește studioul, apoi `uv run python scripts/restore.py`. Studioul restaurat
  pornește oprit, în TEST, cu programarea oprită.
- **Filmele nu sunt în copia bazei de date.** Copiază folderul `STUDIO_MEDIA_ROOT` pe alt disc.

## 8. Când ceva nu merge

| Semn | Ce înseamnă | Ce faci |
|---|---|---|
| `/health/ready` răspunde 503 | lucrătorul s-a oprit, discul e plin, lipsește FFmpeg sau copia de siguranță e veche | Bannerul din pagină spune care; jurnalul complet este `data/logs/studio.log`. |
| «Cheile salvate nu pot fi citite» | baza de date a fost mutată pe alt cont sau calculator | Reconectează furnizorii din Setări. |
| YouTube «invalid_grant» | autorizarea Google a expirat sau a fost retrasă | Setări → Conturi și e-mail → Reconectează. |
| «Filmul este deja în lucru» | un alt pas cumpără acum pentru același film | Așteaptă să se termine; nimic nu se cumpără de două ori. |
| Un pas plătit refuzat cu «spațiu liber» | sub `STUDIO_MIN_FREE_GB` pe discul filmelor | Eliberează spațiu sau mută `STUDIO_MEDIA_ROOT`. |

## 9. Limite oneste

Studioul rulează doar local, fără TLS și fără mai mulți utilizatori. Niciun test nu dovedește că
un film iese bun: primul film plătit, cu plafon și cu regula EVERY_PAID_STEP, este adevărata
probă. Licențele componentelor sunt în [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md).
