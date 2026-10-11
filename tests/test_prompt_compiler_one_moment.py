"""A still prompt is one moment, and its look block is whole sentences.

Film babcf272 «The Particle That Shouldn't Exist (But Does)» (2026-10-09): scene 5's still
came back as three stacked panels (a tunnel with a glowing atom, a flat black band, an empty
tunnel) and its clip animated the triptych. The compiled still prompt described a sequence:
"... holding together as atoms, then the empty accelerator tunnel from scene 1. First the
near-black void of scenes 2 and 3, then the identical tunnel from scene 1", and its look
block opened with fragments of the bible ("two interconnected spaces: the, The setting is
entirely, None, The environment is a controlled", "Muted natural palette of A core palette
of ..."). The prompt lint, the still gate, the vision check and the clip QC all passed it.

These tests replay that scene's package and a bible shaped like that film's through the
compiler. Nothing here calls a provider.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
from app.media.prompt_agent import _clauses_of, _phrase, compile_prompts, without_scene_reference
from app.media.prompt_lint import BLOCK, dangling, lint_still_prompt
from app.media.series_look import look_block, look_phrase

#: Scene 5's package fields, as the shot plan stored them.
SCENE_5: dict[str, Any] = {
    "scene_index": 5,
    "scene_kind": "LIVE",
    "camera": "Wide establishing shot, 85mm lens",
    "subject": (
        "Glowing white spheres clustered and holding together as atoms, then the empty "
        "accelerator tunnel from scene 1"
    ),
    "action": (
        "White spheres drawing close and locking into a stable cluster, their orbits settling "
        "into a steady hold; the cluster's glow softens and dissolves into the tunnel view, "
        "which sits empty and still"
    ),
    "environment": (
        "First the near-black void of scenes 2 and 3; then the identical tunnel from scene 1 "
        "— same curved ceiling, same fluorescent pools, same vanishing point — now without "
        "the figure"
    ),
    "lighting": "The glow of the spheres against darkness",
    "motion": "Spheres drift together and settle; their glow pulses softly",
}

SCENE_3: dict[str, Any] = {
    "scene_index": 3,
    "scene_kind": "LIVE",
    "camera": "Medium shot",
    "subject": "A single faint point of light hanging in darkness",
    "environment": "The same near-black void as scene 2, unbroken and featureless",
}

#: Bibles shaped like babcf272's: world, season and weather written as long sentences, a
#: parenthesis right after an article, a literal "None", a palette that names itself.
BIBLES: list[dict[str, Any]] = [
    {
        "world": (
            "The film exists in two interconnected spaces: the (physical) particle "
            "accelerator tunnel and an abstract near-black void"
        ),
        "season": "The setting is entirely underground and outside of any season",
        "weather": "None. The environment is a controlled (indoor, climate-stable) space",
        "lighting": "In the tunnel, lighting is practical and industrial; in the void a glow",
        "palette": "A core palette of deep charcoal and slate, with cold white accents",
    },
    {
        "world": "The film exists in two interconnected spaces: the tunnel and the void",
        "season": "None",
        "weather": "None. The environment is a controlled, climate-stable laboratory space",
        "lighting": "practical and industrial",
        "palette": "A core palette of deep charcoal and slate",
    },
    {
        "world": {"tunnel": "a curved concrete tunnel", "void": "a near-black void"},
        "season": "n/a",
        "weather": "null",
        "lighting": "Not applicable",
        "palette": "A core palette of deep charcoal and slate",
    },
]

NONE_WORDS = re.compile(r"\b(?:none|null|n/a|not applicable)\b", re.IGNORECASE)
SEQUENCE_WORDS = re.compile(r"\b(?:then|first|finally|later|eventually)\b", re.IGNORECASE)
SCENE_NUMBER = re.compile(r"\bscenes?\s+\d", re.IGNORECASE)


def _fragments(text: str) -> list[str]:
    """Every clause of a text that ends in an article, a preposition, a conjunction or
    "is": the head of a broken sentence."""
    return [
        clause
        for clause in re.split(r"[.,;:]\s*", text)
        if clause.strip() and dangling(clause.strip())
    ]


# --------------------------------------------------------------------- 1. one moment


@pytest.mark.parametrize("bible", BIBLES, ids=["parenthesis", "long", "dict"])
def test_scene_5_compiles_to_a_still_of_one_moment(bible: dict[str, Any]) -> None:
    compiled = compile_prompts(SCENE_5, bible, {"model_id": "seedance2_5"})
    still = compiled["still_prompt"]
    block = compiled["look_block"]
    assert still.startswith(block)
    scene = still[len(block) :]
    # The one moment: the spheres holding together as atoms, in the void they start in.
    assert "Glowing white spheres clustered and holding together as atoms." in scene
    assert "near-black void" in scene
    # Its light is a sentence ("Light The glow of ..." was not).
    assert "Lit by the glow of the spheres against darkness." in scene
    # Nothing of the later moments: no tunnel, no dissolve, no empty view. Read on the whole
    # prompt the image model receives, look block included: a film-wide block that kept the
    # bible's "In the tunnel, lighting is practical" put the void scene in the tunnel again.
    for later in ("tunnel", "dissolves", "empty", "curved ceiling", "vanishing point"):
        assert later not in still.lower(), (later, still)
    assert not SEQUENCE_WORDS.search(still), SEQUENCE_WORDS.search(still)
    assert not SCENE_NUMBER.search(still), SCENE_NUMBER.search(still)
    assert not _fragments(still), _fragments(still)
    # No capital in the middle of a sentence ("today, The environment", "Light The glow").
    assert not re.search(r"[a-z,] [A-Z][a-z]", still), still
    assert 60 <= len(still.split()) <= 120, len(still.split())
    # The lint reads it as one moment, and nothing in it blocks.
    findings = lint_still_prompt(still, scene=5, bible=bible)
    codes = {finding.code for finding in findings}
    assert "STILL_SEQUENCE" not in codes and "SCENE_REFERENCE" not in codes, codes
    assert not [finding for finding in findings if finding.severity == BLOCK]


def test_scene_3_keeps_its_void_and_loses_the_pointer_at_scene_2() -> None:
    still = compile_prompts(SCENE_3, BIBLES[0], {"model_id": "seedance2_5"})["still_prompt"]
    assert "The near-black void, unbroken and featureless." in still
    assert "scene 2" not in still.lower() and "same" not in still.lower()


def test_a_still_field_is_read_up_to_its_first_later_moment() -> None:
    # The words before a "then" are the first moment; the clause after it is not.
    assert _clauses_of("the river is calm and then floods the valley, a bridge") == [
        "the river is calm"
    ]
    assert _clauses_of("First the void, then the tunnel, same ceiling") == ["the void"]
    assert _clauses_of("First, the void; then the tunnel") == ["the void"]
    assert _clauses_of("At first a quiet street; later a crowd fills it") == ["a quiet street"]
    assert _clauses_of("snow on the ridge, eventually melting, a hut") == ["snow on the ridge"]
    assert _clauses_of("the glow brightens, dissolving into the tunnel view") == [
        "the glow brightens"
    ]
    # Changed (review, 2026-10-09): a later-moment word that opens the field is said about
    # the scene before it ("Finally, the cluster settles" is this shot's one moment); the
    # first version dropped the whole field and the still had no subject.
    assert _clauses_of("finally the cluster settles") == ["the cluster settles"]
    assert _clauses_of("Then the tunnel, then the void") == ["the tunnel"]
    # Places and dawn are not moments: they stay.
    assert _clauses_of("a door at the end of the corridor, first light on the wall") == [
        "a door at the end of the corridor",
        "first light on the wall",
    ]


def test_the_motion_side_keeps_its_clauses_but_not_a_pointer_at_another_scene() -> None:
    # Unchanged: the motion prompt drops only the "then" clause and reads on.
    assert _clauses_of("dust drifts, then rain falls, grass sways", motion=True) == [
        "dust drifts",
        "grass sways",
    ]
    assert _clauses_of("Spheres drift as in scene 2, glow pulses", motion=True) == [
        "Spheres drift",
        "glow pulses",
    ]


def test_a_pointer_at_another_scene_is_taken_out_or_its_clause_dropped() -> None:
    assert without_scene_reference("the near-black void of scenes 2 and 3") == "the near-black void"
    assert without_scene_reference("The same void as scene 2") == "The void"
    assert without_scene_reference("the previous scene's tunnel, now empty") == (
        "the tunnel, now empty"
    )
    assert without_scene_reference("as in scene four") == ""
    assert without_scene_reference("echoing scene 1") == ""
    assert without_scene_reference("a quiet street") == "a quiet street"


def test_a_value_that_says_nothing_or_breaks_off_never_enters_a_prompt() -> None:
    for nothing in ("None", "none.", "n/a", "N/A", "null", "Not applicable", "-"):
        assert _clauses_of(nothing) == [], nothing
    # Changed (review, 2026-10-09): an aside no longer splits the clause into fragments
    # (["physical", "tunnel"] lost the tunnel's head): it is taken out, or opened when the
    # sentence needs its words ("the (physical) tunnel" -> "the physical tunnel"). The
    # label rule that was already here reads "two interconnected spaces:" as a label.
    assert _clauses_of("two interconnected spaces: the (physical) tunnel") == [
        "the physical tunnel"
    ]
    # "In", "on" and "by" after a verb of motion are adverbs: the clause is whole.
    assert _clauses_of("fog rolling in, clouds drift by, the lamps switched on") == [
        "fog rolling in",
        "clouds drift by",
        "the lamps switched on",
    ]
    assert _clauses_of("a lab located in (Geneva)") == ["a lab located in Geneva"]
    assert _clauses_of("A curved concrete tunnel lined with (blue-painted) magnets") == [
        "A curved concrete tunnel lined with blue-painted magnets"
    ]
    assert _clauses_of("a controlled (indoor, climate-stable) space") == ["a controlled space"]
    # A subject longer than its words is cut at a word, never on "the", "of" or "and".
    assert _phrase(["glowing white spheres held together in the dark"], 6) == (
        "glowing white spheres held together"
    )


# --------------------------------------------------------------------- 2. the look block


@pytest.mark.parametrize("bible", BIBLES, ids=["parenthesis", "long", "dict"])
def test_the_look_block_of_a_prose_bible_has_no_fragment(bible: dict[str, Any]) -> None:
    block = look_block(bible)
    assert 40 <= len(block.split()) <= 60, block
    assert not _fragments(block), _fragments(block)
    assert not NONE_WORDS.search(block), block
    assert "palette of A" not in block
    assert "A core palette of deep charcoal and slate" in block
    for broken in (
        "two interconnected spaces: the",
        "The setting is entirely,",
        "The setting is entirely.",
        "is a controlled.",
        "is a controlled,",
        "today, The",
    ):
        assert broken not in block, (broken, block)
    # A film without weather is not given the look file's "overcast sky".
    assert "overcast" not in block.lower()
    # Every scene of the film opens with the look: the same rendering, palette and lens. A
    # scene that names its own place or light leaves those slots to its own words
    # (2026-10-11, aa170155), so its block is the film's with those sentences unsaid.
    rendering = block.split(". ")[0] + "."
    for scene in (SCENE_3, SCENE_5):
        compiled = compile_prompts(scene, bible, {"model_id": "seedance2_5"})
        opening = compiled["look_block"]
        assert compiled["still_prompt"].startswith(opening)
        assert opening.startswith(rendering), opening
        assert "A core palette of deep charcoal and slate" in opening
        assert not _fragments(opening), _fragments(opening)
        assert not NONE_WORDS.search(opening), opening
    assert look_block(dict(bible)) == block


def test_a_bible_clause_is_said_whole_or_not_at_all() -> None:
    # Too long for its slot: nothing, so the slot falls back, never "The setting is entirely".
    assert look_phrase("The setting is entirely underground and timeless", 4) == ""
    # A later whole clause does not fit after the first: only the first.
    assert look_phrase("a curved concrete tunnel, fluorescent pools on the floor", 6) == (
        "a curved concrete tunnel"
    )
    # A sentence with its own verb is one unit, its commas notwithstanding.
    assert look_phrase("The environment is a controlled, climate-stable space", 6) == ""
    assert look_phrase("The environment is a controlled, climate-stable space", 8) == (
        "The environment is a controlled, climate-stable space"
    )
    # An aside is opened where the sentence needs its words (after "the"), taken out elsewhere.
    assert look_phrase("The film exists in two spaces: the (physical) tunnel and the void", 12) == (
        "The film exists in two spaces: the physical tunnel and the void"
    )
    assert look_phrase("a controlled (indoor, climate-stable) space", 6) == "a controlled space"
    assert look_phrase("None", None) == ""
    assert look_phrase("slate blue (#2E4A66), muted ochre", 8) == "slate blue, muted ochre"


# ------------------------------------------- 3. what the adversarial review found (2026-10-09)


def test_the_look_block_names_no_single_place_of_a_film_that_has_several() -> None:
    # babcf272's light opened with "In the tunnel, lighting is practical and industrial", and
    # a block said for every scene put the void scenes in the tunnel: the stills under
    # backend/storage/media/babcf272-.../stills/ show tunnels over flat black bands. A light
    # that the bible gives place by place is the scene's to say, not the block's, and is
    # not replaced by the look file's daylight either.
    block = look_block(BIBLES[0])
    assert "tunnel" not in block.lower() and "void" not in block.lower(), block
    assert "daylight" not in block.lower(), block
    # A world of several places names none of them in the block: every scene would show both.
    for world in (
        {"tunnel": "a curved concrete tunnel", "void": "a near-black void"},
        "tunnel: a curved concrete tunnel; void: a near-black void",
        "The film moves between two places, a tunnel and a void",
    ):
        block = look_block({"world": world})
        assert "tunnel" not in block.lower() and "void" not in block.lower(), (world, block)
    # A light said for the whole film still is the film's, an opening phrase of time too.
    assert "In the soft light of dawn, hills glow" in look_block(
        {"lighting": "In the soft light of dawn, hills glow"}
    )
    assert "Kathmandu" in look_block({"world": "In the Kathmandu valley, brick temples"})


def test_a_named_place_light_and_palette_survive_a_relative_clause() -> None:
    # The bible writer is asked for "the place by its name and what it looks like": the name
    # before the comma is whole and is said, the sentence after it when it fits.
    kathmandu = {
        "world": "Kathmandu, a valley city where brick temples sit beside new concrete",
        "lighting": "Soft grey daylight, the sun is hidden behind cloud",
        "palette": "Brick red, wet slate and faded prayer-flag colours that are softened by rain",
        "season": "late monsoon",
    }
    block = look_block(kathmandu)
    for kept in ("Kathmandu", "late monsoon", "Soft grey daylight", "Brick red"):
        assert kept in block, (kept, block)
    assert "real location" not in block and "slate blue" not in block, block
    assert look_phrase(kathmandu["world"], 8) == "Kathmandu"
    assert look_phrase(kathmandu["lighting"], 8) == "Soft grey daylight"
    # The comma of a sentence whose verb came first still binds ("is a controlled, ..."),
    # but not before a new phrase or a negation.
    assert look_phrase("The light is soft, warm and low", 8) == "The light is soft, warm and low"
    assert look_phrase("The light is soft, never harsh", 8) == "The light is soft"
    assert look_phrase("The sky is grey, the river is high", 8) == (
        "The sky is grey, the river is high"
    )


def test_a_first_moment_opener_keeps_only_the_first_moment() -> None:
    assert _clauses_of("First the near-black void; next, the identical tunnel") == [
        "the near-black void"
    ]
    assert _clauses_of("First the near-black void, next the identical tunnel") == [
        "the near-black void"
    ]
    assert _clauses_of("Initially the near-black void, the identical tunnel appearing") == [
        "the near-black void"
    ]
    assert _clauses_of("First the void, second the tunnel") == ["the void"]
    assert _clauses_of("a quiet square; next, a crowd fills it") == ["a quiet square"]
    assert _clauses_of("a quiet square; secondly, a crowd") == ["a quiet square"]
    # "Next to" is a place.
    assert _clauses_of("next to the window, a cat sleeps") == ["next to the window", "a cat sleeps"]
    # The lint sees what the compiler would have cut.
    for text, evidence in (
        ("The near-black void, next the identical tunnel.", "next"),
        ("First the near-black void, the identical tunnel.", "First"),
        ("Initially the near-black void, the identical tunnel appearing.", "Initially"),
    ):
        found = [f for f in lint_still_prompt(text, scene=5) if f.code == "STILL_SEQUENCE"]
        assert found and found[0].evidence == evidence, (text, found)


def test_a_panel_layout_is_read_as_its_first_picture() -> None:
    assert _clauses_of("Before: a dense rainforest canopy. After: a bare clearing of stumps") == [
        "a dense rainforest canopy"
    ]
    assert _clauses_of("Top half: the glacier in 1990; bottom half: the bare valley today") == [
        "the glacier in 1990"
    ]
    assert _clauses_of("Split screen of the dense forest and the cleared land") == [
        "the dense forest and the cleared land"
    ]
    assert _clauses_of("A before-and-after view of the glacier") == ["the glacier"]
    assert _clauses_of("the street before and after the flood") == ["the street before the flood"]
    assert _clauses_of("a triptych, a lone tree") == ["a lone tree"]
    # One picture of things next to each other is not a layout.
    assert _clauses_of("two boats moored side by side, solar panels on a roof") == [
        "two boats moored side by side",
        "solar panels on a roof",
    ]
    package = {
        "scene_index": 2,
        "scene_kind": "LIVE",
        "camera": "Aerial wide shot",
        "subject": "Before: a dense rainforest canopy. After: a bare clearing of stumps",
        "environment": "Split screen of the Borneo lowlands",
    }
    still = compile_prompts(package, {}, {"model_id": "seedance2_5"})["still_prompt"]
    assert "A dense rainforest canopy." in still and "The Borneo lowlands." in still, still
    assert "stumps" not in still and "split" not in still.lower(), still
    assert not [f for f in lint_still_prompt(still, scene=2) if f.code == "STILL_PANELS"]


def test_a_present_state_is_not_a_later_moment() -> None:
    for state in (
        "Rainforest replaced by palm oil plantations",
        "An old textile mill transformed into a museum",
        "Wind turbines marking the transition to renewable energy",
        "since then the city has grown",
    ):
        assert _clauses_of(state) == [state], state
    assert _clauses_of("A mother elephant followed by her calf, crossing the river") == [
        "A mother elephant followed by her calf",
        "crossing the river",
    ]
    # A change said in the present is cut at its verb, and what came before it stays.
    assert _clauses_of("the cluster's glow softens and dissolves into the tunnel view") == [
        "the cluster's glow softens"
    ]
    assert _clauses_of("an old mill transforms into a museum") == ["an old mill"]
    package = {
        "scene_index": 4,
        "scene_kind": "LIVE",
        "camera": "Aerial wide shot",
        "subject": "Rainforest replaced by palm oil plantations",
    }
    still = compile_prompts(package, {}, {"model_id": "seedance2_5"})["still_prompt"]
    assert "Rainforest replaced by palm oil plantations." in still, still


def test_a_pointer_at_another_scene_leaves_no_broken_words() -> None:
    assert without_scene_reference("Back in the scene 1 tunnel") == ""
    assert without_scene_reference("Identical to the tunnel in scene 1") == "the tunnel"
    assert without_scene_reference("A tunnel similar to scene 2's") == "A tunnel"
    assert without_scene_reference("Matching scene 1's tunnel") == "the tunnel"
    assert without_scene_reference("the scene 1 tunnel, now empty") == "the tunnel, now empty"
    # "Lit the same" points at the scene it is the same as: nothing whole is left.
    assert without_scene_reference("lit the same as scene 1") == ""
    # A scene that names itself the opening shot points at no other scene.
    own = "The opening shot shows a glacier at dawn"
    assert without_scene_reference(own) == own
    assert _clauses_of(own) == [own]
    codes = {f.code for f in lint_still_prompt(f"{own}.", scene=1)}
    assert "SCENE_REFERENCE" not in codes, codes
