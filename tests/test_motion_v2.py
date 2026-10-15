"""«Mișcare v2»: ample, cinematic motion in every prompt the video model receives.

The Owner, 2026-10-11, 23:40, on the live clips of film aa170155 and the serial's first
board f06808c9: «Modelele sunt capabile ... imaginile sunt bune, dar mișcările de ce sunt
așa slabe? Pe video pare doar un zoom, și mișcări mici. Nu este capabil de mai mult? De
cursivitate? De mișcări mai ample? ... trebuie doar să lucrăm la prompturi!» Read on the
prompts those clips were made from, the studio had asked for exactly that: «Slow push-in
toward the subject.», «Static camera, held steady.», «Background details remain stable
throughout the shot.», «barely moving». A video model does what it is told.

What these tests hold, on fakes and frozen fixtures only (no provider, no database):

- one vocabulary: every camera move has one key, one sentence with its tempo and its path,
  one lint pattern and one QC fixture, and the ten older keys still read (stored prompts,
  written plans and the Director's rewrites name them);
- the motion prompt of a factual plan and of a serial beat names one move with its path and
  its tempo, says the subject's own action as movement, keeps the world moving, and asks
  for no stillness; a clip of seven seconds or more gets a second beat of camera;
- what protects the picture stays: the face rule, the serial's faces sentence, the closing
  line, one move per clip (two beats of one move read as one), the vendor caps;
- the word band is 25-95 and every rule that reads it follows;
- the one retry asks for the move more firmly when the clip barely moved, and one step
  calmer when it moved and deformed the picture (the Director's ladder).
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from app.media import prompt_agent, qc
from app.media.prompt_agent import (
    _SHOTS_INSTRUCTIONS,
    AMPLE,
    DEFAULT_WORLD_MOTION,
    END_BEAT,
    FACES_CONSTRAINT,
    MEASURED,
    MEASURED_SENTENCE,
    MOTION_PAD,
    MOVE_SENTENCES,
    MOVE_SHORT,
    SERIAL_FACES_SENTENCE,
    SERIAL_LIFE_SENTENCE,
    SIZE_MOVES,
    TWO_BEAT_SECONDS,
    _validated_package,
    choose_camera_move,
    compile_film_prompts,
    compile_prompts,
    compose_serial_motion,
    motion_prompt_for,
    render_motion,
    serial_ending_dropped,
    serial_motion,
)
from app.media.prompt_lint import (
    BLOCK,
    CAMERA_MOVES,
    LEGACY_STILLNESS,
    MOTION_CLOSING,
    MOTION_WORDS,
    SPEED_WORDS,
    STILLNESS_WORDS,
    VEO_MOTION_CLOSING,
    LintScene,
    camera_moves,
    lint_film,
    lint_motion_prompt,
)
from app.media.qc import (
    MOVE_FIXTURE,
    calmer_motion_prompt,
    canonical_move,
    clip_deformed,
    clip_retry_decision,
    motion_check,
    qc_clip_with_retry,
    retry_motion_prompt,
    stronger_motion_prompt,
)

FACELESS_BIBLE = {
    "continuity_rules": ["No human faces appear"],
    "world": "terraced hills under moving weather",
    "lighting": "soft overcast daylight",
}

#: A factual plan with people and a world, as the Video Editor's model writes one: the
#: action is a chain of moments (a still shows the first; the clip is the chain).
PLAN = {
    "subject": "A farmer at the edge of a stone terrace above the valley",
    "action": (
        "She stands, walks to the low wall and turns toward the valley, then hands over the "
        "ledger to a boy beside her"
    ),
    "environment": "Terraced rice fields under moving cloud",
    "camera": "Wide shot, 24mm lens",
    "lighting": "soft overcast daylight from the left",
    "composition": "the wall leading the eye up the frame",
    "motion": "cloud shadows sweep across the terraces; prayer flags snap in the wind",
    "seconds": 8.0,
    "scene_kind": "LIVE",
    "shot_type": "WIDE",
}

#: A serial beat as the first episode's scene 4 was planned (f06808c9): a chain of moments.
BEAT = {
    "action": (
        "Nadia taps the brass pen once against the green ledger, pauses before the number, "
        "then lays the pen flat; Sarah leans in a fraction as she asks her question"
    ),
    "emotion": "Nadia composed, Sarah curious",
    "camera_move": "tracking left",
    "seconds": 8.0,
    "shot_size": "two_shot",
}


def _blocks(findings) -> list[str]:
    return [f.code for f in findings if f.severity == BLOCK]


def _codes(findings) -> set[str]:
    return {f.code for f in findings}


# ----------------------------------------------------------------- 1. the vocabulary


def test_every_camera_move_has_one_sentence_one_pattern_and_one_fixture():
    assert set(MOVE_SENTENCES) == set(CAMERA_MOVES) == set(MOVE_FIXTURE)
    for key, sentence in MOVE_SENTENCES.items():
        # The sentence names exactly its own move, spells its key, says its tempo, and asks
        # for no stillness; the lint and clip QC read the same one move from it.
        assert [move for move, _ in camera_moves(sentence)] == [key], (key, sentence)
        assert key in sentence.lower(), (key, sentence)
        assert SPEED_WORDS.search(sentence), (key, sentence)
        assert not STILLNESS_WORDS.search(sentence), (key, sentence)
        assert not re.search(r"\bthen\b", sentence, re.IGNORECASE), sentence
        assert canonical_move(key) == key
        assert canonical_move(sentence) == key, (key, sentence)
        assert MOVE_FIXTURE[key] in ("push_in", "pan", None), key
    # Only the static camera and the rack focus (which moves the blur, not the frame) have
    # no floor; every move that changes the scale or slides the frame is measured.
    assert {key for key, fixture in MOVE_FIXTURE.items() if fixture is None} == {
        "static",
        "rack focus",
    }
    for key in ("dolly in", "dolly out", "slow push-in", "slow pull-back"):
        assert MOVE_FIXTURE[key] == "push_in"
    for key in ("tracking left", "tracking right", "crane up", "crane down", "handheld drift"):
        assert MOVE_FIXTURE[key] == "pan"
    # Every move with a path says where it goes: no sentence but the static camera's lacks one.
    for key, sentence in MOVE_SENTENCES.items():
        if key != "static":
            assert re.search(r"\b(?:from|to|toward|alongside|over|around)\b", sentence), key


def test_the_older_spellings_still_read_as_their_moves():
    # The prompts stored before 2026-10-11, word for word.
    assert canonical_move("Slow push-in toward the subject.") == "slow push-in"
    assert canonical_move("Slow pull-back that widens the view.") == "slow pull-back"
    assert canonical_move("Gentle pedestal up.") == "pedestal up"
    assert canonical_move("Slow orbit around the subject.") == "slow orbit"
    assert canonical_move("Static camera, held steady.") == "static"
    # The cinema's spellings read as their own keys now, each on the same fixture family.
    assert canonical_move("a slow dolly in on the medal") == "dolly in"
    assert canonical_move("the camera dollies out") == "dolly out"
    assert canonical_move("crane up over the hall") == "crane up"
    assert canonical_move("a handheld medium shot") == "handheld drift"
    assert canonical_move("tracking shot left along the bench") == "tracking left"
    assert canonical_move("rack focus to the window") == "rack focus"
    # Two moves name none, as before.
    assert canonical_move("a dolly in and a tracking left") is None
    assert [m for m, _ in camera_moves("a slow pan left, then a dolly out")] == [
        "slow pan left",
        "dolly out",
    ]


def test_the_default_sentences_ask_for_life_not_stillness():
    for sentence in (DEFAULT_WORLD_MOTION, MOTION_PAD, END_BEAT, MEASURED_SENTENCE):
        assert not STILLNESS_WORDS.search(sentence), sentence
        assert not camera_moves(sentence), sentence  # a second move would be a second move
        assert not re.search(r"\bthen\b", sentence, re.IGNORECASE), sentence
    for legacy in LEGACY_STILLNESS:
        assert STILLNESS_WORDS.search(legacy), legacy
        assert legacy not in (DEFAULT_WORLD_MOTION, MOTION_PAD)
    # Setting-neutral: an airless scene gets no weather from the default world.
    for word in ("haze", "wind", "cloud", "water", "rain"):
        assert word not in DEFAULT_WORLD_MOTION.lower()


# ----------------------------------------------------------- 2. the factual compile


def test_a_factual_plan_renders_one_cinematic_move_with_real_subject_motion():
    compiled = compile_prompts(PLAN, FACELESS_BIBLE, {"model_id": "LTX-2.5"})
    prompt = compiled["motion_prompt"]
    move = compiled["camera_move"]
    assert move in CAMERA_MOVES and move not in ("static", "slow orbit", "rack focus")
    # One move, said with its path and its tempo, the way the table says it.
    assert [m for m, _ in camera_moves(prompt)] == [move], prompt
    assert prompt.startswith(MOVE_SENTENCES[move]), prompt
    assert SPEED_WORDS.search(MOVE_SENTENCES[move])
    # The subject's own action, as verbs, the chain kept without its "then" (each clause of
    # the plan's action is said as a sentence of its own, so it opens with a capital).
    assert "walks to the low wall" in prompt.lower(), prompt
    assert "hands over the ledger" in prompt.lower(), prompt
    assert not re.search(r"\bthen\b", prompt, re.IGNORECASE), prompt
    # The world in motion, from the plan's own words.
    assert "cloud shadows sweep across the terraces" in prompt.lower(), prompt
    # Two beats of camera on an eight-second clip, and the second beat is no second move.
    assert END_BEAT in prompt, prompt
    # Nothing asks for stillness; what protects the picture stays.
    assert not STILLNESS_WORDS.search(prompt), prompt
    assert FACES_CONSTRAINT in prompt
    assert prompt.endswith(MOTION_CLOSING)
    low, high = MOTION_WORDS
    assert low <= len(prompt.split()) <= high, len(prompt.split())
    findings = lint_motion_prompt(
        prompt, scene=1, still_prompt=compiled["still_prompt"], model_id="LTX-2.5"
    )
    assert not _blocks(findings), findings
    assert not _codes(findings) & {
        "MOTION_STILLNESS",
        "MOTION_SPEED",
        "MOTION_ENVIRONMENT",
        "MOTION_LENGTH",
        "CAMERA_COUNT",
    }, findings
    # The intent carries what the renderer needs, so another model's dialect says the same.
    intent = compiled["motion_intent"]
    assert intent["seconds"] == 8.0 and intent["amplitude"] == AMPLE
    assert any("walks to the low wall" in clause.lower() for clause in intent["action_clauses"])
    assert motion_prompt_for(compiled, "LTX-2.5")[0] == prompt


def test_a_short_clip_has_one_beat_of_camera():
    short = compile_prompts({**PLAN, "seconds": 5.0}, FACELESS_BIBLE)
    assert END_BEAT not in short["motion_prompt"]
    exact = compile_prompts({**PLAN, "seconds": TWO_BEAT_SECONDS}, FACELESS_BIBLE)
    assert END_BEAT in exact["motion_prompt"]
    # A static camera asked by the plan holds; it does not "ease to a hold" twice.
    held = compile_prompts({**PLAN, "camera_move": "static"}, FACELESS_BIBLE)
    assert held["camera_move"] == "static" and END_BEAT not in held["motion_prompt"]


def test_two_beats_of_one_move_read_as_one_move_across_the_film():
    # Four moves on four shot sizes: the film lint reads both languages of the camera.
    plans = [
        {**PLAN, "camera_move": move, "camera": camera, "seconds": 9.0}
        for move, camera in (
            ("dolly in", "Wide shot, 24mm lens"),
            ("tracking right", "Medium shot, 50mm lens"),
            ("crane up", "Detail shot of the ledger, 85mm lens"),
            ("handheld drift", "Aerial wide shot"),
        )
    ]
    compiled = compile_film_prompts(plans, FACELESS_BIBLE, contract={"model_id": "LTX-2.5"})
    scenes = []
    for index, item in enumerate(compiled, start=1):
        assert END_BEAT in item["motion_prompt"], item["motion_prompt"]
        assert [m for m, _ in camera_moves(item["motion_prompt"])] == [item["camera_move"]]
        scenes.append(
            LintScene(
                scene=index,
                kind="LIVE",
                still_prompt=item["still_prompt"],
                motion_prompt=item["motion_prompt"],
                model_id="LTX-2.5",
            )
        )
    findings = lint_film(scenes, bible=FACELESS_BIBLE)
    assert not _codes(findings) & {"SAME_CAMERA_EVERY_SCENE", "SAME_CAMERA_RUN", "CAMERA_COUNT"}
    # The same move on every scene is still what the film lint refuses: it reads one move
    # per prompt, and the one move is the same everywhere.
    same = [
        LintScene(scene=s.scene, kind="LIVE", still_prompt=s.still_prompt, motion_prompt=m)
        for s, m in zip(
            scenes,
            [compile_prompts({**PLAN, "camera_move": "dolly in"}, FACELESS_BIBLE)["motion_prompt"]]
            * 4,
            strict=True,
        )
    ]
    assert "SAME_CAMERA_EVERY_SCENE" in _codes(lint_film(same, bible=FACELESS_BIBLE))


def test_the_compiler_varies_the_moves_and_never_orbits_people_kept_faceless():
    for size, moves in SIZE_MOVES.items():
        assert len(moves) >= 2, size
        for move in moves:
            assert move in CAMERA_MOVES and move not in ("static", "slow orbit", "rack focus")
    # Never the move of the scene before, never one to avoid; a plan's own choice always wins.
    assert choose_camera_move({}, "medium", ["dolly in"]) == "tracking left"
    assert choose_camera_move({}, "medium", ["dolly in"], avoid=("tracking left",)) == "crane down"
    assert choose_camera_move({"camera_move": "slow orbit"}, "medium", [], avoid=("slow orbit",))
    assert choose_camera_move({"camera": "a handheld medium shot, 35mm"}, "medium") == (
        "handheld drift"
    )
    # A film of four sizes gets four different moves.
    plans = [
        {**PLAN, "camera": camera, "shot_type": shot_type}
        for camera, shot_type in (
            ("Aerial wide shot", "WIDE"),
            ("Wide shot, 24mm", "WIDE"),
            ("Medium shot, 50mm", "MEDIUM"),
            ("Detail shot of hands, 85mm", "DETAIL"),
        )
    ]
    moves = [item["camera_move"] for item in compile_film_prompts(plans, FACELESS_BIBLE)]
    assert len(set(moves)) == 4, moves
    assert "slow orbit" not in moves


def test_a_template_package_moves_too():
    scene = {
        "scene_index": 2,
        "seconds": 6.0,
        "story_purpose": "SETUP",
        "narration": "The river rose overnight.",
        "writer_visual": "A river at dawn",
        "shot_type": "WIDE",
        "characters": [],
    }
    package, _notes = _validated_package(None, scene, FACELESS_BIBLE, "", "")
    assert "slow, natural movement" not in package["motion"]
    compiled = compile_prompts({**package, "scene_kind": "LIVE"}, FACELESS_BIBLE)
    prompt = compiled["motion_prompt"]
    assert "carries on with its action" in prompt, prompt
    assert "shadows drift" in prompt.lower(), prompt
    assert not STILLNESS_WORDS.search(prompt), prompt
    assert len(camera_moves(prompt)) == 1


def test_a_stored_intent_from_before_is_said_in_the_new_words():
    # The intent of film aa170155's scene, as stored on 2026-10-11 before this change.
    stored = {
        "camera_move": "slow push-in",
        "world": LEGACY_STILLNESS[0],
        "subject": "A slow drift of dust motes in the lamp beam, barely moving.",
        "subject_clauses": ["A slow drift of dust motes in the lamp beam, barely moving."],
        "constraints": [],
        "faces_banned": True,
        "people": False,
    }
    prompt, negative = render_motion(stored, None)
    assert negative is None
    assert prompt.startswith(MOVE_SENTENCES["slow push-in"]), prompt
    assert LEGACY_STILLNESS[0] not in prompt and DEFAULT_WORLD_MOTION in prompt
    # The plan's own words stay the plan's: the Director's, not the compiler's, to change.
    assert "dust motes" in prompt
    assert END_BEAT not in prompt  # no length stored: one beat
    assert [m for m, _ in camera_moves(prompt)] == ["slow push-in"]
    assert prompt.endswith(MOTION_CLOSING)


def test_a_measured_amplitude_is_one_step_down():
    compiled = compile_prompts({**PLAN, "motion_amplitude": MEASURED, "seconds": 9.0}, {})
    prompt = compiled["motion_prompt"]
    assert compiled["motion_intent"]["amplitude"] == MEASURED
    assert MEASURED_SENTENCE in prompt and END_BEAT not in prompt, prompt
    assert len(camera_moves(prompt)) == 1 and not STILLNESS_WORDS.search(prompt)
    # An amplitude nobody defined is the rule's.
    loose = compile_prompts({**PLAN, "motion_amplitude": "timid"}, {})
    assert loose["motion_intent"]["amplitude"] == AMPLE and END_BEAT in loose["motion_prompt"]


# -------------------------------------------------------------- 3. the serial beat


def test_the_serial_motion_locks_its_cast_and_their_features():
    """2026-10-15, a4ecf40a: scene 6's clip let Marcus's face slip between frames and scene
    7's single on Sarah grew a second man behind her — the Director's cause both times: the
    words never fixed the face as its own clause, nor one person and nobody entering. The
    composer says both, with the shot's names, before the life of the room."""
    from app.media.prompt_agent import SERIAL_CAST_TAIL, serial_cast_sentence

    single = {**BEAT, "shot_size": "medium_close_up", "in_frame": [{"name": "Sarah Director"}]}
    prompt = compose_serial_motion(single, {})
    assert (
        "Only Sarah in the frame from first to last, the same face and features throughout; "
        in prompt
    ), prompt
    assert SERIAL_CAST_TAIL in prompt
    assert prompt.index(SERIAL_CAST_TAIL) < prompt.index(SERIAL_LIFE_SENTENCE)
    two = {**BEAT, "characters": [{"name": "Nadia"}, {"name": "Sarah"}]}
    assert serial_cast_sentence(two).startswith("Only Nadia and Sarah in the frame")
    assert serial_cast_sentence(BEAT) == ""  # a plan that names nobody says nothing


def test_the_serial_motion_moves_its_people_and_keeps_its_faces_and_closing():
    prompt = compose_serial_motion(BEAT, {})
    assert prompt.startswith(MOVE_SENTENCES["tracking left"]), prompt
    assert [m for m, _ in camera_moves(prompt)] == ["tracking left"]
    # The whole chain of the beat is the clip's (a still is one moment; 48bbcd1).
    assert "then lays the pen flat" in prompt
    assert "Sarah leans in a fraction" in prompt
    assert SERIAL_FACES_SENTENCE in prompt
    assert SERIAL_LIFE_SENTENCE in prompt
    assert prompt.endswith(MOTION_CLOSING)
    assert not STILLNESS_WORDS.search(prompt), prompt
    low, high = MOTION_WORDS
    assert low <= len(prompt.split()) <= high
    findings = lint_motion_prompt(prompt, scene=4, model_id="LTX-2.5")
    assert not _blocks(findings), findings
    assert not _codes(findings) & {"MOTION_SPEED", "MOTION_ENVIRONMENT", "MOTION_STILLNESS"}
    # A short beat gets the second beat of camera when it fits; a five-second beat does not.
    brief = {**BEAT, "action": "Kael swivels his chair toward Sarah and taps the monitor"}
    assert END_BEAT in compose_serial_motion(brief, {})
    assert END_BEAT not in compose_serial_motion({**brief, "seconds": 5.0}, {})
    # A beat with no move of its own holds the camera, as before, and moves its people.
    held = compose_serial_motion({**brief, "camera_move": ""}, {})
    assert held.startswith(MOVE_SENTENCES["static"]) and SERIAL_LIFE_SENTENCE in held


def test_the_serial_motion_carries_the_ending_frame_and_the_rewrites_feeling():
    """2026-10-12, f06808c9 scene 3: the film's QC found the ending frame in profile, and no
    rewrite could reach the clip's ending — the composer never read ``ending_frame``. It is
    said right after the action, before the faces and the room, so it survives the word
    budget; a name keeps its capital, anything else is lower-cased; an ending that names a
    camera move of its own is left out (the clip has one); the Director's motion rewrite gives
    its feeling as ``motion_emotion``, so the still's ``emotion`` stays the still's."""
    ending = "Nadia's hazel eyes steady over the laid-flat pen, Sarah waiting at frame edge."
    beat = {**BEAT, "ending_frame": ending, "in_frame": [{"name": "Nadia Accountant"}]}
    prompt = compose_serial_motion(beat, {})
    assert (
        "The shot ends on Nadia's hazel eyes steady over the laid-flat pen, Sarah waiting at "
        "frame edge." in prompt
    ), prompt
    assert prompt.index("The shot ends on") < prompt.index(SERIAL_FACES_SENTENCE)
    assert prompt.index("then lays the pen flat") < prompt.index("The shot ends on")
    assert [m for m, _ in camera_moves(prompt)] == ["tracking left"]
    low, high = MOTION_WORDS
    assert low <= len(prompt.split()) <= high
    assert not _blocks(lint_motion_prompt(prompt, scene=4, model_id="LTX-2.5"))
    # A chain word goes, the first letter follows the name rule, a preposition is kept.
    plain = compose_serial_motion(
        {**BEAT, "ending_frame": "Both faces turned to the viewer, then the pen laid flat."}, {}
    )
    assert "The shot ends on both faces turned to the viewer, the pen laid flat." in plain
    with_preposition = compose_serial_motion(
        {**BEAT, "ending_frame": "with her eyes on the pen"}, {}
    )
    assert "The shot ends with her eyes on the pen." in with_preposition
    # 2026-10-12, f06808c9 scene 4: the rewrite wrote the lead-in itself and the clip was asked
    # «The shot ends on the shot ends on …». The writer's lead-in goes, once or twice written.
    for lead in (
        "The shot ends on the same medium close-up single on Nadia, eyes on the pen.",
        "The shot ends on: the shot ends on the same medium close-up single on Nadia, eyes on "
        "the pen",
        "Ending on the same medium close-up single on Nadia, eyes on the pen",
    ):
        led = compose_serial_motion({**BEAT, "ending_frame": lead}, {})
        assert led.count("The shot ends") == 1, led
        assert (
            "The shot ends on the same medium close-up single on Nadia, eyes on the pen." in led
        ), led
    kept_with = compose_serial_motion(
        {**BEAT, "ending_frame": "The clip ends with her eyes on the pen"}, {}
    )
    assert kept_with.count("The shot ends") == 1 and "clip ends" not in kept_with
    assert "The shot ends on her eyes on the pen." in kept_with
    # An ending that names a camera move of its own is left out: the clip has exactly one.
    moved = compose_serial_motion({**BEAT, "ending_frame": "a slow tilt down to the ledger"}, {})
    assert "The shot ends" not in moved
    assert [m for m, _ in camera_moves(moved)] == ["tracking left"]
    # No ending frame: the prompt is what it was.
    assert "The shot ends" not in compose_serial_motion(BEAT, {})
    # The motion rewrite's feeling, read by the motion alone.
    felt = compose_serial_motion({**BEAT, "motion_emotion": "Nadia calm, Sarah attentive"}, {})
    assert "Nadia calm, Sarah attentive." in felt and "Nadia composed, Sarah curious." not in felt


#: Scene 3 of f06808c9 as its rewrites planned it (2026-10-12), its action at 45 words.
LONG_ACTION = (
    "Marcus opens both hands as if starting a pitch, the gesture stalls halfway and dies, he "
    "restarts his sentence with a small head shake and glances at the window; Sarah holds "
    "still, then lets one dry corner of her mouth move as she answers him."
)
LONG_ENDING = (
    "Marcus's hands fallen to his sides, Sarah's dry half-smile just forming, both of them "
    "facing the viewer across the desk"
)


def test_the_ending_survives_a_long_action_whose_later_moments_give_way():
    """2026-10-12, f06808c9 scene 3: the rewrite's ending did not fit 95 words beside a
    45-word action; the composer kept the action whole and dropped the ending, two rewrites
    composed to the same prompt, and her review found «finalul cerut … a fost șters». The
    ending is where the clip must arrive: the action's later moments give way first — the
    person with the most moments loses their last one — never anyone's first moment."""
    assert len(LONG_ACTION.split()) == 45
    beat = {
        "action": LONG_ACTION,
        "ending_frame": LONG_ENDING,
        "camera_move": "dolly in",
        "seconds": 6.0,
        "shot_size": "two_shot",
        "in_frame": [{"name": "Marcus Writer"}, {"name": "Sarah Director"}],
    }
    whole = " ".join(
        [
            MOVE_SENTENCES["dolly in"],
            LONG_ACTION,
            f"The shot ends on {LONG_ENDING}.",
            MOTION_CLOSING,
        ]
    )
    assert len(whole.split()) > MOTION_WORDS[1], "the whole action and the ending do not fit"

    prompt = compose_serial_motion(beat, {})

    assert f"The shot ends on {LONG_ENDING}." in prompt, prompt
    assert prompt.startswith(MOVE_SENTENCES["dolly in"]) and prompt.endswith(MOTION_CLOSING)
    assert "Marcus opens both hands as if starting a pitch, the gesture stalls halfway" in prompt
    assert "Sarah holds still, then lets one dry corner of her mouth move" in prompt
    assert "restarts his sentence" not in prompt, "his last moment gave way first"
    assert prompt.index("Sarah holds still") < prompt.index("The shot ends on")
    assert len(prompt.split()) <= MOTION_WORDS[1]
    assert [m for m, _ in camera_moves(prompt)] == ["dolly in"]
    assert not _blocks(lint_motion_prompt(prompt, scene=3, model_id="LTX-2.5"))
    # Two rewrites of the ending compose to two prompts (the same prompt twice was the bug).
    other = compose_serial_motion(
        {**beat, "ending_frame": "both of them facing the viewer, Marcus slumped in his chair"}, {}
    )
    assert other != prompt and "Marcus slumped in his chair." in other
    # An action that fits beside its ending is said whole, as before.
    short = compose_serial_motion({**beat, "action": BEAT["action"]}, {})
    assert "then lays the pen flat" in short and "The shot ends on" in short


#: One person's single clause of 54 words: no comma opens a later moment in it.
ONE_CLAUSE = (
    "Marcus slowly opens both hands above the cluttered desk as if he were about to begin a "
    "long and careful pitch about the quarterly numbers and the missing ledger pages that nobody "
    "in the writers room has managed to find since the studio moved into the new office "
    "building across the river last spring"
)
#: Three people's first moments, nothing later.
THREE_PEOPLE = (
    "Marcus opens both hands as if starting a pitch about the quarterly numbers and the missing "
    "ledger; Sarah leans across the desk and studies the open ledger with a slow doubtful frown; "
    "Nadia lifts her pen from the page and turns toward the warm window light"
)
SHORT_ENDING = (
    "Marcus with both hands open above the desk and Sarah facing the viewer with a dry "
    "half-smile just forming"
)
PEOPLE = [{"name": "Marcus Writer"}, {"name": "Sarah Director"}, {"name": "Nadia Accountant"}]


def test_every_move_said_short_names_its_one_move_and_its_tempo():
    assert set(MOVE_SHORT) == set(MOVE_SENTENCES)
    for move, sentence in MOVE_SHORT.items():
        assert [m for m, _ in camera_moves(sentence)] == [move], sentence
        assert SPEED_WORDS.search(sentence), sentence
        assert len(sentence.split()) < len(MOVE_SENTENCES[move].split()), move


def test_a_single_long_clause_keeps_the_ending_with_the_move_said_short():
    """Review of 68fa0b4, 2026-10-12: one person's single clause of 54 words did not fit beside
    the ending even as its first moment, and the ending was dropped. The move is said short
    first (the same move, its tempo, no path), and the ending stays."""
    assert len(ONE_CLAUSE.split()) == 54
    beat = {
        "action": ONE_CLAUSE,
        "ending_frame": SHORT_ENDING,
        "camera_move": "dolly in",
        "in_frame": PEOPLE[:2],
    }
    prompt, dropped = serial_motion(beat, {})
    assert dropped is False and serial_ending_dropped(beat, {}) is False
    assert prompt.startswith(MOVE_SHORT["dolly in"]), prompt
    assert f"The shot ends on {SHORT_ENDING}." in prompt
    assert ONE_CLAUSE in prompt, "the one moment is said whole, never cut"
    assert len(prompt.split()) <= MOTION_WORDS[1] and prompt.endswith(MOTION_CLOSING)
    assert [m for m, _ in camera_moves(prompt)] == ["dolly in"]
    assert compose_serial_motion(beat, {}) == prompt


def test_three_peoples_moments_give_way_word_by_word_before_the_ending_does():
    """Review of 68fa0b4: three people's first moments did not fit beside the ending. The
    later people's clauses are cut word by word (the last person first), before the ending or
    the first person's moment would be."""
    beat = {
        "action": THREE_PEOPLE,
        "ending_frame": SHORT_ENDING,
        "camera_move": "dolly in",
        "in_frame": PEOPLE,
    }
    prompt, dropped = serial_motion(beat, {})
    assert dropped is False
    assert f"The shot ends on {SHORT_ENDING}." in prompt, prompt
    assert "Marcus opens both hands as if starting a pitch about the quarterly numbers" in prompt
    assert "Sarah leans across the desk and studies the open ledger" in prompt
    assert "turns toward the warm window light" not in prompt, "the last person gave way first"
    assert len(prompt.split()) <= MOTION_WORDS[1]
    assert not _blocks(lint_motion_prompt(prompt, scene=3, model_id="LTX-2.5"))


def test_an_ending_that_fits_beside_nothing_is_left_out_and_said_so():
    """When not even the first person's first moment fits beside the ending with the move
    said short, the action is kept whole, as before, the ending is left out — and the composer
    says so (``ending_dropped``), so the rewrite asks the editor to shorten the action before
    any clip is bought on it."""
    ending = " ".join(["the desk lamp glowing over a stack of folders"] * 9)
    beat = {"action": LONG_ACTION, "ending_frame": ending, "camera_move": "dolly in"}
    prompt, dropped = serial_motion(beat, {})
    assert dropped is True and serial_ending_dropped(beat, {}) is True
    assert "The shot ends" not in prompt
    assert "he restarts his sentence with a small head shake" in prompt
    assert prompt.startswith(MOVE_SENTENCES["dolly in"])
    assert compose_serial_motion(beat, {}) == prompt
    # A beat with no ending drops nothing.
    assert serial_motion({**beat, "ending_frame": ""}, {})[1] is False


# ------------------------------------------------------- 4. the Video Editor's brief


def test_the_video_editor_is_asked_for_ample_specific_movement():
    listed = re.search(r"camera_move from this list: ([^.]+)\.", _SHOTS_INSTRUCTIONS)
    assert listed
    offered = [item.strip() for item in listed.group(1).split(",")]
    assert set(offered) <= set(CAMERA_MOVES), offered
    for move in ("dolly in", "tracking left", "crane up", "handheld drift", "static"):
        assert move in offered
    for words in (
        "path with its speed",
        "where it starts and where it ends",
        "what the subject does across the clip's seconds",
        "what the world does",
        "one primary visual idea",
        "nothing happens that the story does not say",
        "second_framing",
    ):
        assert words in _SHOTS_INSTRUCTIONS, words
    assert "movement only when the story needs it" not in _SHOTS_INSTRUCTIONS
    assert "no explosions" in _SHOTS_INSTRUCTIONS


# ------------------------------------------------------------- 5. the lint's band


def test_the_word_band_is_wider_and_every_rule_that_reads_it_follows():
    assert MOTION_WORDS == (25, 900)
    assert (prompt_agent.MOTION_MIN_WORDS, prompt_agent.MOTION_MAX_WORDS) == MOTION_WORDS
    base = "Steady dolly in from a wide view to the subject while cloud drifts."
    fixed = len(base.split()) + len(MOTION_CLOSING.split())

    def prompt_of(total: int) -> str:
        filler = " ".join(["drifting"] * (total - fixed))
        return f"{base} {filler}. {MOTION_CLOSING}" if filler else f"{base} {MOTION_CLOSING}"

    low, high = MOTION_WORDS
    for total in (low - 1, low, high, high + 1):
        assert len(prompt_of(total).split()) == total
    # The floor and the ceiling are the band's own, read where the rule is applied.
    assert "MOTION_LENGTH" in _codes(lint_motion_prompt(prompt_of(low - 1), scene=1))
    assert "MOTION_LENGTH" not in _codes(lint_motion_prompt(prompt_of(low), scene=1))
    assert "MOTION_LENGTH" not in _codes(lint_motion_prompt(prompt_of(high), scene=1))
    assert "MOTION_LENGTH" in _codes(lint_motion_prompt(prompt_of(high + 1), scene=1))
    # The compiler pads a prompt under the floor with movement, never with stillness.
    assert low <= len(compile_prompts({"subject": "A bell"}, {})["motion_prompt"].split()) <= high


def test_stillness_in_a_motion_prompt_is_a_warning_with_the_words_as_evidence():
    live = (
        "Slow push-in toward the subject. A slow drift of dust motes in the lamp beam, barely "
        "moving. " + MOTION_CLOSING
    )
    findings = lint_motion_prompt(live, scene=4, model_id="LTX-2.5")
    (still,) = [f for f in findings if f.code == "MOTION_STILLNESS"]
    assert still.severity == "WARN" and still.evidence == "barely moving"
    assert "„barely moving”" in still.message_ro and "nemișcare" in still.message_ro
    # The compiled prompts of today carry none.
    compiled = compile_prompts(PLAN, FACELESS_BIBLE)
    assert "MOTION_STILLNESS" not in _codes(
        lint_motion_prompt(compiled["motion_prompt"], scene=1, model_id="LTX-2.5")
    )


# ----------------------------------------------------- 6. clip QC and the one retry


def test_a_move_without_a_fixture_passes_by_its_own_name_and_an_unknown_one_is_not_judged():
    reading = SimpleNamespace(mean=3.0, median=2.8, values=[0.0, 3.0, 3.0], times=[0, 0.04, 0.08])
    focus = motion_check(reading, "rack focus", floors={})
    assert focus.status == "PASSED" and not focus.blocking
    assert "rack focus" in focus.detail_ro and "static" not in focus.detail_ro
    held = motion_check(reading, "static", floors={})
    assert held.status == "PASSED" and "cadru static" in held.detail_ro
    unknown = motion_check(reading, "whip around the tower", floors={})
    assert unknown.status == "NOT_RUN" and unknown.blocking
    # A measured move without its calibration is "not measured", never a pass.
    tracked = motion_check(reading, "tracking left", floors={})
    assert tracked.status == "NOT_RUN" and "tracking left" in tracked.detail_ro


def _report(checks, measured=None, passed=False):
    return qc.ClipReport(
        scene=3,
        path="clip.mp4",
        checks=tuple(checks),
        passed=passed,
        blocks_ro=tuple(f"Scena 3: {c.detail_ro}" for c in checks if c.blocking),
        warnings_ro=(),
        unmeasured=(),
        measured=measured or {},
    )


def _check(code, status, blocking=True):
    return qc.ClipCheck(code, status, blocking, None, f"{code} {status.lower()}")


BARELY_MOVED = _report([_check("motion", "FAILED"), _check("faces", "PASSED", False)])
FACE_TURNED = _report([_check("motion", "PASSED", False), _check("faces", "FAILED")])
WARPED = _report(
    [_check("motion", "PASSED", False), _check("picture", "FAILED")],
    measured={"picture": {"verdict": {"technical_ok": False, "same_shot": True}}},
)
WRONG_WORDS = _report(
    [_check("motion", "PASSED", False), _check("picture", "FAILED")],
    measured={"picture": {"verdict": {"readable_text": True, "technical_ok": True}}},
)
STORED = (
    "Slow push-in toward the subject. "
    + LEGACY_STILLNESS[0]
    + " Dust motes drift in the lamp beam. "
    + MOTION_CLOSING
)


def test_the_retry_is_firmer_when_the_clip_barely_moved_and_calmer_when_it_deformed():
    assert not clip_deformed(BARELY_MOVED)
    assert clip_deformed(FACE_TURNED) and clip_deformed(WARPED)
    assert not clip_deformed(WRONG_WORDS)  # readable text is not a deformation
    firmer = retry_motion_prompt(STORED, "slow push-in", BARELY_MOVED, model_id="LTX-2.5")
    assert firmer == stronger_motion_prompt(STORED, "slow push-in", model_id="LTX-2.5")
    assert "clearly visible" in firmer and "push-in" in firmer
    assert LEGACY_STILLNESS[0] not in firmer  # the stillness that asked for the fault
    assert "Dust motes drift in the lamp beam." in firmer
    assert firmer.endswith(MOTION_CLOSING) and len(camera_moves(firmer)) == 1
    calmer = retry_motion_prompt(STORED, "slow push-in", FACE_TURNED, model_id="LTX-2.5")
    assert calmer == calmer_motion_prompt(STORED, "slow push-in", model_id="LTX-2.5")
    assert "smooth and moderate" in calmer and "keeps its form" in calmer
    assert "clearly visible" not in calmer and LEGACY_STILLNESS[0] not in calmer
    assert calmer.endswith(MOTION_CLOSING) and len(camera_moves(calmer)) == 1
    # The new moves are named in their own words, in the model's dialect.
    for move in ("dolly in", "tracking left", "crane up", "handheld drift", "rack focus"):
        prompt = MOVE_SENTENCES[move] + " Cloud drifts. " + VEO_MOTION_CLOSING
        veo = stronger_motion_prompt(prompt, move, model_id="veo3.1_fast")
        assert veo.endswith(VEO_MOTION_CLOSING) and move in veo
        assert [m for m, _ in camera_moves(veo)] == [move], veo
        assert " no " not in f" {veo.lower()} " and "not " not in veo.lower()
        calm = calmer_motion_prompt(prompt, move, model_id="veo3.1_fast")
        assert [m for m, _ in camera_moves(calm)] == [move], calm
    # The reason the Owner reads says which way the retry went.
    firm = clip_retry_decision(
        BARELY_MOVED, seed=1, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    calm_decision = clip_retry_decision(
        FACE_TURNED, seed=1, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert firm.action == calm_decision.action == "RETRY"
    assert "mai ferm" in firm.reason_ro and "mai lin" in calm_decision.reason_ro


def test_the_one_retry_buys_the_calmer_prompt_after_a_deformation(tmp_path):
    bought: list[dict] = []
    reports = iter([FACE_TURNED, _report([_check("motion", "PASSED", False)], passed=True)])

    def buy(seed, prompt):
        bought.append({"seed": seed, "prompt": prompt})
        out = tmp_path / f"retry_{seed}.mp4"
        out.write_bytes(b"clip")
        return out

    outcome = qc_clip_with_retry(
        tmp_path / "first.mp4",
        check=lambda path: next(reports),
        buy=buy,
        seed=7,
        motion_prompt=MOVE_SENTENCES["dolly in"] + " Cloud drifts. " + MOTION_CLOSING,
        camera_move="dolly in",
        model_id="LTX-2.5",
        price_credits=10,
        committed_credits=0,
        cap_credits=100,
    )
    assert outcome.status == "PASSED_ON_RETRY" and outcome.seeds == (7, 8)
    (purchase,) = bought
    assert (
        "smooth and moderate" in purchase["prompt"] and "clearly visible" not in purchase["prompt"]
    )
    assert outcome.prompt == purchase["prompt"]
