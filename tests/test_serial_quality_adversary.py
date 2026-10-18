"""The adversary's pass over S7 (voices), S8 (look), S10 (identity) and the brief.

Each test is one way to break the serial the steps' own tests did not try: a locked speaker
whose voice is gone, a line nobody speaks, a model that restyles the shot, a Publisher that
hands the episode the factual film's title, the Owner approving a draft the Director sent
back, and the showrunner's brief read as a writers' room reads it.

Every provider is faked here: nothing is synthesised, drawn, sent or bought.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import test_serial_identity
import test_serial_voices
from app.factual.story_review import story_gate
from app.media.models import CharacterBible, Storyboard
from app.media.prompt_agent import strip_style_overrides, write_shot_prompts
from app.media.serial_storyboard import SerialStoryboardError, storyboard_from_episode
from app.media.series_look import load_series_look
from app.media.speaker_voices import speaker_segments
from app.story.review import review_episode
from app.story.services import StoryError, decide_episode, write_episode
from sqlalchemy.orm import Session
from test_serial_identity import (
    HOOK,
    Publisher,
    an_episode,
    director_id,
    gate_record,
    prepare,
)
from test_serial_look import fake_editor, models, scenes_of, shot_pack
from test_serial_pipeline import (
    KAEL,
    SARAH,
    SPOKEN,
    beats_for,
    episode_answer,
    fake_director,
    fake_showrunner,
    letters_day,
    registry,
)
from test_serial_voices import (
    RecordingVoice,
    bible,
    bind,
    planned_for,
    serial_board,
    speakers_of_scene,
    use_cast,
)

#: The fixtures of the step files this pass attacks.
films = test_serial_identity.films
staffed = test_serial_identity.staffed
voices = test_serial_voices.voices

# ---------------------------------------------------------------------------- voices


def test_a_locked_speaker_whose_voice_is_gone_is_never_spoken_in_another_voice(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    """Sarah's voice is locked and usable; Kael's is locked to a voice his connection no
    longer lists. Before, Kael's take fell back to the scene's voice, which is Sarah's lock:
    one character spoken in another's locked voice. A lock that cannot be honoured makes the
    scene unspeakable in real voices, exactly as it does for the scene's first locked
    character, and the plan says why."""
    from app.media.assembler import assemble_video_job

    use_cast(monkeypatch, tmp_path, {})
    bind(client, headers, bible(engine, "Sarah").id, voices["integration"], voices["first"], True)
    bind(client, headers, bible(engine, "Kael").id, voices["integration"], voices["second"], True)
    with Session(engine) as session, session.begin():
        kael = session.get(CharacterBible, bible(engine, "Kael").id)
        kael.voice_binding_json = {**(kael.voice_binding_json or {}), "voice_id": "gone-voice"}
    _, ids = letters_day(engine)
    board_id = serial_board(engine, monkeypatch, beats_for(ids, [SARAH, KAEL]))
    planned = planned_for(engine, board_id)

    sarah, kael_take = speakers_of_scene(planned)
    assert sarah["voice"]["speaker_source"] == "character_lock" and sarah["voice"]["valid"]
    assert kael_take["voice"]["speaker_source"] == "character_lock"
    assert kael_take["voice"]["valid"] is False
    scene = next(s for s in planned["plan"]["scenes"] if s["scene_index"] == 1)
    assert "Kael" in scene.get("speakers_note", "")
    assert planned["tts_for_scene"]({"scene_index": 1}) is None

    assemble_video_job(
        engine,
        board_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        tts_adapter=None,
        tts_adapter_for_scene=planned["tts_for_scene"],
        voice_segments_for_scene=planned["voice_segments_for_scene"],
        production_plan=planned["plan"],
    )
    # Nothing was spoken by a vendor voice at all, so Kael's words were never Sarah's.
    assert not [said for voice_id, said in RecordingVoice.heard if said == SPOKEN[1]]
    assert RecordingVoice.heard == []


def test_a_line_nobody_speaks_and_a_speaker_with_no_bible_are_the_narrators():
    takes = speaker_segments(
        [
            {"speaker": None, "text": "  The render bay, before anyone arrives. "},
            {"speaker": "", "text": "Still quiet."},
            {"speaker": "The Owner", "text": "Morning."},
            {"speaker": KAEL, "text": "What is the runtime?"},
            {"speaker": KAEL, "text": ""},
        ],
        {KAEL: "kael-bible"},
    )

    # Each take carries how it is said (2026-10-15): nothing here, so empty.
    assert takes == [
        {
            "speaker": None,
            "character_id": None,
            "text": "The render bay, before anyone arrives. Still quiet.",
            "direction": "",
        },
        {"speaker": "The Owner", "character_id": None, "text": "Morning.", "direction": ""},
        {
            "speaker": KAEL,
            "character_id": "kael-bible",
            "text": "What is the runtime?",
            "direction": "",
        },
    ]


def test_a_speaker_the_storyboard_has_no_bible_for_speaks_in_the_narrators_voice(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    use_cast(monkeypatch, tmp_path, {"Kael Video Editor": voices["first"]})
    board_id = serial_board(engine, monkeypatch)
    from app.factual.models import ScriptDraft

    with Session(engine) as session, session.begin():
        board = session.get(Storyboard, board_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        scenes = [dict(s) for s in script.scenes_json]
        scenes[0]["speaker_bibles"] = {}
        script.scenes_json = scenes

    kael, sarah = speakers_of_scene(planned_for(engine, board_id))

    assert kael["character_id"] is None and sarah["character_id"] is None
    assert {kael["voice"]["voice_id"], sarah["voice"]["voice_id"]} == {voices["narrator"]}
    assert kael["voice"]["speaker_source"] == "narrator" and kael["voice"]["valid"]


# ---------------------------------------------------------------------------- the look

#: A shot plan from a model that ignores the series' look and restyles the shot.
RESTYLED = {
    "subject": "Kael and Sarah at the render desk",
    "action": (
        "Kael swivels his chair toward Sarah, photorealistic live-action footage, "
        "shot on 35mm film with heavy film grain"
    ),
    "camera": "Medium two-shot, 35mm lens, in the style of a Pixar film",
    "emotion": "Kael tense; anime style exaggerated sweat drop",
    "background": "Elena at her desk, black-and-white noir shadows",
    "lighting": "harsh noon sunlight",
    "continuity": "same seats as the previous shot",
}


def test_a_model_that_ignores_the_look_cannot_restyle_the_shot(engine, staffed, monkeypatch):
    block = load_series_look()["block"]
    board_id = serial_board(engine, monkeypatch)
    count = len(scenes_of(engine, board_id))
    pack = shot_pack(count)
    pack["shots"] = [{**shot, **RESTYLED} for shot in pack["shots"]]
    fake_editor(monkeypatch, pack)

    write_shot_prompts(engine, models(), board_id, str(uuid4()))

    for scene in scenes_of(engine, board_id):
        prompt = scene.visual_prompt
        assert prompt.startswith(block)
        tail = prompt[len(block) :].casefold()
        for restyle in (
            "photorealistic",
            "live-action",
            "film grain",
            "35mm film",
            "pixar",
            "anime",
            "noir",
            "black-and-white",
        ):
            assert restyle not in tail, (restyle, prompt)
        # What the model said about the shot's action is kept. Its camera sentence is read
        # for the move only (48bbcd1): the still's framing is the look's shot size, so a lens
        # the model named never reaches the picture.
        assert "stands beside the office desk" in prompt
        assert "35mm lens" not in prompt
        assert scene.prompt_json["from_model"] is True


def test_strip_style_overrides_keeps_the_shot_and_drops_only_the_restyle():
    assert strip_style_overrides("") == ""
    assert (
        strip_style_overrides("Kael leans back, arms crossed; watercolor painting")
        == "Kael leans back, arms crossed"
    )
    assert strip_style_overrides("Nadia writes with her brass pen") == (
        "Nadia writes with her brass pen"
    )
    assert strip_style_overrides("Sarah turns. Rendered as a hand-drawn cartoon.") == (
        "Sarah turns."
    )
    assert strip_style_overrides("Close-up on Kael, widescreen 16:9 frame") == "Close-up on Kael"


# ---------------------------------------------------------------------------- publishing


def test_the_factual_films_title_with_other_tags_is_still_another_films_title(
    engine, films, monkeypatch
):
    """The copy check compared the title and the tags together, so the factual film's exact
    title under the episode's own tags went through whenever one word of it was also in the
    episode. Two films of one day on two channels never share a title."""
    shared = {**HOOK, "title": "The evidence first", "tags": ["science", "method"]}
    model = Publisher(for_episode=shared, for_factual=shared)
    assert prepare(engine, films, model, "factual")["verdict"] == "READY"

    episode_answer = {**shared, "tags": ["office comedy", "Kael"]}
    result = prepare(engine, films, Publisher(episode_answer, shared))

    assert result["metadata_source"] == "studio_fallback"
    assert not result["title"].startswith("The evidence first")
    assert any("cuvânt cu cuvânt" in reason for reason in result["refusals"])


def test_a_title_that_is_only_the_series_marker_is_not_a_title(engine, films):
    result = prepare(engine, films, Publisher({**HOOK, "title": "Inside The Nexus Ep. 1"}, HOOK))

    assert result["metadata_source"] == "studio_fallback"
    assert result["title"] == "The Cut Runs Long | Inside The Nexus Ep. 1"


# ---------------------------------------------------------------------------- the record


def test_the_owner_approving_an_unread_draft_is_his_and_a_failed_one_cannot_be_approved(
    engine, staffed, monkeypatch
):
    """His approval of a draft she never read is recorded as his, with nothing of hers on
    the row, and it lets the film through exactly as it always did. A draft she failed is
    REJECTED by her reading, so there is nothing left for him to approve: no gate opens that
    was closed before."""
    unread = an_episode(engine, monkeypatch)
    decide_episode(engine, unread["id"], True, "")
    board_id = storyboard_from_episode(engine, unread["id"], str(uuid4()))
    record = gate_record(engine, board_id)
    assert record.reviewer_agent_id is None and record.reviewer_agent_id != director_id(engine)
    assert record.run_id is None and record.checks_json == {}
    assert record.notes_json["source"] == "owner_approval"
    assert record.notes_json["director_review"] is None
    with Session(engine) as session:
        assert story_gate(session, session.get(Storyboard, board_id).script_draft_id)[0]

    failed = an_episode(engine, monkeypatch, when=datetime.now(UTC) + timedelta(days=1))
    fake_director(monkeypatch, "FAIL", notes="The turn is not in the events.")
    reviewed = review_episode(engine, registry(), failed["id"], str(uuid4()))
    assert reviewed["verdict"] == "FAIL" and reviewed["status"] == "REJECTED"
    with pytest.raises(StoryError):
        decide_episode(engine, failed["id"], True, "I like it anyway.")
    with pytest.raises(SerialStoryboardError):
        storyboard_from_episode(engine, failed["id"], str(uuid4()))


def test_the_director_cannot_approve_under_her_leave_what_she_did_not_pass(
    engine, staffed, monkeypatch
):
    from test_serial_pipeline import allow_director_approval

    allow_director_approval(engine)
    episode = an_episode(engine, monkeypatch)
    fake_director(monkeypatch, "FAIL", notes="The button does not land.")

    reviewed = review_episode(engine, registry(), episode["id"], str(uuid4()))

    assert reviewed["status"] == "REJECTED"


# ---------------------------------------------------------------------------- the brief


def test_the_brief_asks_for_a_three_second_hook_and_a_button_that_calls_back(
    engine, staffed, monkeypatch
):
    """Read as a writers' room reads it: the hook is the first words heard, inside three
    seconds, and not a greeting; the button pays off something set up earlier and nothing is
    said after it; every beat changes something; a letter known only by its subject is played
    as the sending and the reaction, never given contents."""
    seen: list[str] = []
    log, ids = letters_day(engine, datetime.now(UTC) - timedelta(days=1))
    fake_showrunner(
        monkeypatch,
        episode_answer(beats_for(ids, [SARAH, KAEL])),
        seen,
    )
    write_episode(engine, registry(), log["id"], str(uuid4()))

    brief = seen[0]
    # Since 2026-10-16 the Narrator opens (where we are, who, what is at stake) and closes.
    assert "OPENS WITH THE NARRATOR" in brief and "where we are" in brief
    assert "ONE closing sentence of the NARRATOR" in brief
    assert "calls back" in brief
    assert "every beat changes something" in brief.casefold()
    assert "only by its subject" in brief
    assert "never invent what it said" in brief
