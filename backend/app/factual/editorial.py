"""What is worth saying, and whether the script says it.

The studio could research a fact, verify it, write narration that cited it, and produce a
film nobody would watch — because nothing in the pipeline ever asked *why this video should
exist*. The Owner's verdict on the first real film was exact: "sunt doar niste imagini
lipite", and later, "filmul nu se incadreaza deloc". Both were content failures, and no
video model can repair either.

This module is the studio's editorial judgement about content, and it holds only judgement
that can be stated as a rule. Everything here is deterministic and cheap: it runs before an
agent is asked anything and before a single shot is bought.

- **An idea needs an argument.** `IDEA_WEIGHTS` says which dimensions decide (a beautiful
  topic with no payoff must not win), `composite` weights them instead of averaging, and
  `idea_rejections` lists the editorial rules a candidate failed.
- **A story needs a shape.** `SCENE_PURPOSES` are the parts a shot can play, `story_checks`
  asks whether the script actually has a hook, a progression, a payoff that answers the hook,
  an ending, and a call to action that belongs to this story rather than to any story.
- **Narration has a length.** `expected_seconds` measures the script against the studio's own
  speaking rate, so thirty seconds of film never carries sixty seconds of words.

The scoring is an opinion about a candidate. It is never evidence about the world: that is
what claims and sources are for, and nothing here can make an unverified statement usable.
"""

from __future__ import annotations

import re
from typing import Any

#: The dimensions an idea is judged on, and how much each decides. Twelve equal numbers would
#: let a beautiful, pointless topic beat a story with a real payoff — which is what happened:
#: six equal criteria had the studio producing whatever scored well on "visual potential".
#: Hook, payoff and story carry the most, because they are what a viewer actually experiences;
#: fact confidence carries as much, because a factual channel that is wrong is worth nothing.
IDEA_WEIGHTS: dict[str, float] = {
    "hook_potential": 0.14,
    "payoff_strength": 0.14,
    "story_potential": 0.13,
    "fact_confidence": 0.13,
    "curiosity": 0.10,
    "retention_potential": 0.09,
    "channel_fit": 0.07,
    "visual_potential": 0.06,
    "originality": 0.05,
    "shareability": 0.04,
    "cta_opportunity": 0.03,
    "production_feasibility": 0.02,
}

#: Dimensions no idea may be weak in, whatever its total. A film whose hook nobody stops for
#: is not saved by being cheap to make, and a fact the studio cannot stand behind is not a
#: story at all. Read as: below this, the idea is refused rather than ranked.
IDEA_FLOORS: dict[str, float] = {
    "hook_potential": 0.45,
    "payoff_strength": 0.45,
    "story_potential": 0.40,
    "fact_confidence": 0.55,
}

#: And the total a candidate needs before the Director is asked to choose at all.
IDEA_MINIMUM_COMPOSITE = 0.50

#: The parts a shot can play in a thirty-second film. A shot that plays none of them is
#: decoration: it is cut or redesigned, never filmed (the Owner paid for eight of those).
SCENE_PURPOSES = (
    "HOOK",
    "SETUP",
    "DEVELOPMENT",
    "EVIDENCE",
    "REVEAL",
    "PAYOFF",
    "ENDING",
    "CTA",
)
#: The purposes that count as the film paying off what its hook promised.
PAYOFF_PURPOSES = ("REVEAL", "PAYOFF")

#: How a call to action can belong to the story. The kind is recorded so the studio can see
#: later which kinds actually earned comments, instead of appending the same line to every film.
CTA_KINDS = ("CURIOSITY", "DECISION", "KNOWLEDGE", "DEBATE", "FOLLOW", "SERIES", "COMMENT")

#: Openings that promise nothing. Not banned because they are ugly: they spend the only three
#: seconds that decide whether anyone watches on saying that a video is about to happen.
WEAK_OPENINGS = (
    "did you know",
    "today we",
    "today, we",
    "in this video",
    "here is an interesting",
    "here's an interesting",
    "let me tell you",
    "have you ever wondered",
    "welcome back",
)

#: Connectives that carry a story forward, and the ones that only stack facts. A script whose
#: scenes are joined by "and then" is a list; one joined by "because" and "but" is a story.
CAUSAL_CONNECTIVES = (
    "because",
    "so ",
    "but ",
    "until",
    "which means",
    "that is why",
    "that's why",
    "therefore",
    "instead",
    "yet ",
    "however",
    "unless",
)
WEAK_CONNECTIVES = ("and then", "also,", "another thing", "additionally", "furthermore")

#: Calls to action that belong to no film in particular.
GENERIC_CTAS = (
    "like and subscribe",
    "like, comment",
    "don't forget to subscribe",
    "smash that",
    "hit the bell",
    "subscribe for more",
)

#: How fast the studio's narration is actually spoken, in words a second, and what a scene
#: change costs in breath. Measured from renders the studio produced, not assumed: narration
#: written for sixty seconds inside a thirty-second film is how a film ends before its words.
WORDS_PER_SECOND = 2.6
SCENE_BEAT_SECONDS = 0.35

#: How far a narration may sit from its target before the story review sends it back. The
#: brief the writer receives and the check that judges him read this same number, because a
#: writer told "78 words" and refused at 102 was never told where the line was.
#:
#: Wide on purpose. It was 0.3, and a 41-second story was refused twice against a 39-second
#: ceiling — over a handful of words, on a film that was otherwise sound. The Owner settled it:
#: "it is fine if it goes over by a few words, not all videos are the same." The target is what
#: the writer aims at; this check exists for the failure it was written for — sixty seconds of
#: narration inside a thirty-second film — not to shave sentences.
DURATION_TOLERANCE = 0.5

#: The longest a short may be, whatever its target. Past this the format itself is gone, which
#: is a refusal no tolerance should reach over.
MAX_SHORT_SECONDS = 60.0

#: What one beat of narration weighs. A scene under this is not a beat of its own; a scene far
#: over it is two beats wearing one number, and the film runs long while every scene looks
#: short. Measured against the drafts the studio actually produced: left to itself the writer
#: lands near 21 words a scene, which is a 40-second film wearing a 30-second brief.
WORDS_PER_SCENE = 15

#: The most scenes a short may carry, wherever the number is needed: the writer's schema
#: rejects a draft with more, and the budget never asks for more.
MAX_STORY_SCENES = 12

#: The shape of a short, as fractions of its own length. At 30 seconds this is the table the
#: studio has always used — 0-3s hook, 3-8s setup, 8-18s development, 18-26s payoff, 26-30s
#: ending — and at any other length it stays true instead of promising seconds the film does
#: not have.
STORY_BEATS = (
    ("HOOK", 0.0, 0.10),
    ("SETUP", 0.10, 0.27),
    ("DEVELOPMENT / EVIDENCE", 0.27, 0.60),
    ("REVEAL / PAYOFF", 0.60, 0.87),
    ("ENDING + CTA", 0.87, 1.0),
)


def narration_budget(target_seconds: float) -> dict[str, Any]:
    """How much narration a film of this length affords — and how many scenes that is.

    The writer used to be told the total words and nothing else, while the same brief offered
    him up to twelve scenes and eight story purposes to fill. Seventy-eight words across seven
    scenes is eleven words a scene, which no one writes; he wrote twenty-one, and the duration
    check refused a film that was otherwise sound. The arithmetic belongs in the brief, not in
    the writer's head: this returns the total, the window the check will actually allow, the
    number of scenes the budget affords, and what one scene may weigh.
    """
    target = max(float(target_seconds), 0.0)

    # A film is its words plus its breaths: `expected_seconds` charges SCENE_BEAT_SECONDS for
    # every scene change, so the seconds left for words are fewer than the film is long. The
    # brief used to state a ceiling computed from words alone, which was five words looser
    # than the ceiling the check applied — and the writer, obeying the brief, was refused for
    # it. The scene count decides how much breath is spent, so it is settled first from the
    # beat-free estimate and the words are then priced against what remains.
    def words_in(seconds: float, scene_count: int) -> float:
        return max(0.0, (seconds - scene_count * SCENE_BEAT_SECONDS) * WORDS_PER_SECOND)

    outer = min(target * (1.0 + DURATION_TOLERANCE), MAX_SHORT_SECONDS) if target else 0.0
    spoken = target * WORDS_PER_SECOND
    # Three scenes is the fewest that can hold a hook, a middle and a payoff; beyond the cap
    # the film is a list again. Between those, the length decides.
    scenes = max(3, min(MAX_STORY_SCENES, int(round(spoken / WORDS_PER_SCENE)))) if target else 0
    total = words_in(target, scenes)
    ceiling = words_in(outer, scenes)
    floor = words_in(target * (1.0 - DURATION_TOLERANCE), scenes)
    per_scene = total / scenes if scenes else 0.0
    return {
        "target_seconds": round(target, 1),
        "max_seconds": round(outer, 1),
        "total_words": int(round(total)),
        "max_words": int(ceiling),
        "min_words": int(round(floor)) + 1,
        "scenes": scenes,
        "words_per_scene_low": max(6, int(per_scene * 0.8)),
        "words_per_scene_high": int(per_scene * 1.2) + 1,
        "beats": [
            (name, round(target * start, 1), round(target * end, 1))
            for name, start, end in STORY_BEATS
        ],
    }


def beat_table(target_seconds: float, indent: str = "  ") -> str:
    """The shape of the film, written out in its own seconds."""
    return "\n".join(
        f"{indent}{start:.0f}-{end:.0f}s{' ' * max(1, 8 - len(f'{start:.0f}-{end:.0f}s'))}{name}"
        for name, start, end in narration_budget(target_seconds)["beats"]
    )


#: Words that carry no subject. Used to ask whether an ending answers its own hook, and
#: whether a call to action belongs to this story — both by shared content words, which is
#: crude, checkable, and impossible to fake by writing more.
STOPWORDS = frozenset(
    """a an and are as at be been but by can could did do does for from had has have he her him his
    how i if in into is it its me my no not of on or our out she so some than that the their them
    then there these they this those to too us was we were what when where which who why will with
    would you your it's don't doesn't""".split()
)


def content_words(text: str) -> set[str]:
    """The words in a line that carry its subject, lowercased and stripped of endings."""
    words = {w for w in re.findall(r"[a-z0-9']+", str(text).lower()) if len(w) > 2}
    return {w.rstrip("'s") for w in words - STOPWORDS}


def composite(scores: dict[str, Any]) -> float:
    """One number for an idea, weighted by what actually decides whether a film works.

    Dimensions the proposer did not score are left out of both the sum and the weight, so a
    partial answer is scored on what it did say rather than punished to zero.
    """
    total = 0.0
    weight = 0.0
    for key, share in IDEA_WEIGHTS.items():
        value = scores.get(key)
        if isinstance(value, int | float):
            total += float(value) * share
            weight += share
    return round(total / weight, 4) if weight else 0.0


def expected_seconds(scenes: list[dict[str, Any]] | str, *, beats: bool = True) -> float:
    """How long this narration actually takes to say, at the studio's own speaking rate.

    Accepts the scene list or one block of text. Scene changes add a beat, because a viewer
    needs a moment to see where they are — "fast" and "incomprehensible" are not the same.
    """
    if isinstance(scenes, str):
        words = len(scenes.split())
        return round(words / WORDS_PER_SECOND, 2)
    words = 0
    for scene in scenes:
        words += len(str(scene.get("narration") or scene.get("voiceover_segment") or "").split())
    seconds = words / WORDS_PER_SECOND
    if beats and scenes:
        seconds += SCENE_BEAT_SECONDS * max(0, len(scenes) - 1)
    return round(seconds, 2)


# ----------------------------------------------------------------------------- the idea


def idea_rejections(thesis: dict[str, Any], scores: dict[str, Any]) -> list[str]:
    """The editorial rules this candidate fails. Empty means it may be ranked.

    Every rule here is one the Owner stated: a video must exist for a reason, and the reason
    has to be answerable before anything is produced. A topic that sounds interesting, is
    recent, is trending, or would look beautiful is not thereby approved.
    """
    reasons: list[str] = []
    thesis = thesis if isinstance(thesis, dict) else {}

    def missing(field: str, question: str) -> None:
        if len(str(thesis.get(field) or "").strip()) < 12:
            reasons.append(f"{question} ({field} nu are răspuns)")

    missing("why_it_matters", "De ce contează asta pentru cineva?")
    missing("payoff", "Cu ce rămâne spectatorul la final?")
    missing("hook", "Ce îl face să nu dea scroll în primele trei secunde?")
    missing("core_fact", "Care este faptul pe care se sprijină filmul?")
    missing("ending", "Cum se închide filmul?")
    if len(str(thesis.get("cta") or "").strip()) < 6:
        reasons.append("Nu are un îndemn final care să aparțină acestei povești (cta)")

    for key, floor in IDEA_FLOORS.items():
        value = scores.get(key)
        if isinstance(value, int | float) and float(value) < floor:
            reasons.append(f"{key} este {float(value):.2f}, sub minimul {floor:.2f}")

    total = composite(scores)
    if total < IDEA_MINIMUM_COMPOSITE:
        reasons.append(f"scor compozit {total:.2f}, sub minimul {IDEA_MINIMUM_COMPOSITE:.2f}")

    seconds = thesis.get("expected_seconds")
    if isinstance(seconds, int | float) and not 12 <= float(seconds) <= 90:
        reasons.append(f"lungimea propusă ({float(seconds):.0f}s) nu este un short")

    # A hook that promises what the payoff does not deliver is the one thing worse than a
    # weak hook: the viewer was told a lie to make them stay.
    hook_words = content_words(str(thesis.get("hook") or ""))
    payoff_words = content_words(
        str(thesis.get("payoff") or "") + " " + str(thesis.get("ending") or "")
    )
    if hook_words and payoff_words and not (hook_words & payoff_words):
        reasons.append("Finalul nu răspunde la ce promite hook-ul (nimic comun între ele)")

    cta = str(thesis.get("cta") or "").lower()
    if any(generic in cta for generic in GENERIC_CTAS):
        reasons.append("Îndemnul final este generic, nu ține de povestea asta")
    return reasons


# ----------------------------------------------------------------------------- the story


def _check(passed: bool, reason: str) -> dict[str, Any]:
    return {"passed": bool(passed), "reason": reason}


def story_checks(
    *,
    title: str,
    scenes: list[dict[str, Any]],
    story: dict[str, Any],
    target_seconds: float,
    tolerance: float = DURATION_TOLERANCE,
) -> dict[str, dict[str, Any]]:
    """Everything about a script that can be checked without asking a model.

    Each answer carries its reason, so a revision request can name what is wrong instead of
    telling the writer to try harder. These are the questions the Owner listed: does the
    opening create interest, is there one central idea, does every scene advance the story,
    is there a real payoff, does the ending resolve the hook, is every statement attributed,
    is the length realistic, does the call to action fit.
    """
    story = story if isinstance(story, dict) else {}
    narrations = [str(s.get("narration") or s.get("voiceover_segment") or "") for s in scenes]
    purposes = [str(s.get("purpose") or s.get("story_purpose") or "").upper() for s in scenes]
    joined = " ".join(narrations).lower()
    first = narrations[0].strip().lower() if narrations else ""
    seconds = expected_seconds(scenes)

    hook_text = str(story.get("hook") or (narrations[0] if narrations else ""))
    payoff_indexes = [i for i, p in enumerate(purposes) if p in PAYOFF_PURPOSES]
    tail = " ".join(narrations[payoff_indexes[0] :]) if payoff_indexes else ""
    cta = str(story.get("cta") or "")

    checks = {
        "has_hook": _check(
            bool(purposes and purposes[0] == "HOOK"),
            "Prima scenă trebuie să fie hook-ul.",
        ),
        "hook_is_not_generic": _check(
            bool(first) and not any(first.startswith(weak) for weak in WEAK_OPENINGS),
            "Deschiderea nu poate fi «did you know» sau «in this video»: primele trei "
            "secunde decid dacă cineva se uită.",
        ),
        "every_scene_has_a_purpose": _check(
            bool(purposes) and all(p in SCENE_PURPOSES for p in purposes),
            "Fiecare scenă trebuie să declare de ce există: " + ", ".join(SCENE_PURPOSES) + ".",
        ),
        "every_scene_is_attributed": _check(
            bool(scenes) and all(list(s.get("claim_ids") or []) for s in scenes),
            "Fiecare scenă se sprijină pe cel puțin o afirmație verificată.",
        ),
        "has_payoff": _check(
            bool(payoff_indexes) and payoff_indexes[0] >= max(1, len(scenes) // 2),
            "Trebuie să existe o scenă de REVEAL sau PAYOFF, în a doua jumătate a filmului.",
        ),
        # Does the film close — not: is there a scene wearing the label. A draft was sent
        # back twice for this while ending on "after eleven years of defending the planet, it
        # became a streak of fire in the sky" and a CTA of its own: the writer had spent all
        # five scenes the brief allowed on HOOK, SETUP, DEVELOPMENT, EVIDENCE and PAYOFF, and
        # delivered the close inside the last of them. The label is evidence, not the fact.
        "has_ending": _check(
            "ENDING" in purposes
            or "CTA" in purposes
            or (
                len(str(story.get("ending") or "").strip()) >= 12
                and bool(
                    content_words(str(story.get("ending")))
                    & content_words(narrations[-1] if narrations else "")
                )
            ),
            "Filmul trebuie să se închidă, nu să se opreasca: ultima scenă duce finalul "
            "declarat în «ending», sau poartă eticheta ENDING / CTA.",
        ),
        "ending_answers_the_hook": _check(
            bool(content_words(hook_text) & content_words(tail)) if tail else False,
            "Finalul trebuie să răspundă la ce promite hook-ul.",
        ),
        "has_one_message": _check(
            12 <= len(str(story.get("core_message") or "").strip()) <= 240,
            "Filmul are un singur mesaj, spus într-o propoziție.",
        ),
        "has_progression": _check(
            any(word in joined for word in CAUSAL_CONNECTIVES)
            and not any(word in joined for word in WEAK_CONNECTIVES),
            "Scenele se leagă cauzal («pentru că», «dar», «până»), nu prin «and then».",
        ),
        "cta_belongs_to_the_story": _check(
            bool(cta.strip())
            and not any(generic in cta.lower() for generic in GENERIC_CTAS)
            and bool(content_words(cta) & content_words(joined)),
            "Îndemnul final trebuie să vorbească despre povestea asta.",
        ),
        "cta_kind_is_stated": _check(
            str(story.get("cta_kind") or "").upper() in CTA_KINDS,
            "Îndemnul are un fel: " + ", ".join(CTA_KINDS) + ".",
        ),
        "title_keeps_its_promise": _check(
            bool(content_words(title) & content_words(joined)),
            "Titlul promite ce livrează scenariul.",
        ),
        # Not a word count — a length. A film a little over its target is a film; one that
        # no longer fits the format, or has nothing in it, is not.
        "duration_is_realistic": _check(
            target_seconds <= 0
            or (
                target_seconds * (1 - tolerance)
                <= seconds
                <= min(target_seconds * (1 + tolerance), MAX_SHORT_SECONDS)
            ),
            f"Narațiunea durează {seconds:.1f}s la {WORDS_PER_SECOND} cuvinte/secundă plus "
            f"respirația dintre scene, față de ținta de {target_seconds:.0f}s. Intervalul "
            f"acceptat este {target_seconds * (1 - tolerance):.0f}-"
            f"{min(target_seconds * (1 + tolerance), MAX_SHORT_SECONDS):.0f}s.",
        ),
    }
    return checks


def failed(checks: dict[str, dict[str, Any]]) -> list[str]:
    """The names of the checks that did not pass."""
    return [name for name, result in checks.items() if not result.get("passed")]


def revision_notes(checks: dict[str, dict[str, Any]]) -> list[str]:
    """What to tell the writer, in the words of the checks that failed."""
    return [str(result.get("reason")) for result in checks.values() if not result.get("passed")]
