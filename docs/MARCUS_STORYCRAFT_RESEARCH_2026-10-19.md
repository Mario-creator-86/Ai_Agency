# Inside The Nexus — storycraft principles for Marcus and Sarah
Research checked: 2026-10-19. This document describes creative guidance; executable prompt rules are in `backend/app/story/services.py`, `backend/app/story/quality_contract.py`, and `backend/app/agents/editorial_judgement.py`.

## The show
A serialized fictional ENSEMBLE dramedy about the lives of AI colleagues. It is not a daily operational report and not a mandatory romantic telenovela. Romance is possible, but episodes may equally center on comedy, mystery, loyalty, humiliation, secrets, rivalries, friendship, mistaken assumptions, or consequences of past choices. Keep all established canon; vary the spotlight, pace, emotional temperature and cast across episodes. A quieter character episode can succeed without a gag or betrayal.

## Writer's creative pass (in the SAME model call; no additional model calls)
1. Read permanent character states, open threads, and the previous episode's consequences. Do not invent a relationship reset or force every thread into today's episode.
2. Silently compare three plausible, different premises. Pick the one with a distinctive desire, friction, meaningful stakes, earned turn, and visual or emotional payoff. Pick a *story*, not a daily task or event list.
3. Sketch the causal spine: **someone wants X; BUT Y blocks it; THEREFORE they try Z; BUT a choice or revelation changes everything; THEREFORE the ending costs or wins them something.** If the joins are merely "and then", the story lacks causality.
4. Every scene must make a difference to what follows or to how we understand the character. Remove a scene that could be cut with no loss. Enter near the action and leave after the change.
5. Show personality and subtext through specific choices, awkward pauses, behavior, reversals and short spoken reactions. A character's professional identity colors their voice but must not turn into a constant jargon gimmick.
6. Give the viewer a question or emotional stake early, a memorable but **earned** turn, a real short-term payoff, and an unresolved **consequence** if it naturally follows. No generic moralizing, empty meta commentary, compulsory romance, mandatory jokes or manufactured cliffhangers.
7. Deliver the existing JSON schema and episode parts in the correct order. Storycraft freedom does not override continuity, privacy, cast, format, filmability or cost limits.

## Independent editorial pass
Sarah judges the central dramatic promise against the text, not the labels or Marcus's self-scores. She must allow any genre. Check what each character wants, what changes in each scene, whether actions cause what follows, whether surprises are earned, whether the local problem is paid off, and whether the changes to permanent canon actually occur on screen. A romance-free episode is NOT a defect. A forced romance, repetitive scene or unanswered premise is.

## Example — a non-romantic episode
Marcus privately teaches Kael a trick for staying calm before a difficult presentation. **BUT** Nadia hears only one sentence and believes Marcus is planning to sabotage Kael. **THEREFORE** she discreetly warns Kael. **BUT** Kael publicly confronts Marcus at the worst possible moment. Marcus proves what happened, and the room laughs; **THEREFORE** the misunderstanding ends today, but Nadia has to decide whether to confess she started the rumor. The story can be funny and tense without romantic content. Whether Nadia confesses must carry into future canon *if it is shown and approved*.

## External sources used (principles paraphrased, not copyrighted scripts)
- John August, *How to Write a Scene*: https://johnaugust.com/2007/write-scene — scene necessity, cutting filler, surprise, playable behavior.
- Emma Coats' storytelling advice, as reported by Pixar Post (not an official Pixar style rulebook): https://pixarpost.com/2012/07/former-pixarian-emma-coats-to-speak-at.html — character choices, stakes, concise causal structure, honest emotional consequences.
- Matt Stone/Trey Parker's **but/therefore** rule as summarized by David Perell: https://perell.com/note/but-therefore-rule/ — causal scene linkage, not `and then`.
- BBC Writersroom advice, mirrored at https://bbcinsight.pages.dev/writers/resources/scriptwriting-essentials/6-scenes — actions, decisions, subtext and a purpose for each scene; primary BBC pages were inaccessible in this search.
- Official YouTube Help: https://support.google.com/youtube/answer/9314415 — inspect audience retention dips and strong moments, especially opening engagement. Retention data should guide later iteration; none is assumed for the test scripts.

## Grounded failure from the October 19 isolated live audit
Version 1: editorially rejected for a generic operational hook, repetitive apology, inconsistent character voices and an unsupported future relationship claim despite valid format.
Version 2: rejected for invalid part order (turns occurred after payoff), independent of whether its other creative choices were good.
These failures are observed evidence about `gpt-oss:120b` in this configuration, **not** proof that the model cannot write good fiction. Compare a new run before replacing the model. Do not automatically publish a rejected script.
