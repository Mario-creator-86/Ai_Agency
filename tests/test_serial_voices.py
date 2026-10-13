"""S7, one voice per speaker: a beat's lines are spoken by the people who say them.

Measured before this step (2026-09-24): the storyboard bound one voice per scene, the first
speaker's where a bible had a locked voice and the narrator's otherwise, and handed it the
beat's whole text. On the Owner's data no bible has a voice, so every line of every episode
was the narrator's. Now each speaker's lines are a take of their own, in that character's
bound voice (the bible's lock or binding), else the voice the proposal in
config/serial_voice_cast.json names from his own catalogue, else the narrator's; the takes
are joined in order with a short breath between them, and the captions follow the takes.

Every voice here is a recording fake: nothing is synthesised by a vendor.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible, Storyboard, VideoRenderJob
from app.providers.deterministic_media import DeterministicTTSAdapter
from app.story.services import decide_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_production_policy import channels_by_type, connect_elevenlabs, select_voice, set_default
from test_serial_pipeline import (
    KAEL,
    SARAH,
    SPOKEN,
    beats_for,
    letters_day,
    written,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


class RecordingVoice(DeterministicTTSAdapter):
    """A fake vendor voice: says nothing to anyone, remembers what it was asked to say."""

    PROVIDER_NAME = "test_voice"
    model = "test-tts-model"
    heard: list[tuple[str, str]] = []

    def __init__(self, voice_id: str, integration_id: str | None = None):
        self.voice_id = voice_id
        self.integration_id = integration_id

    async def synthesize(self, text: str, **kwargs: Any):
        type(self).heard.append((self.voice_id, text))
        # Twice the placeholder's pace: a take shorter than its planned shot, as a vendor
        # voice usually is, so the padding to the picture is exercised.
        return await super().synthesize(text, voice_id=self.voice_id, speed=2.0)


@pytest.fixture
def voices(client, headers, elevenlabs_api, monkeypatch, tmp_path):
    """A verified voice connection with three discovered voices: the narrator (the
    Organization default) and two others. Every adapter the plan builds is a RecordingVoice."""
    elevenlabs_api.voices.append({"voice_id": f"test-voice-{uuid4()}", "name": "Test voice 3"})
    identifier = connect_elevenlabs(client, headers)
    select_voice(client, headers, identifier)
    models = [m["model_id"] for m in elevenlabs_api.models]
    narrator, first, second = [v["voice_id"] for v in elevenlabs_api.voices]
    set_default(client, headers, identifier, models[0], narrator)
    channels_by_type(client, headers)

    from app.media import factory

    def fake_provider(_engine, _vault, resolved):
        if not resolved or not resolved.get("valid"):
            return None
        return RecordingVoice(resolved["voice_id"], resolved.get("integration_id"))

    monkeypatch.setattr(factory, "tts_provider_for", fake_provider)
    RecordingVoice.heard = []
    return {
        "integration": identifier,
        "model": models[0],
        "narrator": narrator,
        "first": first,
        "second": second,
    }


def use_cast(monkeypatch, tmp_path: Path, voices: dict[str, str], **extra: Any) -> None:
    """A voice-cast proposal written for the test, in the shipped file's shape."""
    from app.media import speaker_voices

    body = {
        "version": 1,
        "status": "PROPOSED",
        "provider_kind": "elevenlabs",
        "use_until_the_owner_binds": True,
        "voices": {name: {"voice_id": voice_id} for name, voice_id in voices.items()},
    }
    body.update(extra)
    path = tmp_path / "serial_voice_cast.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(speaker_voices, "VOICE_CAST_FILE", path)


def bible(engine, fragment: str) -> CharacterBible:
    with Session(engine) as session:
        return session.scalar(
            select(CharacterBible).where(CharacterBible.canonical_name.like(f"{fragment}%"))
        )


def bind(client, headers, character_id: str, integration: str, voice_id: str, lock=False):
    response = client.put(
        f"/api/v1/media/character-bible/{character_id}/voice-binding",
        headers=headers,
        json={"integration_id": integration, "voice_id": voice_id, "language": "en"},
    )
    assert response.status_code == 200, response.text
    if lock:
        response = client.put(
            f"/api/v1/media/character-bible/{character_id}/identity-locks",
            headers=headers,
            json={"voice": True},
        )
        assert response.status_code == 200, response.text


def serial_board(engine, monkeypatch, beats=None) -> str:
    """An approved episode where Kael speaks first and Sarah answers, as a storyboard."""
    from app.media.serial_storyboard import storyboard_from_episode

    _, ids = letters_day(engine)
    episode = written(engine, monkeypatch, beats or beats_for(ids, [KAEL, SARAH]))
    decide_episode(engine, episode["id"], True, "")
    return storyboard_from_episode(engine, episode["id"], str(uuid4()))


def planned_for(engine, board_id: str) -> dict:
    from app.media.factory import render_plan

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    return render_plan(engine, vault, board_id)


def speakers_of_scene(planned: dict, index: int = 1) -> list[dict]:
    scene = next(s for s in planned["plan"]["scenes"] if s["scene_index"] == index)
    return list(scene.get("speakers") or [])


def parse_srt(text: str) -> list[dict]:
    def seconds(stamp: str) -> float:
        hours, minutes, rest = stamp.split(":")
        secs, millis = rest.split(",")
        return int(hours) * 3600 + int(minutes) * 60 + int(secs) + int(millis) / 1000

    cues = []
    for block in text.strip().split("\n\n"):
        rows = block.strip().splitlines()
        start, end = rows[1].split(" --> ")
        cues.append({"start": seconds(start), "end": seconds(end), "text": " ".join(rows[2:])})
    return cues


def by_take(cues: list[dict], texts: list[str]) -> list[list[dict]]:
    """The cues grouped by the take they caption: consecutive cards whose words make up each
    take's line in turn (2026-10-01: a cue is a card of two to five words, not a line)."""
    groups: list[list[dict]] = []
    position = 0
    for text in texts:
        group: list[dict] = []
        while " ".join(c["text"] for c in group) != text:
            assert position < len(cues), (text, cues)
            group.append(cues[position])
            position += 1
        groups.append(group)
    return groups


# ---------------------------------------------------------------------------- the proof


def test_a_two_speaker_beat_is_two_takes_in_two_voices_and_one_caption_track(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    """The plan's proof. Kael speaks first in the voice the proposal gives him, Sarah answers
    in the voice the Owner bound to her; two takes, two voice ids, and one SRT whose cues
    carry the words in order with no name and no stage direction."""
    from app.media.assembler import assemble_video_job
    from app.media.speaker_voices import SPEAKER_GAP_SECONDS

    use_cast(monkeypatch, tmp_path, {"Kael Video Editor": voices["first"]})
    bind(client, headers, bible(engine, "Sarah").id, voices["integration"], voices["second"])
    _, ids = letters_day(engine)
    beats = beats_for(ids, [KAEL, SARAH])
    beats[0]["lines"][0]["text"] = f"Kael: (sighs) {SPOKEN[0]}"
    episode = written(engine, monkeypatch, beats)
    decide_episode(engine, episode["id"], True, "")
    from app.media.serial_storyboard import storyboard_from_episode

    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    planned = planned_for(engine, board_id)

    result = assemble_video_job(
        engine,
        board_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        tts_adapter=None,
        tts_adapter_for_scene=planned["tts_for_scene"],
        voice_segments_for_scene=planned["voice_segments_for_scene"],
        production_plan=planned["plan"],
    )

    # Scene 1: two takes, in the order spoken, in two voices.
    assert RecordingVoice.heard[:2] == [
        (voices["first"], SPOKEN[0]),
        (voices["second"], SPOKEN[1]),
    ]
    # One take per speaker in every scene, and never a name or a direction read aloud.
    assert len(RecordingVoice.heard) == 2 * len(beats)
    for _, said in RecordingVoice.heard:
        assert "(" not in said and "Kael" not in said and "Sarah" not in said
        assert not re.match(r"^\s*\w[\w .]*:", said)

    with Session(engine) as session:
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.storyboard_id == board_id)
        ).one()
        production = job.production_json
    first = production["scenes"][0]
    takes = first["segments"]
    assert [t["voice_id"] for t in takes] == [voices["first"], voices["second"]]
    assert [t["voice_source"] for t in takes] == ["voice_cast_proposal", "character_binding"]
    spoken = sum(t["audio_seconds"] for t in takes) + SPEAKER_GAP_SECONDS
    assert first["audio_seconds"] == pytest.approx(spoken, abs=0.002)

    # One caption track, and it follows the speakers.
    srt = Path(production["captions"]["srt"])
    assert srt.is_file() and Path(result["file_path"]).is_file()
    assert result["voice_source"] == "test_voice"
    assert not list(srt.parent.glob("*.srt"))[1:], "one caption track per film"
    cues = parse_srt(srt.read_text(encoding="utf-8"))
    text = " ".join(c["text"] for c in cues)
    assert "Kael" not in text and "Sarah" not in text and "(" not in text
    # Scene 1's cards: Kael's line while Kael speaks, then Sarah's after the breath.
    kael, sarah = by_take(cues, [SPOKEN[0], SPOKEN[1]])
    assert all(2 <= len(c["text"].split()) <= 5 for c in kael + sarah)
    # Each take's first card comes up on its first word (the voice's own word timing), inside
    # that take: Kael's from the scene's start, Sarah's after Kael's take and the breath.
    sarah_from = takes[0]["audio_seconds"] + SPEAKER_GAP_SECONDS
    assert 0.0 <= kael[0]["start"] < 0.5
    assert kael[-1]["end"] == pytest.approx(takes[0]["audio_seconds"], abs=0.002)
    assert sarah_from - 0.002 <= sarah[0]["start"] < sarah_from + 0.5
    assert sarah[-1]["end"] == pytest.approx(first["audio_seconds"], abs=0.002)

    # The joined voice track is as long as the pictures: each scene's takes are padded to its
    # shot, so the next scene's first speaker starts with the next scene's picture.
    import subprocess

    from app.media.toolchain import find_ffprobe

    ffprobe = find_ffprobe()
    if ffprobe:
        track = srt.parent / "master_audio.wav"
        probed = subprocess.run(  # noqa: S603
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
            + [str(track)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert float(probed.stdout.strip()) == pytest.approx(result["duration_seconds"], abs=0.15)


def test_with_no_real_voice_the_takes_are_placeholders_and_still_captioned_apart(
    engine, staffed, monkeypatch, tmp_path
):
    """A studio with no voice connection renders the placeholder narrator, as before; the
    takes are still separate, so the captions still change with the speaker, and nothing
    claims a character's voice spoke."""
    from app.media.assembler import assemble_video_job

    board_id = serial_board(engine, monkeypatch)
    takes = {
        1: [
            {"speaker": KAEL, "character_id": None, "text": SPOKEN[0], "adapter": None},
            {"speaker": SARAH, "character_id": None, "text": SPOKEN[1], "adapter": None},
        ]
    }

    assemble_video_job(
        engine,
        board_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        voice_segments_for_scene=lambda scene: takes.get(scene["scene_index"]),
    )

    with Session(engine) as session:
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.storyboard_id == board_id)
        ).one()
        production = job.production_json
    first, second = production["scenes"][:2]
    assert [t["voice_source"] for t in first["segments"]] == ["placeholder", "placeholder"]
    assert "segments" not in second  # a scene with no takes is read whole
    cues = parse_srt(Path(production["captions"]["srt"]).read_text(encoding="utf-8"))
    kael, sarah = by_take(cues, [SPOKEN[0], SPOKEN[1]])
    assert sarah[0]["start"] > kael[-1]["end"]


# ---------------------------------------------------------------------------- the choice


def test_a_character_with_no_voice_speaks_in_the_narrators(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    use_cast(monkeypatch, tmp_path, {})
    board_id = serial_board(engine, monkeypatch)

    takes = speakers_of_scene(planned_for(engine, board_id))

    assert [t["speaker"] for t in takes] == [KAEL, SARAH]
    assert [t["voice"]["voice_id"] for t in takes] == [voices["narrator"]] * 2
    assert {t["voice"]["speaker_source"] for t in takes} == {"narrator"}
    assert all(t["voice"]["valid"] for t in takes)


def test_a_bound_or_locked_voice_wins_over_the_proposal(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    use_cast(
        monkeypatch,
        tmp_path,
        {"Sarah Executive": voices["first"], "Kael Video Editor": voices["first"]},
    )
    bind(client, headers, bible(engine, "Sarah").id, voices["integration"], voices["second"], True)
    board_id = serial_board(engine, monkeypatch)

    kael, sarah = speakers_of_scene(planned_for(engine, board_id))

    assert kael["voice"]["voice_id"] == voices["first"]
    assert kael["voice"]["speaker_source"] == "voice_cast_proposal"
    assert sarah["voice"]["voice_id"] == voices["second"]
    assert sarah["voice"]["speaker_source"] == "character_lock"
    assert sarah["character_id"] == bible(engine, "Sarah").id


def test_a_proposed_voice_the_catalogue_does_not_list_is_not_spoken(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    use_cast(monkeypatch, tmp_path, {"Kael Video Editor": "not-in-the-catalogue"})
    board_id = serial_board(engine, monkeypatch)

    kael, _ = speakers_of_scene(planned_for(engine, board_id))

    assert kael["voice"]["voice_id"] == voices["narrator"]
    assert kael["voice"]["speaker_source"] == "narrator"
    assert any("not-in-the-catalogue" in note for note in kael["voice"]["notes"])


def test_a_proposal_switched_off_is_not_used(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    use_cast(
        monkeypatch,
        tmp_path,
        {"Kael Video Editor": voices["first"]},
        use_until_the_owner_binds=False,
    )
    board_id = serial_board(engine, monkeypatch)

    planned = planned_for(engine, board_id)
    kael, _ = speakers_of_scene(planned)

    assert kael["voice"]["voice_id"] == voices["narrator"]
    assert planned["plan"]["voice_cast"]["in_use"] is False


def test_a_consistency_locked_channel_without_voice_locks_narrates_and_says_so(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    """The plan asked to settle it: Channel B is CONSISTENCY_LOCKED and no bible on his data
    has a voice lock. The film is not refused; each unbound speaker has the proposal's
    voice or the channel's narrator, both fixed from episode to episode, and the plan says
    which it was."""
    use_cast(monkeypatch, tmp_path, {})
    board_id = serial_board(engine, monkeypatch)

    planned = planned_for(engine, board_id)

    assert planned["plan"]["policy"] == "CONSISTENCY_LOCKED"
    kael, _ = speakers_of_scene(planned)
    assert kael["voice"]["valid"] and kael["voice"]["speaker_source"] == "narrator"
    assert any("no voice of their own" in note for note in kael["voice"]["notes"])


def test_a_narration_that_no_longer_matches_its_lines_is_read_by_one_voice(
    engine, staffed, client, headers, voices, monkeypatch, tmp_path
):
    """The lines are kept on the script; the scene's narration is what the film says. When
    the two differ, the lines are stale, and the scene is read whole rather than split."""
    from app.media.models import StoryboardScene

    use_cast(monkeypatch, tmp_path, {"Kael Video Editor": voices["first"]})
    board_id = serial_board(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board_id, StoryboardScene.scene_index == 1
            )
        )
        scene.voiceover_segment = "A different sentence the Owner wrote himself."

    planned = planned_for(engine, board_id)

    assert speakers_of_scene(planned, 1) == []
    assert planned["voice_segments_for_scene"]({"scene_index": 1}) is None
    assert len(speakers_of_scene(planned, 2)) == 2


def test_a_factual_storyboard_has_no_speakers(engine, client, headers, voices, tmp_path):
    from test_production_policy import make_storyboard

    board_id = make_storyboard(engine, tmp_path)

    planned = planned_for(engine, board_id)

    assert all(not s.get("speakers") for s in planned["plan"]["scenes"])
    assert planned["voice_segments_for_scene"]({"scene_index": 1}) is None


# ---------------------------------------------------------------------------- the parts


def test_the_storyboard_keeps_which_bible_speaks_each_line(engine, staffed, monkeypatch):
    board_id = serial_board(engine, monkeypatch)
    from app.factual.models import ScriptDraft

    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        first = script.scenes_json[0]
    assert first["speaker_bibles"] == {
        KAEL: bible(engine, "Kael").id,
        SARAH: bible(engine, "Sarah").id,
    }


def test_consecutive_lines_of_one_speaker_are_one_take():
    from app.media.speaker_voices import speaker_segments

    lines = [
        {"speaker": KAEL, "text": "One."},
        {"speaker": KAEL, "text": "Two."},
        {"speaker": None, "text": "Meanwhile."},
        {"speaker": SARAH, "text": "Three."},
        {"speaker": KAEL, "text": "Four."},
    ]

    takes = speaker_segments(lines, {KAEL: "k", SARAH: "s"})

    assert [(t["speaker"], t["character_id"], t["text"]) for t in takes] == [
        (KAEL, "k", "One. Two."),
        (None, None, "Meanwhile."),
        (SARAH, "s", "Three."),
        (KAEL, "k", "Four."),
    ]


def test_captions_follow_the_takes_and_leave_the_breath_empty():
    from app.media.assembler import caption_cues

    scene = {
        "scene_index": 1,
        "duration_seconds": 8.0,
        "audio_seconds": 5.3,
        "voiceover_segment": "First speaker here.\nSecond speaker answers.",
        "voice_segments": [
            {"text": "First speaker here.", "offset": 0.0, "seconds": 2.0},
            {"text": "Second speaker answers.", "offset": 2.3, "seconds": 3.0},
        ],
    }

    cues = caption_cues([scene])

    assert [(c["start"], c["end"], c["lines"]) for c in cues] == [
        (0.0, 2.0, ["First speaker here."]),
        (2.3, 5.3, ["Second speaker answers."]),
    ]


def test_a_take_never_spills_into_the_next_scene():
    from app.media.assembler import caption_cues

    scene = {
        "scene_index": 1,
        "duration_seconds": 4.0,
        "audio_seconds": 6.0,
        "voiceover_segment": "A. B.",
        "voice_segments": [
            {"text": "A.", "offset": 0.0, "seconds": 3.0},
            {"text": "B.", "offset": 3.3, "seconds": 2.7},
        ],
    }

    cues = caption_cues([scene])

    assert cues[-1]["end"] == pytest.approx(4.0)


def test_the_shipped_voice_cast_proposes_eight_distinct_voices_for_the_eight_bibles(engine):
    from app.media.services import seed_default_character_bibles
    from app.media.speaker_voices import load_voice_cast

    seed_default_character_bibles(engine)
    with Session(engine) as session:
        names = set(session.scalars(select(CharacterBible.canonical_name)))
    raw = json.loads((ROOT / "config" / "serial_voice_cast.json").read_text(encoding="utf-8"))
    cast = load_voice_cast()

    assert raw["status"] == "PROPOSED"
    assert set(cast["voices"]) == names and len(names) == 8
    assert len(set(cast["voices"].values())) == 8
    assert all(entry["catalogue_name"] for entry in raw["voices"].values())
    # The narrator on his data is the Organization default; no character takes its voice.
    assert "CwhRBWXzGAHq8TQ4Fs17" not in cast["voices"].values()
