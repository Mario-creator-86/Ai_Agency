# The daily pipeline, stage by stage — what runs and what each stage refuses — 2026-09-11

The Owner's studio had everything connected and still produced nothing: the publishing screen
answered "Internal error", the preflight said there was no image provider and no default
voice, analytics said there was no verified account, and idea generation was skipped with "no
implementation". This is the audit of every stage of
`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` against the code, and what was added.

## What was actually wrong

| Screen said | Cause | Fixed by |
|---|---|---|
| "Eroare canale / publicații: Internal error" | `GET /publishing/channels` asked `selected_youtube()` for the studio's one publisher; with two accounts connected and no slot naming either, it refuses — and the refusal became a 500. One failed request, and the page printed the error into both panels. | Publishing is per slot, so the endpoint answers per slot: which account each channel is bound to, and which accounts exist to bind. |
| "Niciun cont YouTube verificat pentru analytics" | Both accounts were CONNECTED, but neither channel slot named one (`credentials_ref` empty), and the analytics adapter refuses to attribute one channel's numbers to another. | The slot's binding names the account; the preflight reports unbound slots as the missing step, and the publishing screen binds them in one click. |
| "Niciun serviciu ales pentru Imagini · NO_SELECTION" | Runway was verified and selected for `video`; nothing was selected for `image`. Connecting a vendor and choosing what it does are two different acts, and the second was invisible. | `POST /settings/auto-configure`: selects a service for a purpose **only where one candidate exists**, and fills only empty defaults. |
| "…dar nu are un model și o voce implicită · NO_DEFAULT" | ElevenLabs had 9 models and 21 voices discovered and no Organization default. | The same command, choosing the top of `rank_candidates` — the order `strategy: auto` already uses — and saying what it chose. |
| "Generare idei: SKIPPED — nicio implementare" | True: topics were only ever typed in by the Owner. | The Lead Researcher proposes a scored, deduplicated pool (§3) and fetches its own pages (§4). |

## Stage by stage

| § | Stage | Who does it | What it refuses |
|---|---|---|---|
| 1 | Preflight | code | Rounds nothing up: a missing provider, an unbound channel or an untested source site degrades the day and names the action. |
| 2 | Performance intake | code + the bound account | Measuring through an unbound account: with several connected, whose numbers these are is not knowable. |
| 3 | **Idea generation** | Lead Researcher | A candidate that repeats an existing title (word-set similarity ≥ 0.6) or expects evidence on a site the Owner never authorised. |
| 4 | **Research and verification** | Lead Researcher, then Fact Checker | A URL outside the allowlist is refused before any request; a page that does not answer is recorded, not invented. A verdict without a verbatim quote from the stored text is rejected. |
| 5 | **Selection** | Director | A choice naming a topic that is not on the shortlist. Only topics with at least one SUPPORTED claim are on it. |
| 6 | Script and storyboard | Script Writer | A sentence that cannot cite a supplied claim; a fabricated citation fails the whole draft. |
| 7 | Serial queue (since 2026-09-17 before media, so the same run films the episode) | Showrunner writes, Director reviews | An episode citing an event the day's public-safe projection does not hold; a private word in a title or a line. |
| 8 | Media | code, with the Voice Artist reviewing narration | Rendering with a model the account does not have; a locked character rendered by an unapproved model. |
| 9 | Edit and QC | code, with the Video Editor diagnosing failures | Measurement from the database row instead of the file; a placeholder frame reaching publication. |
| 10 | Publish | Publisher prepares metadata, code holds the five gates (a sixth for a film that would be seen) | Publishing past a failed gate, to an unbound slot, or with a description that adds facts the script does not contain. |
| 11 | Post-run | Director | Deciding anything about a person or a channel on fewer than three samples. |
| 12 | Daily log | code | Writing a log for a day the studio did not work. |

## The two new agent stages

**Idea generation** (`backend/app/research/agent.py::propose_topics`). The Researcher is given
the authorised hosts, the recent topic titles and the channel's topic weights, and returns
candidates scored on the runbook's six criteria (interest, credibility, source availability,
visual potential, novelty, cost); the composite is their mean, so one strong number cannot
carry a candidate. Each is stored as `TopicIdea` PROPOSED with `scores_json`,
`source_plan_json` and the proposing employee. Duplicates and unauthorised hosts are dropped
with the reason, and the surviving candidates are handed to the Director as a message.

**Source gathering** (`…::gather_sources`). Since 2026-09-18 the studio looks for the pages
itself first (`find_pages`): each authorised site's own search address — the one the Owner
typed, else the one discovered on the site's front page — and then, when a search engine is
connected and verified, the addresses it names, filtered against the allowlist before anything
downstream sees them. Where that found pages, the Researcher's plan is a choice among them and
a guessed address is set aside unread; where it found none, the Researcher names pages on
authorised hosts as before. The studio fetches each through the same retriever the Owner's own
"add source" button uses, never an engine's copy. This is what keeps it honest: a URL the model invented
does not resolve and is recorded as failed, and one that does resolve is stored with the text
that came back — never with the text the model expected. The Fact Checker still has to find
each claim in that text, verbatim.

**Selection** (`backend/app/agents/director.py::choose_topic`). With more than one producible
candidate the Director chooses and says why (`decided_by`, `decision_notes` on the topic).
With one candidate there is nothing to decide; with no language model the studio falls back to
the deterministic order and records that nobody decided it.

## Auto-configure

`POST /settings/auto-configure` (button in Settings → Video și sunet) exists because the Owner
was right: a verified connection should not need a second, hidden step. It:

- selects a service for a purpose **only when exactly one verified connection can serve it**
  (the account's own catalogue must contain a usable resource — a Runway key whose
  organisation exposes no video model is not a video provider);
- reports an ambiguous purpose instead of resolving it;
- fills **only empty** defaults, preferring a model the pipeline can actually call from a
  prompt (`text_to_video` / `image_to_video` / `text_to_image`) over one that needs an input
  the storyboard does not have;
- never replaces a choice the Owner made, and lists every choice with its reason.

## Remaining limitations

- The Researcher still names URLs from what it knows when nothing was found, on hosts the Owner
  authorised, and the fetch is the check. (Corrected 2026-09-18: the studio now finds pages
  through each site's own search address, discovered as well as typed, and through a web search
  engine the Owner connects — which may name addresses and nothing else, filtered to the
  allowlist. No engine is connected on the live studio, and the allowlist cannot be widened by
  an agent, a request or a result.)
- `gather_sources` reads `STUDIO_RESEARCH_CANDIDATES_PER_DAY` candidates at
  `STUDIO_RESEARCH_PAGES_PER_TOPIC` pages (four and four, clamped 1..12; two and four before
  2026-09-18): this is reading, not crawling.
- A topic proposed today usually becomes producible tomorrow: the claims extracted from
  today's pages are verified in the same stage, but a page fetched late in the stage is read
  on the next run.
- Analytics measures through the first bound slot; per-channel measurement needs one call per
  binding, which the ingest loop does not do yet.
