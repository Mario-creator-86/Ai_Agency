"""The serial rung of the Director's ladder (2026-10-12).

Live, film f06808c9 («The Zero Script Club»): the stills of scenes 3 and 4 came back as stacked
panels on every candidate and re-roll, the composer was fixed (48bbcd1), and the walk after the
restart stopped on «Directoarea nu a putut încă rescrie scenele 3, 4 … (Scena nu este una pe
care studioul o rescrie (card, serial, film închis))»: the Director's rewrite reads no serial
scene, a redo would have bought the stored words again, and the film waited for the Owner —
which his rule forbids. A serial scene's words are the composer's: said again with today's
composer when they changed, written as her decision on the scene, so the stills step buys
again on the new words; a scene whose words are already today's says so and is not rewritten.

Later that day the Owner, on scene 4 redone and redone («Cum să lași de 5 ori refacerea
scenei? Nu este clar că este o problemă?»): the gate had refused «two women facing each other
across the ledger instead of the requested medium close-up single on Nadia with Sarah only at
frame edge», and the rung asked the same words again with another seed. Now a technical refusal
of the gate (panels, blur) is still another picture on the same words; a content refusal (the
gate's, a clip QC block, the film QC's findings) goes to her brief, his rewrite and her review,
and the serial composer says the rewritten fields again — who is in frame, the room, the shot's
size and the look stay the studio's. Every provider is faked; nothing is bought.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from app.agents.models import Agent, ModelRecord
from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, _scene_prompt_rewrite
from app.media.models import SceneTake, StoryboardScene
from app.media.prompt_agent import (
    MOVE_SENTENCES,
    SERIAL_BLANK_SENTENCE,
    SERIAL_FACES_SENTENCE,
    SERIAL_LIFE_SENTENCE,
    _serial_camera_move,
    compose_serial_motion,
    compose_serial_prompt,
)
from app.media.prompt_lint import MOTION_CLOSING
from app.media.scene_rewrite import (
    BRIEF_EVENT,
    CONTENT_REFUSAL,
    MOTION,
    REWRITE_REASON,
    SERIAL_RECOMPOSE_REASON,
    SERIAL_REROLL_REASON,
    STILL,
    STILL_KEPT_WHOLE,
    TECHNICAL_REFUSAL,
    refusal_kind,
    rewrite_failed_scene,
    rewrite_for_redo,
    scene_context,
    serial_recomposition,
)
from app.media.series_look import load_series_look
from app.models import DomainEvent
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_look import (  # noqa: F401
    SEQUENCE_SHOT,
    fake_editor,
    models,
    scenes_of,
    serial_board,
    staffed,
)

STALE_STILL = (
    "Warm hand-drawn 2D animation like the studio's own office picture. Location: Accounting & "
    "Treasury, ground floor. Medium close-up on Nadia, a slow tilt down from her face to the "
    "ledger and back up as she speaks, ending on her eyes behind the tortoiseshell glasses. In "
    "frame, facing the viewer: Nadia: Chestnut hair in a low bun. Nadia taps the brass pen once "
    "against the green ledger, pauses before the number, then lays the pen flat."
)
STALE_MOTION = "Static camera, held steady. "


def described_board(engine, monkeypatch) -> str:
    """A serial storyboard whose shots the model described with a camera path and a chain."""
    from app.media.serial_storyboard import describe_serial_shots

    board_id = serial_board(engine, monkeypatch)
    pack = {
        "shots": [
            {"scene_index": index, "story_purpose": "SETUP", **SEQUENCE_SHOT}
            for index in range(1, 7)
        ]
    }
    fake_editor(monkeypatch, pack)
    describe_serial_shots(engine, models(), board_id, str(uuid4()))
    return board_id


def make_stale(engine, board_id: str, scene_index: int) -> None:
    """The scene's stored words as the composer of 2026-10-11 wrote them, before its fix."""
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        package = dict(scene.prompt_json or {})
        package["still_prompt"] = STALE_STILL
        package["motion_prompt"] = STALE_MOTION + str(package.get("action"))
        scene.prompt_json = package
        scene.visual_prompt = STALE_STILL


def refused_by_the_gate(
    engine, board_id: str, scene_index: int, detail: str = "trei panouri suprapuse"
) -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=board_id,
                scene_number=scene_index,
                kind="still",
                prompt_hash=uuid4().hex,
                model_id="Qwen-Image-2512",
                resolution="1530:2720",
                status="REJECTED",
                failure_code="LOCAL.STILL_GATE",
                failure_detail=detail[:500],
                path=None,
                sha256=None,
                created_at=now,
                updated_at=now,
            )
        )


def refused_by_clip_qc(engine, board_id: str, scene_index: int, detail: str) -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=board_id,
                scene_number=scene_index,
                kind="motion",
                prompt_hash=uuid4().hex,
                model_id="LTX-2.5",
                resolution="1080p",
                status="REJECTED",
                failure_code="QC.CLIP",
                failure_detail=detail[:500],
                path=None,
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )


def rewritten_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
            .order_by(DomainEvent.sequence)
        ).all()
        session.expunge_all()
        return list(rows)


def brief_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == BRIEF_EVENT)
            .order_by(DomainEvent.sequence)
        ).all()
        session.expunge_all()
        return list(rows)


# ------------------------------------------------------- scene 4 of f06808c9, as a fixture

NADIA = {
    "id": "nadia",
    "name": "Nadia Accountant",
    "face_hair": "Chestnut hair in a low bun; hazel eyes behind tortoiseshell glasses",
    "outfit": "forest green cardigan over a cream blouse",
    "props": "a brass pen",
}
SARAH_EXEC = {
    "id": "sarah",
    "name": "Sarah Executive",
    "face_hair": "Brunette professional bob",
    "outfit": "navy executive blazer over a white shirt",
    "props": "",
}
#: The package of scene 4 (f06808c9, 2026-10-12): a single on Nadia whose action names both
#: women's first moments — the still came back as the two of them face to face.
SCENE_FOUR = {
    "shot_type": "MEDIUM_CLOSEUP",
    "shot_size": "single",
    "in_frame": [NADIA],
    "characters": [NADIA, SARAH_EXEC],
    "action": (
        "Nadia taps the brass pen once against the green ledger, pauses before the number, "
        "then lays the pen flat; Sarah leans in a fraction as she asks her question."
    ),
    "ending_frame": (
        "Nadia's hazel eyes steady over the laid-flat pen, Sarah waiting at frame edge."
    ),
    "location": "Accounting & Treasury, ground floor",
    "camera_move": "tilt down",
    "emotion": "Nadia composed, Sarah curious",
    "background": "",
    "continuity": "",
}
#: The gate's refusal of that still, as `stills_stage._set_verdicts` writes it on the take.
TWO_WOMEN = (
    "Imaginea nu arată ce cere scena (imaginea ei scrisă și narațiunea) «Frame shows two women "
    "facing each other across the ledger instead of the requested medium close-up single on "
    "Nadia with Sarah only at frame edge»; Modelul de vedere a văzut text lizibil în imagine "
    "«garbled text on the ledger»"
)
BRIEF_FOUR = {
    "diagnosis": (
        "The action names both women's first moments, so the picture became a two-shot across "
        "the ledger; the shot is a single on Nadia."
    ),
    "layer": "still",
    "avoid": ["Sarah facing Nadia across the ledger", "writing on the ledger"],
    "keep": ["Nadia's first moment with the brass pen", "the Accounting room"],
    "change": [
        "the action names only Nadia's moment first and places Sarah at the frame's right "
        "edge, turned to the viewer"
    ],
    "summary_ro": (
        "Imaginea a ieșit un cadru dublu; refac acțiunea: doar Nadia în prim-plan, Sarah la "
        "marginea cadrului."
    ),
}
SHOT_FOUR = {
    "scene_index": 4,
    "action": (
        "Nadia taps the brass pen once against the green ledger and lays it flat; Sarah stands "
        "a sliver inside the right edge of the frame, turned to the viewer"
    ),
    "emotion": "Nadia composed, Sarah quietly curious",
    "ending_frame": (
        "Nadia's hazel eyes steady over the laid-flat pen, Sarah a shape at the frame's right edge"
    ),
    "camera_move": "dolly in",
}
#: Her review of it, answering quality control's two findings (the gate's «; »-joined reasons)
#: by their ids (2026-10-12).
REVIEW_FOUR = {
    "findings": [
        {
            "id": 1,
            "finding": "two women face to face instead of a single on Nadia",
            "treated": True,
            "severity": "serious",
            "by": (
                "Sarah stands a sliver inside the right edge of the frame, turned to the viewer."
            ),
        },
        {
            "id": 2,
            "finding": "garbled text on the ledger",
            "treated": True,
            "severity": "serious",
            "by": SERIAL_BLANK_SENTENCE,
        },
    ],
    "reason_ro": "Acțiunea nouă o pune pe Sarah la marginea cadrului; paginile rămân goale.",
    "cause": "The action named both women's first moments, so the picture became a two-shot.",
    "lesson": (
        "In a single, the action's first moment names only the person the shot is on; anyone "
        "else stands at the frame's edge."
    ),
}
#: Scene 3's finding the same day: the clip's ending, which no rewrite could reach before.
IN_PROFILE = (
    "ending frame shows Nadia and Sarah in profile facing each other instead of facing the viewer"
)
BRIEF_ENDING = {
    "diagnosis": "The clip has no ending frame of its own, so the model turned them to each other.",
    "layer": "motion",
    "avoid": ["the two in profile facing each other"],
    "keep": ["the picture as composed"],
    "change": ["the clip ends on both turned to the viewer"],
    "summary_ro": "Refac doar mișcarea: cadrul se încheie cu amândouă întoarse spre privitor.",
}
SHOT_ENDING = {
    "scene_index": 3,
    "camera_move": "crane down",
    "ending_frame": "Nadia and Sarah both turned to the viewer, Nadia's hands on the closed ledger",
    "emotion": "Nadia calm, Sarah attentive",
}
REVIEW_ENDING = {
    "findings": [
        {
            "id": 1,
            "finding": "ending frame in profile facing each other",
            "treated": True,
            "severity": "serious",
            "by": (
                "The shot ends on Nadia and Sarah both turned to the viewer, Nadia's hands on "
                "the closed ledger."
            ),
        }
    ],
    "reason_ro": "Clipul se încheie acum cu amândouă întoarse spre privitor.",
    "cause": "The motion had no ending frame of its own, so the model ended on a profile.",
    "lesson": "Give every clip its own ending frame with the people turned to the viewer.",
}


#: Scene 4's clip refused by clip QC for what the beat's action asks: the motion layer keeps
#: the action word for word, so no motion rewrite can treat it (f06808c9, 16:46-16:48).
TURNED_AWAY = "Sarah leans in and turns toward Nadia instead of facing the viewer"
#: Her review of the motion rewrite: the finding is locked on the motion layer, quoted from
#: the kept action.
LOCKED_ON_MOTION = {
    "findings": [
        {
            "id": 1,
            "finding": "Sarah turns toward Nadia",
            "treated": False,
            "severity": "serious",
            "why_not": "the kept action still has Sarah lean in toward Nadia",
            "locked": True,
            "locked_words": "Sarah leans in a fraction",
        }
    ],
    "reason_ro": "Mișcarea nu poate schimba acțiunea: Sarah se apleacă tot spre Nadia.",
    "cause": "The beat's action has Sarah lean in toward Nadia.",
    "lesson": "",
}
#: Her review of the picture's rewrite that follows: the finding is treated by the new action.
TREATED_ON_STILL = {
    "findings": [
        {
            "id": 1,
            "finding": "Sarah turns toward Nadia",
            "treated": True,
            "severity": "serious",
            "by": "Sarah stands a sliver inside the right edge of the frame, turned to the viewer.",
        }
    ],
    "reason_ro": "Acțiunea nouă o ține pe Sarah la marginea cadrului, cu fața spre privitor.",
    "cause": "The beat's action has Sarah lean in toward Nadia.",
    "lesson": (
        "In a single, anyone beside the speaker stands at the frame's edge facing the viewer."
    ),
}


class SerialAgents:
    """The Director's and the Video Editor's models, scripted: her brief, his shot, her review
    — each one answer, or a list answered in order (the last repeats)."""

    def __init__(self, brief: Any, shot: Any, review: Any):
        self.brief, self.shot, self.review = brief, shot, review
        self.briefs: list[str] = []
        self.rewrites: list[str] = []
        self.reviews: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    @staticmethod
    def _said(script: Any, asked: int) -> str:
        if isinstance(script, list):
            script = script[min(asked, len(script) - 1)]
        return json.dumps(script) if isinstance(script, dict) else str(script)

    async def generate(self, model, prompt, **kwargs):
        if '"scene-brief"' in prompt:
            self.briefs.append(prompt)
            return GenerateResult(self._said(self.brief, len(self.briefs) - 1), 10, 40, None)
        if '"scene-rewrite"' in prompt:
            self.rewrites.append(prompt)
            return GenerateResult(self._said(self.shot, len(self.rewrites) - 1), 10, 40, None)
        if '"rewrite-review"' in prompt:
            self.reviews.append(prompt)
            return GenerateResult(self._said(self.review, len(self.reviews) - 1), 10, 40, None)
        return GenerateResult("{}", 10, 40, None)


def boundary_data(prompt: str, name: str) -> dict[str, Any]:
    """The data an agent was given inside its inert boundary."""
    found = re.search(
        rf'<untrusted_source_evidence hash="{name}">\n(.*?)\n</untrusted_source_evidence>',
        prompt,
        re.DOTALL,
    )
    assert found is not None, name
    return json.loads(found.group(1))


def agents_say(engine, agents: SerialAgents) -> ProviderRegistry:
    """The staffed studio's agents answer from ``agents``: every model available, one provider."""
    with Session(engine) as session, session.begin():
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalars(select(Agent.provider_id)).first()
    registry = ProviderRegistry()
    registry.register(provider_id, agents)
    return registry


def make_scene_four(engine, board_id: str, scene_index: int = 4) -> StoryboardScene:
    """Scene ``scene_index`` stored as f06808c9's scene 4, its words today's composer's."""
    look = load_series_look()
    with Session(engine) as session, session.begin():
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == board_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        moves = [
            str((row.prompt_json or {}).get("camera_move") or "")
            for row in rows
            if row.scene_index < scene_index and (row.prompt_json or {}).get("camera_move")
        ]
        scene = next(row for row in rows if row.scene_index == scene_index)
        package = {**dict(scene.prompt_json or {}), **SCENE_FOUR}
        package["still_prompt"] = compose_serial_prompt(package, look)
        package["camera_move"] = _serial_camera_move(package, moves)
        package["motion_prompt"] = compose_serial_motion(package, look)
        scene.prompt_json = package
        scene.visual_prompt = package["still_prompt"]
        scene.shot_type = "MEDIUM_CLOSEUP"
    with Session(engine) as session:
        assert serial_recomposition(session, board_id, scene_index) is None, "today's words"
    return next(s for s in scenes_of(engine, board_id) if s.scene_index == scene_index)


def test_a_stale_serial_scene_is_composed_again_as_her_decision(engine, staffed, monkeypatch):  # noqa: F811
    board_id = described_board(engine, monkeypatch)
    make_stale(engine, board_id, 3)
    refused_by_the_gate(engine, board_id, 3)

    outcome = rewrite_failed_scene(engine, models(), board_id, 3, "c-1")

    assert outcome["rewritten"] is True and outcome["layer"] == "still"
    assert outcome["reason"] == SERIAL_RECOMPOSE_REASON
    scene = next(s for s in scenes_of(engine, board_id) if s.scene_index == 3)
    package = dict(scene.prompt_json or {})
    still = package["still_prompt"]
    assert still == scene.visual_prompt
    for path in ("tilt down", "back up", "then lays"):
        assert path not in still, (path, still)
    assert "One continuous picture fills the whole tall frame" in still
    # The move the composer chose for the shot is kept; the motion is today's composer's.
    move = package["camera_move"]
    assert move in MOVE_SENTENCES
    assert package["motion_prompt"].startswith(MOVE_SENTENCES[move])
    assert not package["motion_prompt"].startswith(STALE_MOTION)
    assert SERIAL_FACES_SENTENCE in package["motion_prompt"]
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
        ).all()
        assert event.payload["decided_by"] == "director" and event.payload["layer"] == "still"
        assert event.payload["scene_index"] == 3
        assert event.payload["old_still_prompt"] == STALE_STILL
        assert event.payload["still_prompt"] == still
        # Said again once: the words are today's now.
        assert serial_recomposition(session, board_id, 3) is None


def test_a_serial_scene_whose_clip_words_alone_are_stale_keeps_its_picture(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """2026-10-16: the composer's faces and life sentences changed the clip's words of every
    serial shot and the picture's words of none but the establishing ones. A refused clip whose
    picture words are today's is said again on the motion layer: the decision clears the clip,
    and the stills step does not buy the unchanged picture again."""
    board_id = described_board(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board_id, StoryboardScene.scene_index == 2
            )
        )
        package = dict(scene.prompt_json or {})
        still = package["still_prompt"]
        package["motion_prompt"] = STALE_MOTION + str(package.get("action"))
        scene.prompt_json = package
    refused_by_clip_qc(engine, board_id, 2, "the hands lift off the desk")

    outcome = rewrite_failed_scene(engine, models(), board_id, 2, "c-2")

    assert outcome["rewritten"] is True and outcome["layer"] == MOTION, outcome
    assert outcome["reason"] == SERIAL_RECOMPOSE_REASON
    assert "doar mișcarea" in outcome["summary_ro"]
    (event,) = rewritten_events(engine)
    assert event.payload["layer"] == MOTION and event.payload["decided_by"] == "director"
    assert event.payload["still_prompt"] == event.payload["old_still_prompt"] == still
    assert not event.payload["motion_prompt"].startswith(STALE_MOTION)
    with Session(engine) as session:
        assert serial_recomposition(session, board_id, 2) is None


def test_a_serial_scene_with_todays_words_is_not_rewritten_and_says_so(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """Nothing refused the scene: its words are today's and nothing is made again."""
    board_id = described_board(engine, monkeypatch)

    outcome = rewrite_failed_scene(engine, models(), board_id, 2, "c-2")

    assert outcome["rewritten"] is False
    assert "cuvintele de azi" in outcome["reason"]
    assert "card, serial" not in outcome["reason"]
    with Session(engine) as session:
        assert (
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
            ).all()
            == []
        )


def test_a_serial_scene_with_todays_words_refused_by_quality_control_is_made_again_on_them(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """2026-10-12: a serial scene whose words the composer had already said today, refused by
    the gate for a technical fault (panels), left the rung with nothing to rewrite — and the
    walk stopped on it for good. Her decision is to make the picture again on the same words:
    the record carries it (the hold lifts, the attempts count again), the words stay. A clip
    QC block is about what the clip shows: the words must change, so it goes to her brief and
    is never bought again on the same words."""
    board_id = described_board(engine, monkeypatch)
    before = next(s for s in scenes_of(engine, board_id) if s.scene_index == 2)
    refused_by_the_gate(engine, board_id, 2)

    outcome = rewrite_failed_scene(engine, models(), board_id, 2, "c-2")

    assert outcome["rewritten"] is True and outcome["layer"] == "still"
    assert outcome["reason"] == SERIAL_REROLL_REASON
    assert outcome["refusal_kind"] == TECHNICAL_REFUSAL
    assert "cuvintele de azi" in outcome["summary_ro"] and "altă sămânță" in outcome["summary_ro"]
    after = next(s for s in scenes_of(engine, board_id) if s.scene_index == 2)
    assert after.visual_prompt == before.visual_prompt
    assert dict(after.prompt_json or {}) == dict(before.prompt_json or {})
    (event,) = rewritten_events(engine)
    assert event.payload["decided_by"] == "director" and event.payload["layer"] == "still"
    assert event.payload["reason"] == SERIAL_REROLL_REASON
    assert event.payload["refused_code"] == "LOCAL.STILL_GATE"
    assert event.payload["refusal_kind"] == TECHNICAL_REFUSAL
    assert event.payload["still_prompt"] == event.payload["old_still_prompt"]

    # A clip refused by clip QC is a content refusal: no reroll on the same words; the rung
    # goes on to her brief (here, with no model to answer her, the brief fails and is recorded).
    refused_by_clip_qc(engine, board_id, 4, "apare text ars în cadru")
    clip = rewrite_failed_scene(engine, models(), board_id, 4, "c-4")
    assert clip["rewritten"] is False and "Directoarei" in clip["reason"], clip
    assert clip["reason"] != SERIAL_REROLL_REASON
    assert len(rewritten_events(engine)) == 1
    (attempt,) = brief_events(engine)
    assert attempt.payload["scene_index"] == 4 and attempt.payload["rewritten"] is False
    assert attempt.payload["failures"][0]["code"] == "QC.CLIP"


def test_the_gates_refusal_is_read_by_its_own_phrases():
    """The gate writes only its Romanian reasons on the take, never its violation codes."""
    assert refusal_kind("QC.CLIP", "clipul aproape nu se mișcă") == CONTENT_REFUSAL
    assert refusal_kind("LOCAL.STILL_GATE", TWO_WOMEN) == CONTENT_REFUSAL
    for said in (
        "Modelul de vedere a văzut o față; biblia vizuală interzice fețele «a woman in profile»",
        "Imaginea încalcă biblia vizuală: «glossy 3D render»",
        "Imaginea nu are aspectul filmului «photoreal»",
        "Imaginea nu arată ce cere planul scenei «a cat»",
        "",
    ):
        assert refusal_kind("LOCAL.STILL_GATE", said) == CONTENT_REFUSAL, said
    for said in (
        "Imaginea nu e o singură fotografie: trei benzi suprapuse",
        "Modelul de vedere nu vede o singură fotografie (panouri, colaj, ecran împărțit sau o "
        "bandă goală) «three stacked panels»; Verdictul modelului de vedere: regenerate_still",
        "Imaginea e neclară: 40 sub pragul de 90 (la 512 px)",
        "Imaginea nu e o imagine: flat grey",
        "Imaginea are defecte tehnice «six fingers»",
        "Imaginea nu a fost privită: modelul de vedere nu a fost întrebat",
        "trei panouri suprapuse",
    ):
        assert refusal_kind("LOCAL.STILL_GATE", said) == TECHNICAL_REFUSAL, said


def test_a_content_refusal_of_a_serial_still_goes_through_her_brief_his_rewrite_and_her_review(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """Scene 4 of f06808c9 (2026-10-12): a single on Nadia whose action named both women's
    first moments; the gate refused «two women facing each other across the ledger», and the
    rung asked the same words again with another seed. Now the refusal is content: her brief
    (told who is in frame and how the still is composed), his rewrite of the fields the serial
    composer reads, her review, and the composer says the new action — Sarah at the frame's
    edge — with the look, the room, the framing and the people in frame unchanged."""
    board_id = described_board(engine, monkeypatch)
    before = make_scene_four(engine, board_id, 4)
    refused_by_the_gate(engine, board_id, 4, TWO_WOMEN)
    agents = SerialAgents(BRIEF_FOUR, SHOT_FOUR, REVIEW_FOUR)
    look = load_series_look()

    outcome = rewrite_failed_scene(engine, agents_say(engine, agents), board_id, 4, "c-4")

    assert outcome["rewritten"] is True and outcome["layer"] == "still", outcome
    assert outcome["summary_ro"] == BRIEF_FOUR["summary_ro"]
    # She was told the serial's composition and the finding, in the serial's own terms.
    (asked,) = agents.briefs
    assert "office serial" in asked and "serial_shot" in asked
    assert "two women facing each other across the ledger" in asked
    assert "Medium close-up single at eye level on Nadia" in asked
    assert "Only still is open" in asked
    # He was told which fields the serial composer reads, and her brief.
    (rewrite,) = agents.rewrites
    assert "belongs to the office serial" in rewrite and "FIRST moment of action" in rewrite
    assert "places Sarah at the frame's right edge" in rewrite
    # She reviewed the words before anything was stored: the old action, the new, the diff.
    (review,) = agents.reviews
    assert "Sarah leans in a fraction" in review and "right edge of the frame" in review
    assert '"removed"' in review and '"added"' in review

    after = next(s for s in scenes_of(engine, board_id) if s.scene_index == 4)
    package = dict(after.prompt_json or {})
    still = package["still_prompt"]
    assert still == after.visual_prompt and still != before.visual_prompt
    # The studio's part of the picture is unchanged: the look, the room, the framing, the people.
    assert still.startswith(look["block"])
    assert "Location: Accounting & Treasury, ground floor." in still
    assert "Medium close-up single at eye level on Nadia, facing the viewer" in still
    assert "In frame, facing the viewer: Nadia:" in still and SERIAL_BLANK_SENTENCE in still
    assert package["in_frame"] == [NADIA] and package["shot_size"] == "single"
    assert package["location"] == SCENE_FOUR["location"]
    assert package["series_look_version"] == before.prompt_json["series_look_version"]
    assert package["from_model"] == before.prompt_json["from_model"]
    # The action changed: Nadia's moment alone, Sarah at the frame's edge.
    assert "Sarah leans in a fraction as she asks her question" not in still
    assert "Sarah stands a sliver inside the right edge of the frame" in still
    assert package["action"] == SHOT_FOUR["action"]
    # The clip is the composer's too: the new move with its path, the new ending frame.
    move = package["camera_move"]
    assert move in MOVE_SENTENCES and package["motion_prompt"].startswith(MOVE_SENTENCES[move])
    assert (
        "The shot ends on Nadia's hazel eyes steady over the laid-flat pen"
        in (package["motion_prompt"])
    )
    assert SERIAL_FACES_SENTENCE in package["motion_prompt"]
    # Her rewrite is the decision on the scene: the hold lifts, the stills step buys the new words.
    (event,) = rewritten_events(engine)
    assert event.payload["reason"] == REWRITE_REASON and event.payload["decided_by"] == "director"
    assert event.payload["layer"] == "still" and event.payload["scene_index"] == 4
    assert event.payload["review"]["verdict"] == "TREATS"
    (brief,) = brief_events(engine)
    assert brief.payload["rewritten"] is True and brief.payload["review_verdict"] == "TREATS"
    assert brief.payload["failures"][0]["code"] == "LOCAL.STILL_GATE"
    # Said once: today's composer agrees with the stored words, so nothing is said again.
    with Session(engine) as session:
        assert serial_recomposition(session, board_id, 4) is None
    context = scene_context(engine, board_id, 4)
    assert context is not None and context["serial"] is True
    assert context["bible"]["style"] == look["block"]


def test_a_serial_redo_after_the_film_failed_rewrites_the_movement_and_keeps_the_picture(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """Scene 3 of f06808c9 (2026-10-12): the film's QC found the ending frame in profile, and
    the redo would have bought the stored words again (`rewrite_for_redo` read no serial
    scene). Now the scene is rewritable: its stale words are said again first, 0 credits; her
    brief reads today's words; his motion rewrite reaches the clip's ending; the picture stays
    word for word, and today's composer agrees with what was stored, so nothing loops."""
    board_id = described_board(engine, monkeypatch)
    make_scene_four(engine, board_id, 3)
    make_stale(engine, board_id, 3)
    agents = SerialAgents(BRIEF_ENDING, SHOT_ENDING, REVIEW_ENDING)
    look = load_series_look()

    outcome = rewrite_for_redo(
        engine, agents_say(engine, agents), board_id, 3, "motion", [IN_PROFILE], "c-3"
    )

    assert outcome["rewritable"] is True and outcome["rewritten"] is True, outcome
    assert outcome["layer"] == "motion" and outcome["same_prompt"] is False
    # The stale words were said again before her brief, and the brief read today's words.
    said_again, rewritten = rewritten_events(engine)
    assert said_again.payload["reason"] == SERIAL_RECOMPOSE_REASON
    assert said_again.payload["old_still_prompt"] == STALE_STILL
    assert rewritten.payload["reason"] == REWRITE_REASON and rewritten.payload["layer"] == "motion"
    (asked,) = agents.briefs
    # The prompts she read are today's, not the stale ones the scene stored.
    assert STALE_MOTION not in asked
    assert "tortoiseshell glasses. In frame, facing the viewer: Nadia: Chestnut" not in asked
    assert "Medium close-up single at eye level on Nadia, facing the viewer" in asked
    assert IN_PROFILE in asked and "only motion is open" in asked
    (rewrite,) = agents.rewrites
    assert "action stays word for word" in rewrite

    after = next(s for s in scenes_of(engine, board_id) if s.scene_index == 3)
    package = dict(after.prompt_json or {})
    # The picture stays: the still as today's composer says it, the action untouched.
    assert after.visual_prompt == package["still_prompt"] == compose_serial_prompt(package, look)
    assert after.visual_prompt != STALE_STILL
    assert package["action"] == SCENE_FOUR["action"]
    assert package["emotion"] == SCENE_FOUR["emotion"]
    assert package["motion_emotion"] == SHOT_ENDING["emotion"]
    # The clip ends where her brief asked, on the new move.
    motion = package["motion_prompt"]
    assert "The shot ends on Nadia and Sarah both turned to the viewer" in motion
    assert "Nadia calm, Sarah attentive." in motion and "Nadia composed" not in motion
    assert motion.startswith(MOVE_SENTENCES[package["camera_move"]])
    (brief,) = brief_events(engine)
    assert brief.payload["review_verdict"] == "TREATS" and brief.payload["layer"] == "motion"
    with Session(engine) as session:
        assert serial_recomposition(session, board_id, 3) is None


def test_a_redo_of_a_serial_scene_buys_on_todays_words_not_the_stored_ones(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    board_id = described_board(engine, monkeypatch)
    make_stale(engine, board_id, 4)

    with Session(engine) as session:
        rewrite = _scene_prompt_rewrite(session, board_id, 4, "Qwen-Image-2512")
        assert rewrite is not None
        assert rewrite["old_still_prompt"] == STALE_STILL
        assert "tilt down" not in rewrite["still_prompt"]
        assert rewrite["package"]["camera_move"] in MOVE_SENTENCES
        assert not rewrite["motion_prompt"].startswith(STALE_MOTION)
        assert rewrite["visual_prompt"] == rewrite["still_prompt"]
        # A scene whose words are today's needs no rewrite.
        assert _scene_prompt_rewrite(session, board_id, 2, "Qwen-Image-2512") is None


def test_a_serial_motion_rewrite_whose_finding_is_in_the_kept_action_turns_to_the_picture(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """2026-10-12, 16:46-16:48, f06808c9 scenes 3, 4, 7: the clips were refused for what the
    beat's action asks («Sarah leans in a fraction», «turning fully toward her») and the
    Director briefed the motion; the motion layer keeps the action word for word, her review
    said the words were untreated, his second rewrite could not touch them, and nothing turned
    to the picture. Now her review is given what the motion layer lets him change and the
    words it keeps — the action, the move's sentence, the faces and the room, the closing —
    and says the finding is locked there; he is not asked again on that layer, and her brief
    for the picture follows at once."""
    board_id = described_board(engine, monkeypatch)
    make_scene_four(engine, board_id, 4)
    refused_by_clip_qc(engine, board_id, 4, TURNED_AWAY)
    agents = SerialAgents(
        [BRIEF_ENDING, BRIEF_FOUR],
        [{**SHOT_ENDING, "scene_index": 4}, SHOT_FOUR],
        [LOCKED_ON_MOTION, TREATED_ON_STILL],
    )

    outcome = rewrite_failed_scene(engine, agents_say(engine, agents), board_id, 4, "c-4")

    assert outcome["rewritten"] is True and outcome["layer"] == STILL, outcome
    assert outcome["escalated_from"] == MOTION
    # One motion rewrite, refused as locked, then the picture: two briefs, two rewrites.
    assert len(agents.briefs) == 2 and len(agents.rewrites) == 2 and len(agents.reviews) == 2
    # Her review of the motion rewrite read what the motion layer keeps: the beat's action,
    # the move's own sentence, the faces and the room, and the still as it stays.
    review_data = boundary_data(agents.reviews[0], "rewrite-review")
    terms = review_data["this_layer"]
    assert list(terms["fields_he_may_change"]) == ["camera_move", "ending_frame", "emotion"]
    assert terms["kept_word_for_word"]["action"] == SCENE_FOUR["action"]
    fixed = terms["fixed_sentences"]["motion"]
    motion_said = review_data["prompts_after"]["motion"]
    assert fixed[-1] == MOTION_CLOSING and SERIAL_FACES_SENTENCE in fixed
    # The move's own sentence is said by the camera_move he chose: his to change, never a
    # sentence the layer keeps (2026-10-12 evening review of a50407e).
    assert MOVE_SENTENCES[terms["camera_move"]] not in fixed
    assert terms["said_by_his_fields"]["camera_move"][0] == MOVE_SENTENCES[terms["camera_move"]]
    # Only the composer's sentences the prompt carries. The clip's life follows the plan since
    # 2026-10-16 (a pose or a steady room in the ending takes it out): it is the ending_frame's
    # sentence, his to change, never one the layer keeps.
    assert all(sentence in motion_said for sentence in fixed)
    assert SERIAL_LIFE_SENTENCE not in fixed
    assert (SERIAL_LIFE_SENTENCE in motion_said) == (
        SERIAL_LIFE_SENTENCE in terms["said_by_his_fields"].get("ending_frame", [])
    )
    # The still is kept whole and is in the prompts beside the terms: not said again.
    assert terms["still_kept_whole"] == STILL_KEPT_WHOLE
    assert review_data["prompts_after"]["still"] not in terms["fixed_sentences"]["still"]
    findings = review_data["quality_control_findings"]
    assert [(f["id"], f["qc_text"]) for f in findings] == [(1, TURNED_AWAY)]
    # Her first brief was told the same, for every open layer; the second opens only the still.
    first_brief = boundary_data(agents.briefs[0], "scene-brief")
    assert set(first_brief["layers_he_may_change"]) == {MOTION, STILL}
    assert "only still is open" in agents.briefs[1]
    motion, picture = brief_events(engine)
    assert motion.payload["layer"] == MOTION and motion.payload["layer_exhausted"] is True
    assert motion.payload["rewritten"] is False
    assert picture.payload["layer"] == STILL and picture.payload["rewritten"] is True
    # The picture's words changed: Sarah at the frame's edge; her lesson is the serial's.
    (event,) = rewritten_events(engine)
    assert event.payload["layer"] == STILL and event.payload["review"]["lesson_scope"] == "serial"
    package = dict(next(s for s in scenes_of(engine, board_id) if s.scene_index == 4).prompt_json)
    assert "Sarah stands a sliver inside the right edge of the frame" in package["still_prompt"]
