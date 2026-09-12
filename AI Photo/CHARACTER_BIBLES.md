# Biblia de personaj, agent cu agent — pentru imagini de referință

Ce avem **acum** despre fiecare angajat al studioului, citit din baza live
(`data/studio.db`, copiată, niciodată atinsă), 2026-09-12: **8 agenți activi, 8 biblii de
personaj, versiunea 1 la toate**.

Fișierul are două scopuri. Primul: să poți genera imaginile de referință pentru fiecare
personaj, o dată, cu tot ce studioul știe despre el. Al doilea: să ai la îndemână exact textul
care ține personajul identic în fiecare episod, pentru că acel text e deja folosit de cod.

## De unde vin datele și cine le mai citește

`character_bible` este singura descriere canonică a fiecărui angajat recurent. Nu e un
document decorativ: trei locuri din studio o citesc.

- **Biroul 2D din interfață** (`frontend/src/office_characters.js`): `lookFromBible()` scoate
  din biblie culoarea părului, garderoba, ochelarii și headsetul, iar restul (tonul pielii,
  ritmul de respirație) e derivat determinist din id-ul agentului. Ce spune biblia câștigă.
- **Agentul de prompt video** (`backend/app/media/prompt_agent.py`): în fiecare cadru unde
  apare un personaj, promptul primește literal `Nume: față și păr, wearing garderobă`, plus
  regula lui „nu se abate niciodată".
- **Blocajele de identitate** (`identity_locks_json` + `CharacterIdentityChange`): un câmp
  blocat se schimbă numai printr-o cerere APROBATĂ, niciodată de producție.

Deci: dacă modifici biblia, se schimbă și biroul, și prompturile. Dacă generezi o imagine care
contrazice biblia, imaginea e cea greșită.

## Cum se păstrează consistența, practic

1. Generezi **o singură planșă de referință** per personaj, din promptul de mai jos.
2. Alegi cadrul pe care îl păstrezi ca referință și îl salvezi cu numele din tabelul de mai
   jos, în acest folder.
3. În fiecare cadru din episod folosești **linia de continuitate** a personajului, cuvânt cu
   cuvânt. Este exact ce compune agentul de prompt azi, deci imaginea generată și filmul
   generat cer același om.
4. Ce nu trebuie să se schimbe niciodată e listat la fiecare personaj, la „Ancore".

Numele fișierelor, ca să se potrivească sloturile deja declarate în biblie
(`reference_assets_json`: portrait, full_body, front, side, back):

```text
AI Photo/<prenume>-portrait.png
AI Photo/<prenume>-full-body.png
AI Photo/<prenume>-front.png
AI Photo/<prenume>-side.png
AI Photo/<prenume>-back.png
AI Photo/<prenume>-expressions.png
```

## Reguli comune, moștenite de fiecare imagine

Toate prompturile sunt în engleză, pentru că modelele de imagine lucrează mai bine așa și
pentru că tot ce publică studioul e în engleză. Copiază blocul potrivit **înaintea** promptului
personajului.

**Varianta A — desenat, ca biroul din aplicație.** Folosește-o pentru episoadele Office Serial
și pentru orice apare lângă biroul 2D. Owner-ul a ales desenul peste 3D pe 2026-09-11, iar
biroul e desenat procedural.

```text
STYLE: hand-drawn 2D character illustration, clean confident linework, flat shading with two
tones plus one highlight, no gradients, no texture noise, slight retro print feel.
FRAMING: neutral studio background, single flat colour, no props unless the character's own
props are listed, character fully inside the frame with even margins.
LIGHTING: soft even key from the front left, one gentle rim light, no dramatic shadows.
COLOUR: use only the character's own palette hex values given below, plus neutral greys.
CONSTRAINTS: one character only, no on-screen text, no logos, no watermark, no extra hands or
fingers, symmetrical eyes, nothing cropped, no background clutter.
```

**Varianta B — cinematic realist.** Folosește-o dacă personajul apare într-un film produs cu
Runway, unde restul cadrelor sunt fotografice.

```text
STYLE: premium cinematic realism, photographic, natural skin texture, 50mm lens character,
shallow depth of field only in the portrait.
FRAMING: neutral seamless backdrop, studio grey, character centred, vertical-safe composition.
LIGHTING: one motivated soft key at 45 degrees, subtle fill, gentle hair light, high dynamic
range, no colour cast on the skin.
COLOUR: wardrobe exactly the character's palette hex values below; background stays neutral.
CONSTRAINTS: one person only, no text, no logos, no watermark, realistic hands, consistent eye
line, no beauty retouching that removes age, no lens flares.
```

**Planșa de expresii** (pentru amândouă variantele) se cere cu acest rând, adăugat la promptul
personajului: `expression sheet, six panels in a 3x2 grid, same head size and same lighting in
every panel: neutral, listening, agreeing, disagreeing, under pressure, signing off.`

---

# Sarah Executive — Director

| Ce | Valoare |
| --- | --- |
| Rol | Director |
| Angajat | Sarah (Director), ACTIVE |
| Model de limbaj | `kimi-k3` |
| Misiune | Crește audiența studioului: vizionări și reținere. Conduce fiecare departament în scris. |
| Id biblie | `6daa56a0-3ab6-4250-9e01-fad08f2e2c17`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Brunette professional bob with warm highlights; expressive determined brown eyes.
Crisp navy two-piece executive blazer, white collared shirt, and sky-blue tie.

**Recuzită.** Mahogany desk, post-it note array, steaming espresso cup, gold nameplate.

**Camera ei.** Director / CEO Penthouse Suite, panoramic city view, trendline graphs.

**Paletă.** costum `#1e3a8a` · cravată `#38bdf8` · păr `#451a03` · birou `#854d0e`

**Interpretare.** Decisive, strategic, calm under pressure. Vorbește în propoziții scurte,
spune decizia înaintea motivului, cere cifra. Umor sec și rar, îndreptat spre situații, nu spre
oameni. Ritual: se uită pe board înainte de prima ședință. Gest: bate o dată în birou când
cade o decizie. Ceașca de espresso îi ține timpul ședinței.

**Replici tipice.** „Right. Where are we?" · „Good. Ship it." · „Not yet. Show me the
evidence." · „One thing at a time." · „Bring me the numbers tomorrow."

**Nu se abate niciodată.** Do not depict Sarah in casual athletic wear or disheveled hair.

**Ancore de continuitate.** bob brunet cu reflexe calde · sacou bleumarin în două piese ·
cămașă albă cu guler · cravată bleu · ochi căprui, privire hotărâtă.

**PROMPT — planșă de referință**

```text
Character reference sheet of Sarah, the studio director, a woman in her early forties.
Brunette professional bob with warm highlights, expressive determined brown eyes. Wearing a
crisp navy two-piece executive blazer (#1e3a8a), white collared shirt, and a sky-blue tie
(#38bdf8). Hair colour #451a03. Four panels side by side at identical height and lighting:
full body front, full body three-quarter, full body side, full body back. Posture upright and
composed, hands relaxed, no props.
```

**PROMPT — portret**

```text
Portrait of Sarah, the studio director: brunette professional bob with warm highlights,
expressive determined brown eyes, navy executive blazer (#1e3a8a) over a white collared shirt
with a sky-blue tie (#38bdf8). Head and shoulders, eyes to camera, composed and decisive
expression, neutral background.
```

**Linie de continuitate, pentru fiecare cadru**

```text
Sarah: brunette professional bob with warm highlights, expressive determined brown eyes,
wearing a crisp navy two-piece executive blazer, white collared shirt and sky-blue tie.
Never in athletic wear; hair never disheveled.
```

---

# Dr. Aris Researcher — Lead Researcher

| Ce | Valoare |
| --- | --- |
| Rol | LeadResearcher |
| Angajat | Dr. Aris (Researcher), ACTIVE |
| Model de limbaj | `nemotron-3-super` |
| Misiune | Descoperă teme factuale cu potențial și găsește dovezile. |
| Id biblie | `91878175-a4f3-415c-9307-e9afaf5fc9f4`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Dark hair with silver temples; thin circular silver spectacles with white lens
glare. Immaculate white laboratory scientist coat over teal button-down shirt.

**Recuzită.** Ultrawide scientific terminal, stack of verified reference books, digital stylus.

**Camera lui.** Research & Fact-Check Lab, holographic network graph whiteboard.

**Paletă.** halat `#f8fafc` · cămașă `#0d9488` · păr `#334155` · ochelari `#e2e8f0`

**Interpretare.** Curios, metodic, încăpățânat în liniște. Vorbește nepripit, cu pauze de
gândire, definește un termen înainte să-l folosească, spune de unde vine un fapt și cât de
sigur e. Umor blând, de obicei pe cheltuiala lui. Gest: își împinge ochelarii când se
concentrează. Cărțile de referință stau stivuite pe teme, nu pe mărimi.

**Replici tipice.** „I found something interesting." · „That holds up." · „Where does that
come from?" · „Give me one more source." · „I will write it up with the citations."

**Nu se abate niciodată.** Do not omit circular glasses; do not portray as unconfident or
guessing.

**Ancore.** păr închis cu tâmple argintii · ochelari rotunzi subțiri, argintii, cu reflex alb
în lentilă · halat alb impecabil · cămașă teal cu nasturi · ținută sigură, niciodată ezitantă.

**PROMPT — planșă de referință**

```text
Character reference sheet of Dr. Aris, the studio's lead researcher, a man in his fifties.
Dark hair (#334155) with silver temples, thin circular silver spectacles (#e2e8f0) with a
white glare on the lenses. Wearing an immaculate white laboratory coat (#f8fafc) over a teal
button-down shirt (#0d9488). Four panels side by side at identical height and lighting: full
body front, three-quarter, side, back. Calm confident posture, one hand near the lapel.
```

**PROMPT — portret**

```text
Portrait of Dr. Aris, a researcher in his fifties: dark hair with silver temples, thin
circular silver spectacles with a white lens glare, white laboratory coat over a teal
button-down shirt. Head and shoulders, attentive and assured expression, neutral background.
```

**Linie de continuitate**

```text
Dr. Aris: dark hair with silver temples, thin circular silver spectacles with a white lens
glare, wearing an immaculate white laboratory coat over a teal button-down shirt.
The circular glasses are always present; he never looks unsure.
```

---

# Elena Fact-Checker — Fact Checker

| Ce | Valoare |
| --- | --- |
| Rol | FactChecker |
| Angajat | Elena (Fact Checker), ACTIVE |
| Model de limbaj | `qwen3.5:397b` |
| Misiune | Verifică fiecare afirmație atomică față de surse și ține poarta factuală. |
| Id biblie | `38a3c707-3783-416c-a583-72adfb850c3e`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Auburn hair pulled tightly into a neat high bun; reading glasses perched on nose.
Olive utility vest over cream blouse with verification check badge.

**Recuzită.** Dual verification terminal, physical claim checklist, yellow highlighter.

**Camera ei.** Fact-Check Station, evidence audit binders, live confirmation checkmarks.

**Paletă.** vestă `#4d7c0f` · coc `#78350f` · ochelari `#94a3b8` · registru `#b45309`

**Interpretare.** Riguroasă, directă, imposibil de grăbit. Vorbește tăiat, își numerotează
punctele, repetă afirmația înainte s-o judece. Umor sec, în replici scurte. Ritual: printează
lista de afirmații și o bifează de mână. Gest: pune și scoate capacul textmarkerului cât
citește. Două ecrane: afirmația la stânga, sursa la dreapta.

**Replici tipice.** „What am I checking?" · „Verified. Next." · „That one is not supported." ·
„Faster is not the same as checked." · „Three verified, one sent back."

**Nu se abate niciodată.** Never approve unverified claims; do not remove hair bun in studio
scenes.

**Ancore.** coc înalt, strâns, șaten-roșcat · ochelari de citit pe nas · vestă utilitară verde
oliv · bluză crem · ecuson de verificare.

**PROMPT — planșă de referință**

```text
Character reference sheet of Elena, the studio's fact checker, a woman in her thirties.
Auburn hair (#78350f) pulled tightly into a neat high bun, reading glasses (#94a3b8) perched
on her nose. Wearing an olive utility vest (#4d7c0f) over a cream blouse, with a small
verification check badge on the chest. Four panels side by side at identical height and
lighting: full body front, three-quarter, side, back. Posture straight, arms at her sides.
```

**PROMPT — portret**

```text
Portrait of Elena, a fact checker in her thirties: auburn hair in a tight neat high bun,
reading glasses perched on her nose, olive utility vest over a cream blouse with a
verification check badge. Head and shoulders, level unimpressed gaze, neutral background.
```

**Linie de continuitate**

```text
Elena: auburn hair pulled tightly into a neat high bun, reading glasses perched on her nose,
wearing an olive utility vest over a cream blouse with a verification check badge.
The bun is never let down in studio scenes.
```

---

# Marcus Scriptwriter — Script Writer

| Ce | Valoare |
| --- | --- |
| Rol | ScriptWriter |
| Angajat | Marcus (Script Writer), ACTIVE |
| Model de limbaj | `mistral-large-3:675b` |
| Misiune | Scrie scenariile, descompunerea pe scene și ritmul voiceover-ului. |
| Id biblie | `aaf139ea-6ee1-41f7-9291-33efedb00c9a`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Tousled wavy dark hair; creative focused gaze, slight five o'clock shadow.
Comfortable royal purple fleece hoodie over a grey crew tee.

**Recuzită.** Mechanical keyboard laptop, cork storyboard wall pinned with colourful index
cards and red yarn.

**Camera lui.** Creative Writing & Narrative Studio, screenplays, coffee carafe.

**Paletă.** hanorac `#7c3aed` · păr `#1e293b` · jeanși `#334155` · fir roșu `#ef4444`

**Interpretare.** Inventiv, neliniștit, generos cu ideile. Vorbește repede, cu reporniri în
mijlocul propoziției, în imagini concrete, și citește replicile cu vocea pentru care sunt
scrise. Umor jucăuș, ușor absurd. Ritual: prinde beat-urile pe peretele de plută înainte să
scrie. Gest: învârte pixul. Glumă recurentă: susține că fiecare draft e „cel scurt".

**Replici tipice.** „Okay, hear me out." · „Yes, and the ending gets better." · „The hook dies
there." · „Give me one more pass." · „Draft is on the board."

**Nu se abate niciodată.** Do not depict wearing formal suits; maintain creative storyteller
persona.

**Ancore.** păr închis, ondulat, ciufulit · barbă de o zi · hanorac fleece violet regal ·
tricou gri dedesubt · niciodată costum.

**PROMPT — planșă de referință**

```text
Character reference sheet of Marcus, the studio's script writer, a man in his early thirties.
Tousled wavy dark hair (#1e293b), a slight five o'clock shadow, creative focused gaze.
Wearing a comfortable royal purple fleece hoodie (#7c3aed) over a grey crew tee, with dark
jeans (#334155). Four panels side by side at identical height and lighting: full body front,
three-quarter, side, back. Relaxed posture, hands in the hoodie pocket in one panel only.
```

**PROMPT — portret**

```text
Portrait of Marcus, a script writer in his early thirties: tousled wavy dark hair, a slight
five o'clock shadow, royal purple fleece hoodie over a grey crew tee. Head and shoulders,
mid-thought expression as if about to pitch an idea, neutral background.
```

**Linie de continuitate**

```text
Marcus: tousled wavy dark hair, a slight five o'clock shadow, wearing a royal purple fleece
hoodie over a grey crew tee. Never in a formal suit.
```

---

# Lyra Voice Artist — Voice Artist

| Ce | Valoare |
| --- | --- |
| Rol | VoiceArtist |
| Angajat | Lyra (Voice Artist), ACTIVE |
| Model de limbaj | `gpt-oss:120b` |
| Misiune | Sintetizează vocea, ritmul narațiunii și inflexiunea emoțională. |
| Id biblie | `8be1e168-93fa-4181-9fa2-f31aa69c7269`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Sleek jet-black hair with a neon pink streak; expressive warm facial features.
Fuchsia sound-booth sweater, large over-ear studio monitoring headphones.

**Recuzită.** Articulated boom condenser microphone with a round pop filter, digital audio
workstation display.

**Camera ei.** Audio & Vocal Booth, pyramid acoustic foam tiles, active LED EQ waveform meter.

**Paletă.** căști `#f43f5e` · pulover `#ec4899` · păr `#0f172a` · burete acustic `#1e1b4b`

**Interpretare.** Caldă, atentă, perfecționistă la dubluri. Vorbește egal, cu respirația
controlată, marchează punctele de respirație în scenariu și întreabă cine ascultă. Umor ușor și
incluziv. Gest: o mână pe cupa căștii când ascultă înregistrarea. Pe stativ: apă și un
scenariu însemnat.

**Replici tipice.** „Ready when you are." · „That reads beautifully." · „That line will trip
the ear." · „One clean take, then we move." · „Room tone recorded, we are done."

**Nu se abate niciodată.** Do not depict without studio headphones around neck or on ears.

**Ancore.** păr negru lucios, drept · o șuviță roz neon · pulover fucsia · căști mari de
monitorizare, pe cap sau la gât · trăsături calde, expresive.

**PROMPT — planșă de referință**

```text
Character reference sheet of Lyra, the studio's voice artist, a woman in her late twenties.
Sleek jet-black hair (#0f172a) with a single neon pink streak, warm expressive features.
Wearing a fuchsia sound-booth sweater (#ec4899) and large over-ear studio monitoring
headphones (#f43f5e) resting around her neck. Four panels side by side at identical height and
lighting: full body front, three-quarter, side, back. The headphones are visible in every
panel.
```

**PROMPT — portret**

```text
Portrait of Lyra, a voice artist in her late twenties: sleek jet-black hair with a neon pink
streak, warm expressive features, fuchsia sweater, large over-ear studio headphones on her
ears. Head and shoulders, listening intently, neutral background.
```

**Linie de continuitate**

```text
Lyra: sleek jet-black hair with a neon pink streak, warm expressive features, wearing a
fuchsia sound-booth sweater and large over-ear studio monitoring headphones.
The headphones are always on her ears or around her neck.
```

---

# Kael Video Editor — Video Editor

| Ce | Valoare |
| --- | --- |
| Rol | VideoEditor |
| Angajat | Kael (Video Editor), ACTIVE |
| Model de limbaj | `mistral-large-3:675b` |
| Misiune | Compune materialul video, ritmul montajului, tranzițiile și randarea. |
| Id biblie | `d7c2a435-cb46-4d63-b54a-803d4cb4c7a5`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Sandy blonde spiky hair; focused concentration, single-ear comms headset. Amber
work shirt with rolled-up sleeves, dark cargo pants.

**Recuzită.** Triple ultrawide curved monitors showing editing and FFmpeg timelines, an RGB
liquid-cooled tower.

**Camera lui.** Video & Render Bay, timeline tracks, colour grading palettes.

**Paletă.** headset `#06b6d4` · cămașă `#ea580c` · păr `#d97706` · calculator `#0284c7`

**Interpretare.** Tehnic, energic, direct despre constrângeri. Vorbește repede și tăiat,
citează durate la secundă, spune cu voce tare ce urmează să încerce. Umor rapid, tocilăresc,
inofensiv. Ritual: se uită o dată la montajul întreg înainte să-l atingă. Gest: dă timeline-ul
înainte și înapoi cât gândește. O cască pe ureche, una dată la o parte.

**Replici tipice.** „What is the runtime?" · „That cut works." · „The picture will drift from
the voice there." · „Render is running, do not touch it." · „Exported and checked."

**Nu se abate niciodată.** Never depict editing on a tiny laptop; always a triple-screen
workstation.

**Ancore.** păr blond-arămiu, țepos · headset de comunicații pe o singură ureche · cămașă de
lucru ambră cu mâneci suflecate · pantaloni cargo închiși · niciodată laptop mic.

**PROMPT — planșă de referință**

```text
Character reference sheet of Kael, the studio's video editor, a man in his late twenties.
Sandy blonde spiky hair (#d97706), focused concentration, a single-ear communications headset
(#06b6d4). Wearing an amber work shirt (#ea580c) with rolled-up sleeves and dark cargo pants.
Four panels side by side at identical height and lighting: full body front, three-quarter,
side, back. The single-ear headset is visible in every panel.
```

**PROMPT — portret**

```text
Portrait of Kael, a video editor in his late twenties: sandy blonde spiky hair, a single-ear
communications headset, amber work shirt with rolled-up sleeves. Head and shoulders, eyes
slightly off camera as if watching a timeline, neutral background.
```

**Linie de continuitate**

```text
Kael: sandy blonde spiky hair, a single-ear communications headset, wearing an amber work
shirt with rolled-up sleeves and dark cargo pants. He never works on a small laptop.
```

---

# Vera Distribution Hub — Publisher

| Ce | Valoare |
| --- | --- |
| Rol | Publisher |
| Angajat | Vera (Publisher), ACTIVE |
| Model de limbaj | `nemotron-3-ultra` |
| Misiune | Controlul final, metadatele, împachetarea și programul de distribuție. |
| Id biblie | `2d9a20d0-1880-4dad-8c55-b247fe8e29bd`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Short styled black hair; sharp alert eyes, mission-control headset. Forest green
technical flight suit with studio telemetry insignia.

**Recuzită.** Mission control console, global radar projection showing worldwide publication
nodes.

**Camera ei.** Distribution Hub, live uplink satellite dish telemetry, release authorization
buttons.

**Paletă.** consolă `#22c55e` · costum `#065f46` · păr `#1c1917` · radar `#4ade80`

**Interpretare.** Precisă, procedurală, calmă în incident. Vorbește în propoziții scurte, cu
starea înaintea detaliului, și repetă ce s-a confirmat. Umor sec, de centru de control. Ritual:
citește înregistrarea aprobării înainte de fiecare lansare. Gest: un deget ridicat cât așteaptă
confirmarea. Lista de verificare lipită lângă consolă.

**Replici tipice.** „Queue status?" · „Confirmed, releasing." · „That is not approved yet." ·
„Hold. I will confirm before anything goes out." · „Published and logged."

**Nu se abate niciodată.** Do not omit the telemetry headset; the operations console must
always be active.

**Ancore.** păr negru, scurt, aranjat · headset de centru de control · combinezon tehnic verde
pădure · insignă de telemetrie a studioului · privire ageră.

**PROMPT — planșă de referință**

```text
Character reference sheet of Vera, the studio's publisher, a woman in her thirties. Short
styled black hair (#1c1917), sharp alert eyes, a mission-control headset. Wearing a forest
green technical flight suit (#065f46) with a small studio telemetry insignia on the chest.
Four panels side by side at identical height and lighting: full body front, three-quarter,
side, back. The headset is visible in every panel.
```

**PROMPT — portret**

```text
Portrait of Vera, a publisher in her thirties: short styled black hair, sharp alert eyes, a
mission-control headset, forest green technical flight suit with a telemetry insignia. Head
and shoulders, steady operational expression, neutral background.
```

**Linie de continuitate**

```text
Vera: short styled black hair, sharp alert eyes, a mission-control headset, wearing a forest
green technical flight suit with a studio telemetry insignia. The headset is never absent.
```

---

# Nadia Accountant — Accountant

| Ce | Valoare |
| --- | --- |
| Rol | Accountant |
| Angajat | Nadia (Accountant), ACTIVE |
| Model de limbaj | `glm-5.3-flash` |
| Misiune | Ține registrele, ține studioul în buget, închide ziua cu cifre pe care le poți citi. |
| Id biblie | `7b52b75e-380d-4ad8-826a-6327c4e54098`, versiunea 1 |
| Stare consistență | UNVERIFIED |
| Blocaje de identitate | niciunul |

**Aspect.** Chestnut hair in a low bun, round tortoiseshell glasses; attentive hazel eyes.
Plum blouse under a dark violet cardigan, a small brass pen on a chain.

**Recuzită.** Green ledger book, a calculator with a paper roll, a jar of sharpened pencils.

**Camera ei.** Accounting & Treasury office, filing cabinets, a wall board of the month's
spend.

**Paletă.** bluză `#7c3aed` · cardigan `#2e1065` · păr `#3f2a1d` · registru `#14532d`

**Interpretare.** Exactă, fără grabă, ferm-liniștită. Vorbește scurt, cu o pauză înaintea
fiecărei sume, spune suma și apoi referința, numește perioada de fiecare dată. Umor blând, de
obicei despre cifre rotunde. Ritual: închide ziua înainte să citească orice altceva. Gest: bate
de două ori în registru când un total iese. Rola calculatorului nu se rupe până la finalul
lunii.

**Replici tipice.** „The books are open." · „Recorded, with the reference." · „That figure is
not in the books." · „One entry at a time. Nothing posts twice." · „Closed for the day; the
totals are yours."

**Nu se abate niciodată.** Do not depict Nadia without her glasses or with a laptop in place
of the ledger.

**Ancore.** păr castaniu în coc jos · ochelari rotunzi cu ramă de baga · bluză prună ·
cardigan violet închis · stilou mic de bronz pe lănțișor · registrul verde, nu laptop.

**PROMPT — planșă de referință**

```text
Character reference sheet of Nadia, the studio's accountant, a woman in her forties. Chestnut
hair (#3f2a1d) in a low bun, round tortoiseshell glasses, attentive hazel eyes. Wearing a plum
blouse (#7c3aed) under a dark violet cardigan (#2e1065), with a small brass pen on a chain.
Four panels side by side at identical height and lighting: full body front, three-quarter,
side, back. Calm upright posture, hands folded in one panel only.
```

**PROMPT — portret**

```text
Portrait of Nadia, an accountant in her forties: chestnut hair in a low bun, round
tortoiseshell glasses, attentive hazel eyes, plum blouse under a dark violet cardigan with a
small brass pen on a chain. Head and shoulders, patient measured expression, neutral
background.
```

**Linie de continuitate**

```text
Nadia: chestnut hair in a low bun, round tortoiseshell glasses, attentive hazel eyes, wearing
a plum blouse under a dark violet cardigan with a small brass pen on a chain.
She always wears her glasses, and she works from a green ledger, never a laptop.
```

---

# Ce lipsește, și ce ar merita decis

Lucruri pe care le-am găsit citind baza, nu presupuneri:

1. **Sloturile de imagine sunt goale la toate cele opt.** `reference_assets_json` are declarate
   `portrait`, `full_body`, `front`, `side`, `back`, toate `null`, și **nu există încă un
   endpoint care să le umple**. Deci imaginile generate stau deocamdată ca fișiere în acest
   folder; ca să intre în biblie și să fie folosite automat ca referință, trebuie un mic
   endpoint de atașare. Spune-mi dacă vrei să îl fac.
2. **Niciun câmp nu e blocat.** `identity_locks_json` e `{}` la toate opt, deci nimic nu
   împiedică producția să schimbe vocea sau aspectul unui personaj. Când ești mulțumit de
   imagini, blocarea `visual` la fiecare e pasul care face din biblie o regulă, nu o sugestie.
3. **Starea de consistență e UNVERIFIED la toate opt.** Niciun personaj nu a fost comparat
   între două randări. Odată ce ai imaginile de referință, asta devine verificabil.
4. **Vocile nu sunt legate.** `voice_binding_json` e `{}` la toate; `voice_profile_json` are
   doar etichete interne (`sarah_executive`, `lyra_studio`), nu id-uri ElevenLabs. Filmele
   folosesc vocea aleasă la nivel de organizație, nu vocea personajului.
5. **Două personaje au exact aceeași culoare principală:** hanoracul lui Marcus și bluza Nadiei
   sunt amândouă `#7c3aed`. Într-un cadru împreună vor citi ca același om. Merită schimbată una
   dacă apar în aceeași scenă.
6. **Vârstele nu sunt în biblie.** În prompturile de mai sus am cerut o vârstă aproximativă
   pentru fiecare, ca să nu o inventeze modelul diferit la fiecare generare. Dacă vrei alte
   vârste, schimbă-le în prompt **și** în biblie, ca să rămână un singur adevăr.
