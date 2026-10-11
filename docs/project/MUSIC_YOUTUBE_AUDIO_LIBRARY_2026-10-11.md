# Music for the shorts from the YouTube Audio Library — research, 2026-10-11

Research only (package D). Nothing in `backend/`, `config/` or the tests changed. Every public
page named under «Sources» was read on 2026-10-11; the Owner's own library page
(`studio.youtube.com/channel/UCb6g_x2qeRFyGJkgIbkmKZA/music`) needs his login and was not
opened. Where a fact could only be read in YouTube Studio itself it is marked «on his screen».

## Why now

The Owner, 2026-10-11: «Dacă avem nevoie în shorturile noastre de muzică, poate putem să o
folosim pe cea de la Google, care este gratis, adică biblioteca audio … Doar investighează și
trage concluzii mai întâi, să vedem ce putem integra, cu ce ne ajută.»

Today every film is mixed voice-only: `config/music_library.json` ships with `"tracks": []`,
so `film_mix` records `NO_BED_ADVISORY` and raises the card «Biblioteca de muzică este goală»
(`backend/app/media/assembler.py:5707-5713`, `backend/app/decisions/sources.py:529-560,
921-935`). The card's guided step already points at the file and says what an entry needs.
The question is only where the tracks come from and under which words.

## 1. What the studio already does with music (as built)

Nothing below needs to be built again; the proposal in §4 fits into it.

- **The library.** `backend/app/media/music_library.py`: one JSON, `config/music_library.json`
  or the file `STUDIO_MUSIC_LIBRARY` names (lines 36-40; `.env.example:120-122` documents the
  variable as «the licensed music library … kept outside the release»). Each entry is vouched
  for by `_checked` (lines 168-213): `commercial_ok` must be literally `true`, `licence`
  non-empty, `file` inside the library's own folder (lines 186-188: `../outside.wav` is
  refused), the file present and its SHA-256 equal to the recorded one. Anything else is
  refused with a Romanian reason that the film keeps (`production['audio']['library']`,
  assembler lines 5679-5683) and quality control shows.
- **The choice.** `choose_bed` (lines 263-277) scores each music track by how many words of
  the film (title, core message, every scene's voice-over, purpose and `audio_intent`) start a
  stem of the track's moods (`MOOD_WORDS`, lines 44-105: `tense`, `mystery`, `dark`, `wonder`,
  `calm`, `uplifting`, `epic`, English and Romanian stems); ties and films that call for
  nothing are broken by the storyboard id, so successive films do not all carry the same
  track. `choose_ambience` (lines 280-291) places an `ambience` entry under a scene whose
  `audio_intent` names one of its `tags`.
- **The mix.** `toolchain.mix_bed` (`backend/app/media/toolchain.py:739` onward) loops or cuts the
  bed to the film's length, sets it 20 LU under the voice, ducks it with a sidechain, fades
  it, and measures it again. ffmpeg decodes the bed, so an **MP3 from the Audio Library needs
  no conversion**; the library does not restrict the extension, only the bytes (sha256).
- **The licence ledger.** `licence_components` (assembler 5898-5991) lists every track used
  with `vendor: BIBLIOTECA_PROPRIETARULUI`, `terms: <licence>`, `commercial_use: True` only when
  `commercial_ok` is true, and its `attribution` (lines 5973-5988). A film is `LICENSED` only
  when every component carries that evidence (lines 6012-6037); otherwise `NEEDS_REVIEW`, which
  the rights check lets go up **private only** (`backend/app/media/qc.py:706-737`) and
  `publishing/licence_release.py` releases later when the evidence arrives.
- **Audio QC.** `audio_mix_verdict` (`qc.py:740-785`) refuses a film whose bed or ambience is
  not an entry of the library *as it is now* (same id, same sha256, commercial use confirmed)
  and checks the bed sits 18-22 LU under the voice (`toolchain.BED_UNDER_VOICE_BAND_LU`,
  line 590). A film without a bed passes with the advisory.
- **The credit in the description.** `film_mix` collects each used track's `attribution`
  once into `production['audio']['attributions']` (assembler 5739-5741). On the one road every
  upload takes, `create_publication_intent` (`backend/app/publishing/services.py:1611-1628`)
  writes the film's sources, then `with_attributions(film_attributions(...))` (lines 849-869),
  then the AI disclosure footer; `_above_footer` (lines 872-883) keeps credits and footer whole
  inside YouTube's 5000 bytes and cuts the body instead. **So a Creative Commons credit needs
  nothing new: the copied text goes into the entry's `attribution` and the publisher writes it
  under the film.**
- **Other platforms.** TikTok is a catalogue entry only: «Publicarea TikTok nu este încă
  integrată» (`backend/app/integrations/catalog.py:105-121`). Where a track may travel is
  nevertheless decided at download time (§2.3), so it is written here now.
- **The release.** `scripts/make_release.py` ships everything under `config/` that
  `git ls-files --cached --others --exclude-standard` lists (lines 34-37, 128); `.gitignore` has
  no rule for audio files. A track dropped into `config/music/` would ship with the next
  release although its entry says `redistributable: false`. §4.1 says how to avoid that.

## 2. The YouTube Audio Library — the terms

### 2.1 What Google states (official help page, read 2026-10-11)

«Use music and sound effects from the Audio Library», support.google.com/youtube/answer/3376882
(the same text is served as answer/4523596; the page shows no «last updated» date):

- «Music and sound effects from the YouTube Audio Library are copyright-safe.» «Only music and
  sound effects from the Audio Library are known to YouTube to be copyright-safe.»
- «If you're in the YouTube Partner Program, you can monetize videos with music and sound
  effects from the Audio Library.» — **monetised videos are permitted.**
- «Copyright-safe music and sound effects downloaded from the Audio Library won't be claimed by
  a rights holder through the Content ID system.»
- «If you're using a track with a Creative Commons license, you must credit the artist in your
  video's description.» The filter bar offers «Attribution required» and «Attribution not
  required»; in the «License type» column the Creative Commons icon opens a pop-up whose
  **Copy** button gives the attribution text to paste into the description. A video that uses
  library music gets a «Music in this Video» section automatically, but for a Creative
  Commons track «the attribution info is still required in your video's description».
- Standard-licence tracks (the ones «that don't require attribution») need no credit.
- «The Audio Library is found exclusively in YouTube Studio» (sign in, then **Audio library**
  in the left menu; `youtube.com/audiolibrary` leads there). Download: «hover over the date and
  click DOWNLOAD to get an MP3 file». «New releases are added to the Audio Library twice a
  month.» A **Starred** tab keeps favourites.
- «YouTube can't give legal guidance, including guidance on issues with music that can occur
  off the platform. If you have questions about your use of music, you may wish to consult a
  qualified lawyer.»

The licence pop-up of a standard track read, as of 2021-01-05 (No Film School, quoting the
Studio UI): «You're free to use this audio track in any of your videos, including videos that
you monetize. No attribution is required.» The current wording is on his screen only; nothing
read suggests it changed, and it must be copied once into the licence text (§4.3) so the
ledger carries Google's own words.

Shorts specifically («Music eligibility for YouTube Shorts», answer/13486873): «You may also
use royalty-free music from the YouTube Audio Library. The royalty-free music won't receive a
Content ID claim.» The *Shorts audio library* of label music is another thing: it is applied
through YouTube's own creation tools, creates a special undisputable Content ID claim
(answer/13053317), and is not downloadable — an upload through the Data API, which is what
`YouTubeProvider` does, cannot use it. It is irrelevant to this studio.

### 2.2 What Google does not state

- No separate licence document exists for the library: the terms are the help page plus the
  per-track pop-up. YouTube's Terms of Service (effective 2022-01-05, «Permissions and
  Restrictions», item 1) forbid downloading content except as the Service expressly allows;
  the library's DOWNLOAD button is that allowance, for use «in your videos».
- The help page says nothing, for or against, about **using a standard-licence track outside
  YouTube**, about **redistributing** the file, or about **sublicensing**.

### 2.3 Outside YouTube (TikTok and other channels)

- **Standard licence**: Google is silent, and its only sentence on the matter is the «off the
  platform … consult a qualified lawyer» disclaimer. Third-party guides (LicenseOrg 2026,
  FoxiMusic updated 2026-10-02, lickd.co) read the standard licence as YouTube-only or «not
  explicitly covered» — none cites an official text, and the pop-up's «any of your videos» is
  ambiguous. **Conclusion: treat standard-licence tracks as YouTube-only until Google answers
  in writing** (YouTube Creator Support can be asked from his account; a written answer would
  be the evidence the ledger wants).
- **Creative Commons tracks (CC BY 4.0)**: the Creative Commons licence itself grants use on
  any platform, commercially, with the credit; it does not depend on YouTube. These are the
  tracks that can travel to TikTok. The «won't be claimed through Content ID» promise is
  YouTube's and does not travel: TikTok, Instagram and Facebook run their own detection with
  no such promise (Pixabay's FAQ documents exactly that experience for its own tracks).

### 2.4 Redistribution

Never, for either licence as far as the studio is concerned: a standard-licence track is
licensed for use *in videos*, not as a standalone asset (every guide read agrees: no
sublicensing, no delivery as a standalone file), and `redistributable: false` in the library is
the right value even for CC BY tracks, because the studio's release must not carry third-party
audio whose licence a buyer did not read. (Any buyer gets the empty library and the same
instructions, as `music_library.py`'s docstring intends.)

### 2.5 Content ID risk

YouTube's promise covers tracks **downloaded from the Audio Library in Studio**. The claims
third-party guides report come from: (a) a file that came from somewhere else (playlists or
channels named «Audio Library» / «No Copyright Music» — these are **not** Google's library,
and the help page disclaims «royalty-free» music from other channels), (b) a CC track whose
artist or distributor registered it elsewhere, (c) a misidentification. Mitigations the design
already has: the sha256 ties a film to the exact downloaded bytes; the licence text records
the date and the source; the publisher reads YouTube's remote state back. What it does not
have: Content ID claim status is not exposed by the Data API v3 (the Content ID API is for
partners), so a claim would be seen in Studio, by him, not by the studio — an open item (§7).

### 2.6 Conclusion on the terms

Free; usable in the channel's own videos including monetised ones; standard tracks need no
credit, CC tracks need the copied credit in the description (already written by the
publisher); YouTube-only for standard tracks until Google says otherwise, anywhere with credit
for CC tracks; never redistributed; Content ID-safe on YouTube for files downloaded from
Studio. For the one place the studio publishes today, this is exactly what the empty library
was built to hold.

## 3. Obtaining tracks — manual only; there is no API

### 3.1 No API, no feed

The YouTube Data API v3 reference (developers.google.com/youtube/v3/docs, read 2026-10-11) lists
these resources and nothing else: activities, captions, channelBanners, channelSections,
channels, commentThreads, comments, i18nLanguages, i18nRegions, members, membershipsLevels,
playlistItems, playlists, search, subscriptions, thumbnails, videoAbuseReportReasons,
videoCategories, videos, watermarks (and playlistImages in the navigation). **No resource lists,
searches or downloads Audio Library tracks**, and no RSS or bulk feed exists. The only way in is
YouTube Studio, signed in. Scraping Studio with his session, or third-party «YouTube to MP3»
tools, would need his login and breach the Terms of Service — the Director cannot bypass
login (`docs/architecture/00_MASTER_PROMPT.md` §6), and the studio never does it.

So: **the Owner downloads; the studio only reads what he put in the library.** That is the
design as written («the source of the music is the Owner's choice»), not a limitation to fix.

### 3.2 What Studio shows per track, and where it goes in our fields

| Studio (Music tab) | Our field | Note |
| --- | --- | --- |
| Track title, Artist name | `id` | a stable slug, e.g. `yal-dawn-of-the-nile`; recorded on every film that used it, so never renamed |
| — (tab) | `kind` | `music`; a download from the **Sound effects** tab is `ambience` |
| the MP3 | `file` | `music/<id>.mp3`, inside the library's folder |
| — | `sha256` | computed after download; the helper does it (§4.2) |
| License type (standard / CC icon), Date | `licence` | Google's words plus source and download date (§4.3) |
| «monetize videos with … the Audio Library» | `commercial_ok` | `true` |
| — | `redistributable` | `false` |
| CC pop-up «Copy» text | `attribution` | `null` for standard tracks; the copied text, verbatim, for CC tracks |
| Mood, Genre | `mood` | mapped to `MOOD_WORDS` keys (§3.3); several allowed |
| — | `bpm` | not shown in Studio; optional, may stay `null` |
| Sound effects: Category, title | `tags` | ambience only: the words a scene's `audio_intent` might use (`rain`, `wind`, `city`, `crowd`, `forest`) |
| Duration (seconds) | — | the bed is looped or cut to the film; prefer ≥ 60 s to avoid loop seams in a 60-180 s short |

### 3.3 Mood mapping (Studio filter → `MOOD_WORDS`)

Studio's Mood filter values, as the UI has shown them (to re-check on his screen): Angry,
Bright, Calm, Dark, Dramatic, Funky, Happy, Inspirational, Romantic, Sad; genres include
Ambient, Cinematic, Classical, Dance & Electronic, Jazz & Blues, Pop, Rock.

| Our mood | Download with Studio filters | Why |
| --- | --- | --- |
| `calm` | Mood Calm; genre Ambient or Classical | nature, quiet, slow scenes |
| `wonder` | Mood Inspirational or Bright; genre Ambient or Cinematic | space, discovery, beauty |
| `uplifting` | Mood Happy or Inspirational | hope, success, future |
| `tense` | Mood Dramatic or Dark; genre Cinematic or Dance & Electronic (pulse) | danger, risk, crisis |
| `mystery` | Mood Dark; genre Ambient | secrets, vanishings, the unknown |
| `dark` | Mood Dark or Sad | death, war, disaster, night |
| `epic` | Mood Dramatic; genre Cinematic | history, empires, battles |

Two tracks per mood (14) is the minimum for `choose_bed` to vary between successive films of
the same mood; a track may carry two moods (`["tense", "dark"]`) when it fits both.

## 4. Integration proposal (described, not coded)

### 4.1 Where the files live

Two places satisfy `music_library.py`'s rule that a file must sit inside the library's folder:

1. **Recommended: outside the repository**, through the existing `STUDIO_MUSIC_LIBRARY`
   variable: e.g. `E:\AMN_music\music_library.json` with the MP3s in `E:\AMN_music\music\`.
   Nothing to change in code or `.gitignore`; the release keeps shipping the empty
   `config/music_library.json`; a buyer fills his own. This is what the variable was written
   for (`music_library.py:36-37`). The studio reads the library once at start-up
   (`LIBRARY_PATH`), so a restart follows the first fill — his act, at a moment he chooses.
2. **Inside the repository**, `config/music/*.mp3` next to `config/music_library.json`. Then
   `.gitignore` must gain `config/music/` **before** the first download, or
   `make_release.py` (which packs untracked, non-ignored files under `config/`) ships
   non-redistributable audio. One line, but a code-adjacent change for the lead.

### 4.2 The helper command the studio could offer

A small operator script, `scripts/music_add.py`, run by the Owner per downloaded file — the
same shape as the other operator scripts (`scripts/backup.py`, `scripts/restore.py`):

- input: the MP3's path, `--source youtube-audio-library`, `--licence-type standard|cc-by`,
  `--title`, `--artist`, `--mood calm,wonder`, optional `--attribution "<pasted CC text>"`,
  optional `--kind ambience --tags rain,storm`, optional `--library <json>` (default: the
  library the studio reads, `LIBRARY_PATH`);
- it copies the file into the library's `music/` folder under `<id>.mp3`, computes the
  SHA-256, composes the licence text from a fixed template (§4.3) with today's date, refuses a
  duplicate id or a CC track without `--attribution`, appends the entry, then runs
  `music_library.load_library()` on the result and prints the entry's own refusal reason if it
  has one (the same words quality control would show), so a mistake is seen before a film is;
- `--check` alone lists every refused entry of the library with its reason (today that is
  visible only inside a film's QC report);
- it never downloads anything, never opens Studio, never touches `data/`; strings to the
  Owner in Romanian. The card's guided step (`sources.py:547-552`) can name the command instead
  of the bare file path once it exists.

A Settings page doing the same (upload the MP3, tick the licence type, paste the credit) is
the product-grade version; the script is the day-one version and needs one test file
(`tests/test_music_add.py`: an entry written, a duplicate refused, a CC track without a credit
refused, the sha256 matching the copied bytes).

### 4.3 What to write in each field

`licence` (shown to him in the ledger and QC, so Romanian; the template keeps Google's words
in English so the evidence is verbatim):

- standard track: «YouTube Audio Library, licență standard: „You're free to use this audio
  track in any of your videos, including videos that you monetize. No attribution is
  required.” Descărcat de Proprietar din YouTube Studio → Audio library la AAAA-LL-ZZ. Folosire
  în videoclipurile canalului, inclusiv monetizate; în afara YouTube neconfirmat de Google;
  nu se redistribuie.»
- Creative Commons track: «Creative Commons Attribution 4.0 (CC BY 4.0), prin YouTube Audio
  Library; descărcat de Proprietar din YouTube Studio la AAAA-LL-ZZ. Creditul din câmpul
  attribution este obligatoriu în descriere; folosire pe orice platformă cu credit; nu se
  redistribuie prin studio.»

`commercial_ok: true` (Google: monetised videos permitted); `redistributable: false` (§2.4);
`attribution: null` for standard tracks, the **Copy** text verbatim for CC tracks (multi-line
is fine: `with_attributions` writes the block once and dedupes on the whole string);
`mood` from §3.3; `bpm` omitted unless he counts it; `kind: ambience` + `tags` for sound
effects.

### 4.4 How the credit reaches the description (nothing to build)

`film_mix` → `production['audio']['attributions']` → `film_attributions` →
`with_attributions`, above the AI-disclosure footer and below the sources, once, inside 5000
bytes (§1). Quality control's audio verdict carries the same list (`qc.py:782`), so the credit
is visible before the upload. The automatic «Music in this Video» panel is not relied upon.

### 4.5 What to download first

Fifteen to twenty beds covering §3.3 (two or three per mood, «Attribution not required» first
so no description depends on a credit), plus four or five ambiences from the Sound effects
tab (rain, wind, city, crowd, forest — the words scenes' `audio_intent` uses). All from Studio,
never from a channel or playlist called «Audio Library». For a future TikTok channel, prefer
CC BY tracks for the moods it will need, or wait for Google's written answer on standard
tracks.

### 4.6 Small things the lead may want to change later (each with its test)

- `platforms` on an entry (`["youtube"]` vs `["any"]`), read by a second platform's publisher
  before it reuses a film; today unnecessary, written here so the licence texts above already
  say it in words.
- The music card is not withdrawn by code when the library gains a track (no
  `withdraw_owner_decision` for `MUSIC_KEY` in `decisions/sources.py`); it is a guided card he
  closes with «Am făcut-o», and it is not raised again while a usable music track exists
  (assembler 5709). Whether DONE re-reads the library's state was not verified here.
- The library is read at start-up only (`LIBRARY_PATH` module constant): a fill takes effect
  after a restart; a later refinement could read it per film.

## 5. Alternatives compared

Prices read 2026-10-11 from the vendors' pages where they rendered, else from aggregators that
state a verification date; all «per month». Content ID column: what the vendor promises on
YouTube.

| Source | Cost | Licence for a monetised short | Outside YouTube | Attribution | API | Content ID on YouTube |
| --- | --- | --- | --- | --- | --- | --- |
| **YouTube Audio Library** | 0 | yes (Google's page) | standard: unconfirmed; CC BY: yes with credit | none / CC credit | none; manual MP3 from Studio | Google: «won't be claimed» for Studio downloads |
| **ElevenLabs Music** (his paid plan) | 900 credits per minute of music, shared with narration; API list price $0.15/min | «Music commercial use» from Starter up; all self-serve tiers exclude film, TV, radio, Studio Games (model terms, last updated 2026-10-09); online video is permitted | yes (any online use); platform AI-disclosure rules apply (§4.4 of the terms) | none from Starter up (Free must denote Eleven Music) | yes, paid subscribers (`music_v2_5`) | no promise; a new composition each time |
| **Pixabay Music** | 0 | yes (Content License, updated 2024-11-18; commercial, no standalone sale) | yes | not required | images/videos only — **no music endpoint**; manual | tracks with a shield icon are Content ID-registered and may be claimed; dispute with the track URL; certificate for those tracks only |
| **Free Music Archive** | 0 | only tracks under CC BY / BY-SA / CC0; NC and ND tracks unusable | yes (CC) | required for every BY licence | none found (the old API is gone from RapidAPI); manual | claims possible; FMA says «reach out to the artists»; Tribe of Noise PRO sells cleared tracks |
| **Mixkit (Envato)** | 0 | yes (Stock Music Free License: YouTube, social, podcasts, online ads) | yes, online; not CDs, DVDs, games, TV/radio | «appreciated but not required» | none | not addressed by Mixkit; third parties report claims settled by e-mail |
| **Uppbeat** | Free: 3 downloads/month, ~25-30 % of the catalogue; paid Essentials $5.59 / Creator $7.99 / Pro $13.99 (pricing page as indexed 2026; older sources $6.99-8.25) | Free: personal channels and small creators, a unique Uppbeat credit **per video** in the description; paid: commercial, client work | paid plans cover other platforms | Free: required per video; paid: none | none | paid: channel safelisting (1/3/10 channels) clears claims; free: the credit |
| **Epidemic Sound** | Creator $9.99 yearly ($17.99 monthly), Pro $16.99 ($39.99), Business $30 ($75) (verified 2026-07-30) | yes; 1 channel per platform (Creator), 3 (Pro) | yes, covered channels | none | partner API for app builders (free prototyping ≤ 50 downloads, no commercial licence; Scale: custom) — not a creator plan | connected/safelisted channel; published films stay cleared after cancelling |
| **Artlist** | Music & SFX Social $14.99 monthly or $119.88 yearly (~$9.99); Pro $24.92 yearly; Max from $29.99-50.66 yearly (sources disagree) (verified 2026-07-24) | yes; Social: 1 channel per platform incl. TikTok, no client work; Pro: 3 per platform, client/ads/broadcast | yes | none | none public | «Projects published while the subscription is active stay licensed forever» |

Notes that matter for the decision:

- **ElevenLabs is not free music.** At 900 credits/min a 60-second bed costs 900 credits:
  about $0.18 on Starter ($6 / 30 000), $0.16 on Creator ($22 / 121 000), $0.15 on Pro
  ($99 / 600 000) — and those credits are the narration's credits. Two films a day generated
  fresh is ~54 000 credits a month, more than Starter holds. The sensible use is the library's
  own: **generate once per mood, fourteen 60-second beds ≈ 12 600 credits (≈ $2.30 on
  Creator), keep the MP3s in the library with the licence text citing the plan tier and the
  model terms date, and reuse them.** Each generation is a paid step: his button, through the
  money staircase, never pressed by the studio on its own (Owner rules 2026-10-09 and
  2026-09-17). Which tier he holds decides eligibility («Individual use only» on Starter-Pro;
  entities under 10 employees from Scale) and must be read from his account, not assumed.
  Outputs are his («you retain any and all rights in and to your Input and Output», §2.2), but
  no vendor promises Content ID silence for generated music.
- **Pixabay** is the 0-cost source that travels to every platform without a credit, with the
  one caveat of its own making: skip tracks with the shield icon (Content ID-registered) and
  keep the track URL in the licence text for a dispute.
- **Paid catalogues** (Uppbeat, Epidemic, Artlist) buy channel safelisting and a bigger
  catalogue; for a bed ducked 20 LU under narration in a factual short, the catalogue size is
  not the constraint and the monthly fee is not 0.

## 6. Recommendation (publish daily, 0 extra cost first)

1. **YouTube Audio Library, standard («Attribution not required») tracks, now.** Cost 0,
   Google's own Content ID promise on the only platform the studio publishes to today, no
   credit to manage, and the library design already holds it (file + sha256 + licence +
   `commercial_ok`). His work: one session in Studio downloading §4.5's list, then one helper
   command per file (or hand-written JSON entries until the script exists), one restart.
2. **Keep the library outside the repository** via `STUDIO_MUSIC_LIBRARY` (§4.1 option 1), so
   no release ever ships audio he may not redistribute. If the lead prefers `config/music/`,
   the `.gitignore` line comes first.
3. **Write the licence text with Google's words and the date** (§4.3). The ledger then shows
   evidence, not an opinion, and a buyer reads the same words.
4. **CC BY tracks are fine too**, and they are the ones that may follow a film to TikTok; the
   publisher already writes the credit. Choose them for moods a second platform will need.
5. **Second tier, later:** Pixabay (shield-free tracks) when TikTok publishing exists and
   standard tracks must stay on YouTube; ElevenLabs as a one-off generation of a signature
   theme for the serial, reused, under his button. No paid catalogue is needed for this
   format.
6. **Nothing in the pipeline changes for step 1.** The only code anyone writes is the helper
   script and its test, plus the `.gitignore` line if option 2 is chosen.

## 7. Open questions

For the Owner:

- Which ElevenLabs tier does he hold (Starter / Creator / Pro)? It sets the music credits and
  the eligibility row; the music is not worth a tier change.
- When does TikTok (or another channel) publish? Until then standard tracks suffice; from
  then, CC BY or Pixabay tracks for the shared moods, or a written answer from YouTube Creator
  Support on standard tracks off-platform.
- The current licence pop-up wording and the mood/genre vocabulary are on his screen; one
  screenshot settles §2.1's quote and §3.3's filter names.

For the lead:

- Library location: `STUDIO_MUSIC_LIBRARY` outside the repo (recommended) or `config/music/`
  plus `.gitignore`.
- The helper: `scripts/music_add.py` now, a Settings page later; the music card's guided step
  then names it.
- Content ID claims are invisible to the studio (Data API v3 has no claims resource); a
  periodic reminder in his letters («verifică reclamațiile în Studio») or nothing — his call.
- Whether the music card's DONE re-reads the library (not verified here), and whether the
  library should be re-read per film instead of at start-up.
- A `platforms` field on entries, only when a second publisher exists.

## Sources (read 2026-10-11 unless dated)

- YouTube Help, «Use music and sound effects from the Audio Library»:
  https://support.google.com/youtube/answer/3376882 (also answer/4523596)
- YouTube Help, «Music eligibility for YouTube Shorts»:
  https://support.google.com/youtube/answer/13486873
- YouTube Help, «Manage Shorts as a rights holder» (Shorts audio library claims):
  https://support.google.com/youtube/answer/13053317
- YouTube Terms of Service, effective 2022-01-05: https://www.youtube.com/t/terms
- YouTube Data API v3 reference (resource list): https://developers.google.com/youtube/v3/docs
- No Film School, 2021-01-05, quoting the standard-licence pop-up:
  https://nofilmschool.com/youtube-audio-library-free-download
- LicenseOrg guide (third party, 2026): https://licenseorg.com/guide/music-audio/youtube-audio-library
- FoxiMusic guide, updated 2026-10-02 (third party): https://www.foximusic.com/blog/?p=546
- ElevenLabs, Music capability docs: https://elevenlabs.io/docs/overview/capabilities/music
- ElevenLabs, API pricing (Music $0.15/min): https://elevenlabs.io/pricing/api
- ElevenLabs, plans (Eleven Music 900 credits per minute; «Music commercial use» from Starter):
  https://elevenlabs.io/pricing
- ElevenLabs, Eleven Music model-specific terms, last updated 2026-10-09:
  https://elevenlabs.io/eleven-music-model-specific-terms
- Pixabay Content License summary and Terms (last updated 2024-11-18):
  https://pixabay.com/service/license-summary/ , https://pixabay.com/service/terms/
- Pixabay FAQ (music, Content ID, disputes): https://pixabay.com/service/faq/
- Pixabay API docs (images and videos only): https://pixabay.com/api/docs/
- Free Music Archive, License Guide and FAQ: https://freemusicarchive.org/License_Guide ,
  https://freemusicarchive.org/faq/
- Mixkit, licence summary and music FAQ: https://mixkit.co/license/ ,
  https://mixkit.co/free-stock-music/ , https://mixkit.co/llm-info/
- Uppbeat pricing (page rate-limited on fetch; figures from its indexed text and
  https://licenseorg.com/guide/music-audio/uppbeat): https://uppbeat.io/pricing
- Epidemic Sound pricing (page prices did not render; figures verified 2026-07-30 by
  https://photutorial.com/epidemic-sound-pricing) and developer API:
  https://www.epidemicsound.com/pricing/ , https://developers.epidemicsound.com/
- Artlist pricing (page refused the fetch; figures verified 2026-07-24 by
  https://recurdash.com/subscription-pricing/artlist): https://artlist.io/pricing
