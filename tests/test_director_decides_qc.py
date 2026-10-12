"""The Director decides a film that failed quality control (2026-10-10, film babcf272).

The film was assembled from takes the Owner approved (scenes 1-4, scene 2 his approved test
shot) and scene 5, a still of three stacked panels. Its QC report failed on scene 5's panels
(real), on every scene for «text or a logo» (the studio's own burned-in subtitles: false) and on
scenes 2 and 3 for the bible's near-black void (takes he approved: his choice). The mechanical
repair then redid scenes 1 and 2 unasked and retired his approved takes. Since then the
Director reads the report first and decides; these tests hold that, with a scripted Director
(no vendor, no credit; the redo path is faked where it would buy):

- captions misread and his approved takes: ACCEPT, a PASSED report listing her overrules,
  nothing redone, nothing bought, his takes untouched, a STATUS letter to him;
- scene 5's panels REAL: only scene 5 is redone, through the redo path with ``unasked`` and his
  sheet choices: its new still, then the film rejoined from its takes for free (his LOCAL_MOVE;
  a filmed scene gets the motion filmed from the new still); the new film is measured again;
- a scene whose take he approved, listed by her, is not redone (and the redo path itself refuses
  a plan that would retire one of his takes); a motion for his LOCAL_MOVE scene is not bought;
- an answer that does not validate twice, or no model at all: nothing is redone, the report
  waits in her inbox;
- CLOSE closes the film through the Director's own retirement path; an ACCEPT of a finding that
  is not hers (rights, his music library's licences, his production rule) is refused;
- the watchdog pass queues the film's continuation once per report, and the continuation reads
  the report, she decides, and the accepted film goes to the publication path.

The 2026-10-10 review of this package added: a purchase that made no film yet is told to him
and carried on once its take is approved (BOUGHT_WAITING, one paid round for a still and its
motion); a REPAIR he said no to, or whose question expired, is hers again; with his limits
spent she is told REPAIR is not possible and a REPAIR that can do nothing does not validate;
walks refused by his mode do not use up her tries.

The second review (babcf272 walked after the restart) added: a paid round that delivered
nothing does not spend his limits; a still given back after a redo that delivered nothing is
never the new still (no rejoin of the same film); a refused rejoin keeps her decision waiting
and is tried again, and an approved take bought for her and in no film is something she can
still do; candidates the gate turned down wait (since the same evening, for her own look,
tests/test_director_looks_at_pictures.py) for a few days, not for ever.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.director_qc import (
    DECISION_EVENT,
    INBOX_KIND,
    LETTER_KIND,
    WAITING_EVENT,
    decision_state,
    report_findings,
)
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.services import seed_default_character_bibles
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.services import FILM_CONTINUE_TASK, append_event, utc_now
from app.workflows.models import TaskQueueItem
from sqlalchemy import select
from sqlalchemy.orm import Session

CAPTIONS = "apare text sau un logo"
TUNNEL = "bible: near-black void, the clip shows a tunnel"
PANELS = "cadrul nu este o singură imagine: trei panouri suprapuse"


def test_director_reads_complete_scene_prompts_and_late_bible_rules(engine):
    from app.agents.reviews import failed_render_reading
    from app.media.director_qc import film_qc_context

    film = failed_film(engine)
    still = "Warm cinematic period setting. " * 20 + "A graphite spiral drawn on the napkin."
    motion = "A faint glowing trail rises while the graphite lines remain visible on paper."
    ending = "The paper sketch remains visible beneath the lifted trail."
    bible = {
        "style": "Warm period detail. " * 150,
        "continuity_rules": ["The same pencil spiral remains drawn on the cream napkin."],
        "avoid": ["No visible faces."],
    }
    with Session(engine) as session, session.begin():
        session.get(Storyboard, film["board"]).visual_bible_json = bible
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == film["board"],
                StoryboardScene.scene_index == 5,
            )
        )
        scene.prompt_json = {
            "still_prompt": still,
            "motion_prompt": motion,
            "ending_frame": ending,
        }
    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))
    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    assert scene["asked"] == still
    assert scene["motion_requested"] == motion
    assert scene["ending_frame"] == ending
    assert scene["prompt_sources"]["motion"] == "current_storyboard"
    assert context["visual_bible"] == bible


def test_director_payload_never_slices_critical_evidence_into_invalid_json():
    from app.agents.reviews import DIRECTOR_QC_PAYLOAD_CHARS, _director_payload

    findings = [{"id": i, "text": f"Finding {i}: " + "evidence " * 40} for i in range(1, 81)]
    scenes = [{"scene_index": i, "asked": "Exact submitted intent. " * 20} for i in range(1, 25)]
    bible = {"continuity_rules": ["Keep the graphite drawing visible."]}
    context = {
        "findings": findings,
        "scenes": scenes,
        "visual_bible": bible,
        "paid_redo_limits": {"left_for_film": 3},
        "checks": "optional detail " * 2000,
    }
    assert len(json.dumps(context)) > DIRECTOR_QC_PAYLOAD_CHARS
    parsed = json.loads(_director_payload(context))
    assert parsed["findings"] == findings
    assert parsed["scenes"] == scenes
    assert parsed["visual_bible"] == bible
    assert parsed["paid_redo_limits"] == context["paid_redo_limits"]


def test_director_finding_keeps_the_end_of_the_actual_qc_diagnosis():
    reason = "Scena 5: " + "Observed picture detail. " * 25 + "The graphite sketch is missing."
    findings = report_findings({"failure_reasons_json": [reason], "checks_json": {}})
    assert findings[0]["scene_index"] == 5
    assert findings[0]["text"] == reason


class ScriptedModel:
    """Every agent's model: the Director answers ``director``; anyone else gets ``other``."""

    def __init__(self, director, other: str = "{}"):
        self.director = director
        self.other = other
        self.asked: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        if "director-qc" in prompt:
            self.asked.append(prompt)
            answer = self.director(prompt) if callable(self.director) else self.director
        else:
            answer = self.other
        return GenerateResult(answer, 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def director_says(studio, answer) -> tuple[ProviderRegistry, ScriptedModel]:
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(studio["provider_id"], model)
    return registry, model


def _take(session, board_id: str, scene: int, kind: str, approved_by: str | None) -> str:
    take_id = str(uuid4())
    now = utc_now()
    session.add(
        SceneTake(
            id=take_id,
            storyboard_id=board_id,
            scene_number=scene,
            kind=kind,
            prompt_hash=uuid4().hex,
            model_id="seedream5_pro" if kind == "still" else "seedance2",
            resolution="1080:1920",
            status="APPROVED",
            approved_by=approved_by,
            path=f"storage/{take_id}.bin",
            sha256=uuid4().hex,
            created_at=now,
            updated_at=now,
        )
    )
    return take_id


def failed_film(
    engine,
    *,
    panels: bool = True,
    extra_failures: list[str] | None = None,
    extra_checks: dict[str, Any] | None = None,
    local_move: bool = True,
) -> dict[str, Any]:
    """babcf272 as it stood at 11:04 UTC: five scenes, his approved takes in scenes 1-4 (scene
    2's motion his approved test shot), scene 5 a still the gate approved, animated locally by
    his LOCAL_MOVE choice (``local_move``; without it scene 5 is a filmed scene like the others);
    the film's QC FAILED with the captions, the tunnel and (``panels``) scene 5's panels."""
    from app.media.production_policy import LOCAL_MOVE
    from app.media.shooting_sheet import SCENE_MODEL_EVENT

    ids = {k: str(uuid4()) for k in ("topic", "script", "board", "asset", "job", "report")}
    now = utc_now()
    takes: dict[int, dict[str, str | None]] = {}
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title="The Particle",
                topic="physics",
                angle="a",
                target_audience="g",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title="The Particle That Shouldn't Exist (But Does)",
                voiceover_full_text="text",
                claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title="The Particle That Shouldn't Exist (But Does)",
                status="APPROVED",
                total_scenes=5,
                visual_bible_json={"palette": "near-black void, one cold light"},
                created_at=now,
            )
        )
        session.flush()
        for index in range(1, 6):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=ids["board"],
                    scene_index=index,
                    visual_prompt=f"scene {index}: a particle in the dark",
                    duration_seconds=5.0,
                    voiceover_segment=f"Narration of scene {index}.",
                    scene_kind="LIVE",
                    created_at=now,
                )
            )
        session.flush()
        for index in range(1, 5):
            takes[index] = {
                "still": _take(session, ids["board"], index, "still", "owner"),
                "motion": _take(
                    session, ids["board"], index, "test_shot" if index == 2 else "motion", "owner"
                ),
            }
        takes[5] = {"still": _take(session, ids["board"], 5, "still", "still_gate"), "motion": None}
        if local_move:
            append_event(
                session,
                SCENE_MODEL_EVENT,
                "storyboard",
                ids["board"],
                1,
                {"scene_index": 5, "model_id": LOCAL_MOVE, "decided_by": "owner"},
                str(uuid4()),
            )
        session.add(
            MediaAsset(
                id=ids["asset"],
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{ids['asset']}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=25.0,
                provider_name="SCENE_TAKES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=ids["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at=now,
                finished_at=now,
                production_json={
                    "image": {"provider": "SCENE_TAKES"},
                    "captions": {"burned_in": True, "cues": 12},
                    "scenes": [
                        {
                            "scene_index": index,
                            "scene_kind": "LIVE",
                            "still_take": {"take_id": takes[index]["still"], "status": "APPROVED"},
                            "motion": (
                                {"take_id": takes[index]["motion"], "reused_take": True}
                                if takes[index]["motion"]
                                else None
                            ),
                        }
                        for index in range(1, 6)
                    ],
                },
            )
        )
        session.flush()
        spans = [
            {
                "scene_index": index,
                "passed": False,
                "status": "FAILED",
                "reason": f"{CAPTIONS}; {TUNNEL}" if index in (2, 3) else CAPTIONS,
            }
            for index in range(1, 5)
        ]
        failures = [f"Scena {index}: {CAPTIONS}" for index in range(1, 5)]
        failures.insert(2, f"Scena 2: {TUNNEL}")
        failures.insert(4, f"Scena 3: {TUNNEL}")
        if panels:
            spans.append({"scene_index": 5, "passed": False, "status": "FAILED", "reason": PANELS})
            failures.append(f"Scena 5: {PANELS}")
        failures += extra_failures or []
        checks: dict[str, Any] = {
            "picture_spans_qc": {"passed": False, "status": "MEASURED", "scenes": spans},
            "technical_qc": {"passed": True},
            "rights_qc": {"passed": True, "license_status": "PROPRIETARY_STUDIO"},
            **(extra_checks or {}),
        }
        session.add(
            QualityControlReport(
                id=ids["report"],
                media_asset_id=ids["asset"],
                status="FAILED",
                score=0.0,
                checks_json=checks,
                failure_reasons_json=failures,
                verified_at=now,
            )
        )
    ids["takes"] = takes
    ids["failures"] = failures
    return ids


def verdicts_for(film: dict[str, Any], real: set[int] | None = None) -> list[dict[str, Any]]:
    """Her verdicts on every finding: the captions FALSE, the tunnel his choice, the panels
    REAL (and any finding id in ``real`` REAL)."""
    out = []
    for number, text in enumerate(film["failures"], start=1):
        if number in (real or set()) or PANELS in text:
            verdict, why = "REAL", "the still is three panels, not one picture"
        elif TUNNEL in text:
            verdict, why = "OWNER_CHOICE", "the Owner approved the tunnel take"
        elif CAPTIONS in text:
            verdict, why = "FALSE", "the text is our own burned-in narration subtitles"
        else:
            verdict, why = "ACCEPTED", "accepted as it is"
        out.append({"finding": number, "verdict": verdict, "reason": why})
    return out


def answer(verdicts, decision: str, repairs=None, summary: str = "Am citit raportul.") -> str:
    return json.dumps(
        {"verdicts": verdicts, "decision": decision, "repairs": repairs or [], "summary": summary}
    )


class FakeRedoPath:
    """The paid redo path, faked where it would buy: `redo_plan` prices nothing, `redo_scene`
    records what it was asked (and with which of his sheet choices), a still redo writes the
    new still (APPROVED by the gate, or ``still_status`` PAID: waiting for his look), a motion
    redo joins a new film, and the free rejoin from the takes (`_reencode_from_takes`) joins
    one too; QC of the new film is scripted. ``replaces`` maps (kind, scene) to the takes a plan
    would retire."""

    def __init__(
        self,
        engine,
        monkeypatch,
        *,
        verdict: str = "PASSED",
        replaces=None,
        still_status: str = "APPROVED",
        refuse=None,
        motion_unbought=(),
    ):
        from app.runbook import stages

        self.engine = engine
        #: Scenes whose motion redo the step held NEEDS_OWNER and bought nothing for (the
        #: cyclotron's unpriced RunPod profile, 2026-10-12): the redo returns the step's summary.
        self.motion_unbought = set(motion_unbought)
        self.calls: list[tuple[str, int | None, bool]] = []
        #: Per paid redo, whether it was her confirmed repair (``director_repair``).
        self.confirmed: list[bool] = []
        self.overrides: list[Any] = []
        self.planned_overrides: list[Any] = []
        self.measured: list[str] = []
        self.new_stills: list[str] = []
        self.replaces = dict(replaces or {})
        self.verdict = verdict
        self.still_status = still_status
        #: (kind, scene) -> the SceneRedoRefused a redo raises instead of buying.
        self.refuse = dict(refuse or {})
        monkeypatch.setattr("app.media.assembler.redo_plan", self.plan)
        monkeypatch.setattr("app.media.assembler.redo_scene", self.redo)
        monkeypatch.setattr("app.media.assembler.release_after_qc", lambda *a, **k: {})
        monkeypatch.setattr(stages, "sheet_wiring", lambda *a, **k: {})
        monkeypatch.setattr(stages, "evaluate_media_qc", self.qc)
        monkeypatch.setattr(stages, "_reencode_from_takes", self.rejoin)

    def plan(self, engine, storyboard_id, kind, scene_index=None, **kwargs):
        self.planned_overrides.append(kwargs.get("overrides"))
        return {
            "buyable": True,
            "plan_hash": f"plan-{kind}-{scene_index}",
            "replaces": list(self.replaces.get((kind, scene_index), [])),
            "invalidates": [],
        }

    def redo(self, engine, storyboard_id, correlation_id, *, kind, scene_index=None, **kwargs):
        if (kind, scene_index) in self.refuse:
            raise self.refuse[(kind, scene_index)]
        self.calls.append((kind, scene_index, bool(kwargs.get("unasked"))))
        self.confirmed.append(bool(kwargs.get("director_repair")))
        self.overrides.append(kwargs.get("overrides"))
        if kind == "still":
            with Session(self.engine) as session, session.begin():
                take_id = _take(session, storyboard_id, int(scene_index), "still", "still_gate")
                session.get(SceneTake, take_id).status = self.still_status
            self.new_stills.append(take_id)
            return {
                "still": {
                    "status": "APPROVED" if self.still_status == "APPROVED" else "NEEDS_OWNER"
                },
                "credits": 8,
                "next_ro": (
                    f"Scena {scene_index} așteaptă decizia Proprietarului pe foaia de filmare."
                ),
            }
        if scene_index in self.motion_unbought:
            return {
                "motion": {
                    "bought_shots": 0,
                    "needs_owner": [scene_index],
                    "stopped": None,
                    "scenes": [
                        {
                            "scene_index": scene_index,
                            "status": "NEEDS_OWNER",
                            "reason": (
                                "Profilul RunPod selectat nu poate filma această scenă: nu are "
                                "preț publicat la 1080p"
                            ),
                        }
                    ],
                },
                "film": None,
                "credits": 0,
                "next_ro": "",
            }
        return {"film": {"output_asset_id": self._film(storyboard_id)}, "credits": 6}

    def rejoin(self, engine, settings, vault, storyboard_id, result, correlation, **kwargs):
        self.calls.append((str(kwargs.get("redo") or "encode"), None, False))
        asset_id = self._film(storyboard_id)
        result["applied"].append(
            {"redo": kwargs.get("redo") or "encode", "scene_index": None, "reason": "rejoined"}
        )
        result["made"].append(asset_id)
        result["new_asset"] = asset_id

    def _film(self, storyboard_id: str) -> str:
        asset_id = str(uuid4())
        with Session(self.engine) as session, session.begin():
            # The film rejoined from the takes: a new file and the render that made it.
            made = session.scalars(
                select(VideoRenderJob).where(VideoRenderJob.storyboard_id == storyboard_id)
            ).first()
            session.add(
                MediaAsset(
                    id=asset_id,
                    asset_type="RENDERED_VIDEO",
                    uri_or_path=f"storage/{asset_id}.mp4",
                    file_size_bytes=10,
                    mime_type="video/mp4",
                    width=1080,
                    height=1920,
                    duration_seconds=25.0,
                    provider_name="SCENE_TAKES",
                    license_status="PROPRIETARY_STUDIO",
                    provenance_hash="1" * 64,
                    created_at=utc_now(),
                )
            )
            session.flush()
            session.add(
                VideoRenderJob(
                    id=str(uuid4()),
                    storyboard_id=storyboard_id,
                    status="COMPLETED",
                    output_asset_id=asset_id,
                    started_at=utc_now(),
                    finished_at=utc_now(),
                    production_json=dict(made.production_json) if made is not None else {},
                )
            )
        return asset_id

    def qc(self, engine, asset_id, correlation_id, **_kwargs):
        self.measured.append(asset_id)
        report_id = str(uuid4())
        with Session(engine) as session, session.begin():
            session.add(
                QualityControlReport(
                    id=report_id,
                    media_asset_id=asset_id,
                    status=self.verdict,
                    score=1.0 if self.verdict == "PASSED" else 0.5,
                    checks_json={},
                    failure_reasons_json=[] if self.verdict == "PASSED" else ["Scena 5: x"],
                    verified_at=utc_now(),
                )
            )
        return {"id": report_id, "status": self.verdict}


def no_redo(monkeypatch) -> None:
    """Any redo, plan or measurement is a failure of the test."""
    from app.runbook import stages

    def refuse(*_args, **_kwargs):
        pytest.fail("something was redone or priced")

    monkeypatch.setattr("app.media.assembler.redo_scene", refuse)
    monkeypatch.setattr("app.media.assembler.redo_plan", refuse)
    monkeypatch.setattr(stages, "_apply_repairs", refuse)
    monkeypatch.setattr(stages, "evaluate_media_qc", refuse)


def events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(DomainEvent)
                .where(DomainEvent.event_type == event_type)
                .order_by(DomainEvent.sequence)
            )
        )
        session.expunge_all()
        return rows


def letters(engine, kind: str) -> list[AgentMessage]:
    with Session(engine) as session:
        rows = [
            message
            for message in session.scalars(select(AgentMessage))
            if isinstance(message.body_json, dict) and message.body_json.get("kind") == kind
        ]
        session.expunge_all()
        return rows


def take_statuses(engine, board_id: str) -> dict[str, str]:
    with Session(engine) as session:
        return {
            take.id: take.status
            for take in session.scalars(
                select(SceneTake).where(SceneTake.storyboard_id == board_id)
            )
        }


def untouched(engine, board_id: str, before: dict[str, str]) -> bool:
    """Every take the film had before is as it was (a new still a redo wrote is not one)."""
    now = take_statuses(engine, board_id)
    return {take: now.get(take) for take in before} == before


def nothing_bought(engine) -> None:
    from app.economy.models import ProviderCostRecord

    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == []
        assert session.scalars(select(ProviderCostRecord)).all() == []
    assert events(engine, "media.scene_take_retired") == []
    assert events(engine, "runbook.qc_paid_redo") == []


# ------------------------------------------------------------------------ the findings


def test_the_findings_are_numbered_with_their_check_scene_and_whether_they_are_hers(engine):
    film = failed_film(
        engine,
        extra_failures=["Invalid license status: UNKNOWN"],
        extra_checks={"rights_qc": {"passed": False, "license_status": "UNKNOWN"}},
    )
    with Session(engine) as session:
        report = session.get(QualityControlReport, film["report"])
        findings = report_findings(
            {
                "checks_json": report.checks_json,
                "failure_reasons_json": report.failure_reasons_json,
            }
        )
    assert [item["id"] for item in findings] == list(range(1, len(film["failures"]) + 1))
    by_text = {item["text"]: item for item in findings}
    assert by_text[f"Scena 1: {CAPTIONS}"]["check"] == "picture_spans_qc"
    assert by_text[f"Scena 1: {CAPTIONS}"]["scene_index"] == 1
    assert by_text[f"Scena 5: {PANELS}"]["scene_index"] == 5
    assert by_text["Invalid license status: UNKNOWN"]["check"] == "rights_qc"
    assert by_text["Invalid license status: UNKNOWN"]["not_yours"] is True
    assert not any(item["not_yours"] for item in findings if item["scene_index"])


#: `qc.audio_mix_verdict`'s and `qc.production_path_verdict`'s own words.
MUSIC = (
    "Piesa „bed-01” din film nu este în biblioteca de muzică a Proprietarului (sau nu mai are "
    "licența confirmată)"
)
MUSIC_FILE = "Piesa „bed-01” din film nu este fișierul licențiat (sha256 diferit)"
MUSIC_LEVEL = "Muzica stă la 12.0 LU sub voce, nu la 18-22 LU: vocea trebuie să conducă"
TEMPLATE = (
    "Scena 3 a fost filmată din prompturi-șablon, nu din planul de cadre scris de model: în "
    "PRODUCTION un astfel de film nu se publică."
)


def test_a_music_licence_or_the_production_path_is_not_hers_to_accept_away(
    engine, settings, studio, monkeypatch
):
    """2026-10-10 review: the music library's licence findings and his production rule were
    hers to judge (`audio_mix_qc` and `production_path_qc` were not «not yours»), so her ACCEPT
    wrote a PASSED report and the publishing gate, which never reads the music library, would
    publish an unlicensed track. The track's loudness stays hers."""
    from app.runbook import stages

    film = failed_film(
        engine,
        panels=False,
        extra_failures=[MUSIC, MUSIC_FILE, MUSIC_LEVEL, TEMPLATE],
        extra_checks={
            "audio_mix_qc": {"passed": False, "reasons_ro": [MUSIC, MUSIC_FILE, MUSIC_LEVEL]},
            "production_path_qc": {
                "passed": False,
                "template_scenes": [3],
                "reasons_ro": [TEMPLATE],
            },
        },
    )
    with Session(engine) as session:
        report = session.get(QualityControlReport, film["report"])
        findings = {
            item["text"]: item
            for item in report_findings(
                {
                    "checks_json": report.checks_json,
                    "failure_reasons_json": report.failure_reasons_json,
                }
            )
        }
    assert findings[MUSIC]["check"] == "audio_mix_qc" and findings[MUSIC]["not_yours"] is True
    assert findings[MUSIC_FILE]["not_yours"] is True
    assert findings[MUSIC_LEVEL]["check"] == "audio_mix_qc"
    assert findings[MUSIC_LEVEL]["not_yours"] is False
    # Named by its scene, but his production rule, not a picture finding of hers.
    assert findings[TEMPLATE]["check"] == "production_path_qc"
    assert findings[TEMPLATE]["not_yours"] is True

    registry, _model = director_says(studio, answer(verdicts_for(film), "ACCEPT"))
    no_redo(monkeypatch)
    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "ACCEPT_REFUSED" and outcome["passed_asset"] is None
    with Session(engine) as session:
        statuses = session.scalars(
            select(QualityControlReport.status).where(
                QualityControlReport.media_asset_id == film["asset"]
            )
        ).all()
    assert statuses == ["FAILED"]


# ------------------------------------------------------------------------------ ACCEPT


def test_captions_misread_and_his_approved_takes_are_accepted_and_nothing_is_redone(
    engine, settings, studio, monkeypatch
):
    from app.media.production_policy import LOCAL_MOVE
    from app.publishing.services import QC_MINIMUM_SCORE
    from app.runbook import stages

    film = failed_film(engine, panels=False)
    before = take_statuses(engine, film["board"])
    registry, model = director_says(studio, answer(verdicts_for(film), "ACCEPT"))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "ACCEPTED"
    assert outcome["passed_asset"] == film["asset"]
    # She was given the whole context, as data: the captions fact, his approvals, the bible.
    prompt = model.asked[-1]
    assert "burns its own subtitles" in prompt
    assert '"approved_by_owner": true' in prompt
    assert "near-black void" in prompt
    assert LOCAL_MOVE in prompt
    # The film now stands on a PASSED report that keeps the measured checks and lists her
    # overrules, so the publishing QC gate lets it through.
    with Session(engine) as session:
        newest = session.scalars(
            select(QualityControlReport)
            .where(QualityControlReport.media_asset_id == film["asset"])
            .order_by(QualityControlReport.verified_at.desc())
        ).first()
        assert newest.id != film["report"]
        assert newest.status == "PASSED"
        assert newest.score >= QC_MINIMUM_SCORE
        assert newest.checks_json["picture_spans_qc"]["passed"] is False
        director = newest.checks_json["director_qc"]
        assert director["passed"] is True and director["of_report"] == film["report"]
        assert director["original_failures"] == film["failures"]
        overrules = {item["text"]: item for item in director["overrules"]}
        assert overrules[f"Scena 1: {CAPTIONS}"]["verdict"] == "FALSE"
        assert overrules[f"Scena 2: {TUNNEL}"]["verdict"] == "OWNER_CHOICE"
        assert overrules[f"Scena 2: {TUNNEL}"]["owner_choice_confirmed"] is True
    # The publishing gate's QC check reads that report and passes (its other gates run apart).
    from app.publishing.models import ChannelRecord
    from app.publishing.services import evaluate_publishing_gate, seed_default_channels

    seed_default_channels(engine)
    with Session(engine) as session:
        channel_id = session.scalars(select(ChannelRecord.id)).first()
    gate = evaluate_publishing_gate(engine, film["asset"], channel_id)
    (qc_gate,) = [check for check in gate["checks"] if check["check_name"] == "QC_GATE"]
    assert qc_gate["passed"] is True, qc_gate
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["decision"] == "ACCEPT" and decided.payload["outcome"] == "ACCEPTED"
    assert decided.payload["final"] is True
    assert len(decided.payload["verdicts"]) == len(film["failures"])
    assert decided.payload["passed_report_id"] == newest.id
    # Nothing redone, nothing bought, his takes untouched.
    assert untouched(engine, film["board"], before)
    nothing_bought(engine)
    # He is told, in a STATUS letter: not a question.
    (letter,) = letters(engine, LETTER_KIND)
    assert letter.intent == "STATUS" and letter.body_json.get("to") == "Owner"
    assert "fals, controlul a citit greșit filmul" in letter.body_text
    assert "alegerea ta" in letter.body_text
    assert "publicare" in letter.body_text
    # Asked again, the standing decision answers: no second review, no second letter.
    again = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert again["outcome"] == "ACCEPTED" and len(model.asked) == 1
    assert len(letters(engine, LETTER_KIND)) == 1


def test_an_accept_of_a_finding_that_is_not_hers_is_refused(engine, settings, studio, monkeypatch):
    from app.runbook import stages

    film = failed_film(
        engine,
        panels=False,
        extra_failures=["Invalid license status: UNKNOWN"],
        extra_checks={"rights_qc": {"passed": False, "license_status": "UNKNOWN"}},
    )
    registry, _model = director_says(studio, answer(verdicts_for(film), "ACCEPT"))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "ACCEPT_REFUSED" and outcome["passed_asset"] is None
    with Session(engine) as session:
        statuses = session.scalars(
            select(QualityControlReport.status).where(
                QualityControlReport.media_asset_id == film["asset"]
            )
        ).all()
    assert statuses == ["FAILED"]
    (letter,) = letters(engine, LETTER_KIND)
    assert "nu se publică" in letter.body_text


# ------------------------------------------------------------------------------ REPAIR


def test_the_panels_are_real_and_only_scene_5_is_redone(engine, settings, studio, monkeypatch):
    """Scene 5 is his LOCAL_MOVE: her new still is bought (unasked, under his rule) and the film
    is rejoined from its takes with the new still animated locally, for 0 credits. No paid
    motion is bought against his choice (2026-10-10 review: the repair bought a 340-credit
    motion there on an auto-selected model), and his sheet choices price every redo."""
    from app.media.production_policy import LOCAL_MOVE
    from app.runbook import stages

    film = failed_film(engine)
    before = take_statuses(engine, film["board"])
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    # Only her scene: the new still, unasked (his rule), then the free rejoin; no motion.
    assert redo.calls == [("still", 5, True), ("rejoin", None, False)]
    assert redo.planned_overrides == [{5: LOCAL_MOVE}]
    assert redo.overrides == [{5: LOCAL_MOVE}]
    assert outcome["outcome"] == "REPAIRED"
    (repair,) = outcome["repairs"]
    assert repair["new_asset"] and outcome["passed_asset"] == repair["new_asset"]
    assert redo.measured == [repair["new_asset"]]
    assert [(item["redo"], item["scene_index"]) for item in repair["bought"]] == [("still", 5)]
    assert [item["redo"] for item in repair["applied"]] == ["rejoin"]
    assert untouched(engine, film["board"], before)
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["outcome"] == "REPAIRED" and decided.payload["final"] is True
    assert decided.payload["repairs"] == [
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"}
    ]
    (paid,) = events(engine, "runbook.qc_paid_redo")
    assert paid.payload["scene_index"] == 5 and paid.payload["kinds"] == ["still"]
    (letter,) = letters(engine, LETTER_KIND)
    assert "scena 5" in letter.body_text.lower()
    assert "a trecut controlul calității" in letter.body_text


def test_a_motion_she_lists_for_his_local_move_scene_is_not_bought(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine)
    repairs = [
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"},
        {"scene_index": 5, "redo": "motion", "reason": "animate the new picture"},
    ]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert ("motion", 5, True) not in redo.calls
    (decided,) = events(engine, DECISION_EVENT)
    skipped = {
        (item["redo"], item["scene_index"]): item["status"]
        for item in decided.payload["done"]["skipped"]
    }
    assert skipped == {("motion", 5): "OWNER_CHOICE"}
    (letter,) = letters(engine, LETTER_KIND)
    assert "LOCAL_MOVE" in letter.body_text


def test_a_filmed_scene_gets_its_new_still_and_the_motion_filmed_from_it(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("still", 5, True), ("motion", 5, True)]
    assert outcome["outcome"] == "REPAIRED"
    (paid,) = events(engine, "runbook.qc_paid_redo")
    assert paid.payload["kinds"] == ["still", "motion"] and paid.payload["open_motion"] is False


def his_final_look(engine, film: dict[str, Any], scene: int, kind: str) -> None:
    """His APPROVED on the sheet marked final (`decide_take` ``final``), as its event records
    it: what no repair of the Director's retires (2026-10-11, his card)."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.scene_take_decided",
            "scene_take",
            film["takes"][scene][kind],
            1,
            {
                "storyboard_id": film["board"],
                "scene_number": scene,
                "kind": kind,
                "decision": "APPROVED",
                "decided_by": "owner",
                "final": True,
            },
            str(uuid4()),
        )


def test_a_scene_whose_take_he_approved_as_final_is_not_redone_even_when_she_lists_it(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine)
    his_final_look(engine, film, 1, "still")
    his_final_look(engine, film, 2, "motion")
    before = take_statuses(engine, film["board"])
    repairs = [
        {"scene_index": 1, "redo": "still", "reason": "the text is in the picture"},
        {"scene_index": 2, "redo": "motion", "reason": "the tunnel"},
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"},
    ]
    registry, _model = director_says(
        studio, answer(verdicts_for(film, real={1, 3}), "REPAIR", repairs)
    )
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("still", 5, True), ("rejoin", None, False)]
    assert untouched(engine, film["board"], before)
    (decided,) = events(engine, DECISION_EVENT)
    skipped = {
        (item["redo"], item["scene_index"]): item["status"]
        for item in decided.payload["done"]["skipped"]
    }
    assert skipped == {("still", 1): "OWNER_APPROVED", ("motion", 2): "OWNER_APPROVED"}
    assert outcome["outcome"] == "REPAIRED"
    (letter,) = letters(engine, LETTER_KIND)
    assert "aprobată de tine ca finală" in letter.body_text


def test_a_take_he_approved_without_final_is_redone_by_her_confirmed_repair_and_he_is_told(
    engine, settings, studio, monkeypatch
):
    """His card of 2026-10-11 («Directoarea poate reface și ce am aprobat eu»): her repair of
    a real defect replaces a take he approved without marking it final, every paid redo of
    hers runs as her confirmed repair, and his letter says what of his was replaced and why."""
    from app.runbook import stages

    film = failed_film(engine)
    his_still, his_clip = film["takes"][1]["still"], film["takes"][2]["motion"]
    repairs = [
        {"scene_index": 1, "redo": "still", "reason": "the text is in the picture"},
        {"scene_index": 2, "redo": "motion", "reason": "the tunnel"},
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"},
    ]
    registry, _model = director_says(
        studio, answer(verdicts_for(film, real={1, 3}), "REPAIR", repairs)
    )
    redo = FakeRedoPath(
        engine, monkeypatch, replaces={("still", 1): [his_still], ("motion", 2): [his_clip]}
    )

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [
        ("still", 1, True),
        ("motion", 1, True),
        ("motion", 2, True),
        ("still", 5, True),
        ("rejoin", None, False),
    ]
    assert redo.confirmed == [True, True, True, True]
    assert outcome["outcome"] == "REPAIRED"
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["done"]["skipped"] == []
    replaced = decided.payload["done"]["replaced_his"]
    assert [(r["redo"], r["scene_index"], r["takes"], r["reason"]) for r in replaced] == [
        ("still", 1, [his_still], "the text is in the picture"),
        ("motion", 2, [his_clip], "the tunnel"),
    ]
    (letter,) = letters(engine, LETTER_KIND)
    assert "pe care o aprobaseși" in letter.body_text and "«finală»" in letter.body_text
    assert "the text is in the picture" in letter.body_text and "the tunnel" in letter.body_text


def test_the_redo_path_itself_lets_her_confirmed_repair_replace_his_take_and_records_it(
    engine, settings, studio, monkeypatch
):
    from app.media.qc_report import RedoProposal
    from app.runbook import stages

    film = failed_film(engine)
    his_still = film["takes"][1]["still"]
    redo = FakeRedoPath(engine, monkeypatch, replaces={("still", 1): [his_still]})
    result: dict[str, Any] = {
        "applied": [],
        "bought": [],
        "asked": [],
        "refused": [],
        "limited": [],
        "made": [],
        "new_asset": None,
    }
    reading = {
        "storyboard_id": film["board"],
        "media_asset_id": film["asset"],
        "proposals": [RedoProposal(redo="still", scene_index=1, reason="x", credits=None)],
    }

    stages._apply_repairs(engine, settings, None, None, reading, result, False, "c")

    assert redo.calls == [("still", 1, True)] and redo.confirmed == [True]
    assert result["refused"] == []
    assert result["replaced_his"] == [
        {"redo": "still", "scene_index": 1, "takes": [his_still], "reason": "x"}
    ]


def test_the_redo_path_itself_refuses_a_plan_that_would_retire_his_final_take(
    engine, settings, studio, monkeypatch
):
    """Whoever builds the list: an unasked redo whose plan retires a take he approved as
    final is refused before anything is priced or bought."""
    from app.media.qc_report import RedoProposal
    from app.runbook import stages

    film = failed_film(engine)
    his_still = film["takes"][1]["still"]
    his_final_look(engine, film, 1, "still")
    redo = FakeRedoPath(engine, monkeypatch, replaces={("still", 1): [his_still]})
    result: dict[str, Any] = {
        "applied": [],
        "bought": [],
        "asked": [],
        "refused": [],
        "limited": [],
        "made": [],
        "new_asset": None,
    }
    reading = {
        "storyboard_id": film["board"],
        "media_asset_id": film["asset"],
        "proposals": [RedoProposal(redo="still", scene_index=1, reason="x", credits=None)],
    }

    stages._apply_repairs(engine, settings, None, None, reading, result, False, "c")

    assert redo.calls == []
    (refused,) = result["refused"]
    assert refused["status"] == stages.OWNER_APPROVED_REDO
    assert result["bought"] == [] and result["new_asset"] is None


def test_her_next_round_yields_the_worker_when_another_film_waits(
    engine, settings, studio, monkeypatch
):
    """2026-10-12: the cyclotron's rounds (repair, render, QC, read again, up to four) held the
    one worker an hour while the serial's walk waited in the queue. When another film's
    continuation is QUEUED, the repaired film's new report is queued as a continuation of its
    own (the review pass's key) and this walk ends; nobody waiting, the round runs here."""
    from app.runbook import stages

    film = failed_film(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        session.add(
            TaskQueueItem(
                id=str(uuid4()),
                workflow_id=None,
                step_id=None,
                task_type=FILM_CONTINUE_TASK,
                payload={"storyboard_id": "another-film", "cause": "serial_unfilmed_after_start"},
                priority=4,
                status="QUEUED",
                attempts=0,
                max_attempts=1,
                backoff_seconds=60,
                next_attempt_at=utc_now(),
                idempotency_key="film-continue-another-film-serial-after-start-x",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    first = answer(verdicts_for(film), "REPAIR", repairs)
    second = answer([{"finding": 1, "verdict": "ACCEPTED", "reason": "good enough"}], "ACCEPT")
    first_report = f'"report_id": "{film["report"]}", "status"'
    registry, model = director_says(
        studio, lambda prompt: first if first_report in prompt else second
    )
    redo = FakeRedoPath(engine, monkeypatch, verdict="FAILED")

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    (repair,) = outcome["repairs"]
    assert len(model.asked) == 1, "she read the new report in the same walk"
    assert [round_["outcome"] for round_ in outcome["rounds"]] == ["REPAIRED"]
    assert outcome["yielded"]
    with Session(engine) as session:
        task = session.get(TaskQueueItem, outcome["yielded"])
        assert task is not None and task.status == "QUEUED"
        assert task.payload["storyboard_id"] == film["board"]
        assert task.payload["cause"] == f"director_qc:{repair['requalified_report_id']}"
        assert task.idempotency_key.endswith(f"-director-qc-{repair['requalified_report_id']}-0")
    # One paid redo (and the rejoin that completes it): the second round did not run here.
    assert [call for call in redo.calls if call[0] == "still"] == [("still", 5, True)]


def test_a_repaired_film_that_fails_again_is_read_by_her_again(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    first = answer(verdicts_for(film), "REPAIR", repairs)
    second = answer([{"finding": 1, "verdict": "ACCEPTED", "reason": "good enough"}], "ACCEPT")
    first_report = f'"report_id": "{film["report"]}", "status"'
    registry, model = director_says(
        studio, lambda prompt: first if first_report in prompt else second
    )
    redo = FakeRedoPath(engine, monkeypatch, verdict="FAILED")

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    (repair,) = outcome["repairs"]
    assert len(model.asked) == 2
    assert outcome["outcome"] == "ACCEPTED" and outcome["passed_asset"] == repair["new_asset"]
    assert [round_["outcome"] for round_ in outcome["rounds"]] == ["REPAIRED", "ACCEPTED"]
    assert len(redo.calls) == 2


# ------------------------------------------------------------------- she cannot decide


@pytest.mark.parametrize(
    "said",
    [
        "I would rather redo every scene.",
        # REAL and ACCEPT at once is not a decision.
        "contradiction",
        # A finding left without a verdict is a half-read report.
        "incomplete",
    ],
)
def test_an_unusable_answer_waits_and_nothing_is_redone(
    engine, settings, studio, monkeypatch, said
):
    from app.runbook import stages

    film = failed_film(engine)
    before = take_statuses(engine, film["board"])
    if said == "contradiction":
        said = answer(verdicts_for(film), "ACCEPT")
    elif said == "incomplete":
        said = answer(
            verdicts_for(film)[:2], "REPAIR", [{"scene_index": 5, "redo": "still", "reason": "x"}]
        )
    registry, model = director_says(studio, said)
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    # Asked once more with her own thinking (`structured_run`), then the film waits.
    assert len(model.asked) == 2
    assert outcome["outcome"] == "WAITING" and outcome["passed_asset"] is None
    assert events(engine, DECISION_EVENT) == []
    (waited,) = events(engine, WAITING_EVENT)
    assert waited.aggregate_id == film["report"]
    (note,) = letters(engine, INBOX_KIND)
    assert note.to_agent_id is None and note.body_json.get("to") != "Owner"
    assert note.body_json["report_id"] == film["report"]
    assert untouched(engine, film["board"], before)
    nothing_bought(engine)
    assert letters(engine, LETTER_KIND) == []

    # Asked again later: one more wait, still one note in her inbox.
    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert len(events(engine, WAITING_EVENT)) == 2
    assert len(letters(engine, INBOX_KIND)) == 1
    assert decision_state(engine, film["report"])["tries"] == 2


def test_with_no_model_nothing_is_redone_and_the_report_waits(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine)
    before = take_statuses(engine, film["board"])
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, None, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "WAITING"
    assert untouched(engine, film["board"], before)
    nothing_bought(engine)
    (note,) = letters(engine, INBOX_KIND)
    assert "niciun model" in note.body_text


def test_the_days_qc_puts_a_failed_film_before_her_and_never_repairs_it_by_itself(
    engine, settings, studio, monkeypatch
):
    """`_edit_and_qc`: the film fails QC; with no model nothing is repaired (the old
    mechanical repair is gone), and with her ACCEPT it is the day's passed film."""
    from app.runbook import stages

    film = failed_film(engine, panels=False)
    with Session(engine) as session, session.begin():
        session.execute(
            QualityControlReport.__table__.delete().where(QualityControlReport.id == film["report"])
        )
    failures, checks = (
        film["failures"],
        {
            "picture_spans_qc": {
                "passed": False,
                "scenes": [
                    {"scene_index": i, "passed": False, "status": "FAILED", "reason": CAPTIONS}
                    for i in range(1, 5)
                ],
            }
        },
    )
    measured: list[str] = []

    def qc(engine_, asset_id, correlation_id, **_kwargs):
        measured.append(asset_id)
        report_id = str(uuid4())
        film["report"] = report_id
        with Session(engine_) as session, session.begin():
            session.add(
                QualityControlReport(
                    id=report_id,
                    media_asset_id=asset_id,
                    status="FAILED",
                    score=0.0,
                    checks_json=checks,
                    failure_reasons_json=failures,
                    verified_at=utc_now(),
                )
            )
        return {"id": report_id, "status": "FAILED"}

    monkeypatch.setattr(stages, "evaluate_media_qc", qc)
    monkeypatch.setattr("app.media.assembler.release_after_qc", lambda *a, **k: {})
    registry, _model = director_says(studio, answer(verdicts_for(film), "ACCEPT"))

    outcome = stages._edit_and_qc(engine, registry, settings, asset_ids=[film["asset"]])

    assert measured == [film["asset"]]
    assert outcome["artefacts"]["failed"] == 1
    assert outcome["artefacts"]["passed_assets"] == [film["asset"]]
    assert outcome["artefacts"]["decisions"][0]["outcome"] == "ACCEPTED"
    assert "Directoarea a decis" in outcome["reason"]
    assert events(engine, "runbook.qc_repair") == []


# ------------------------------------------------------------------------------- CLOSE


def test_she_never_closes_a_film_for_its_quality_it_waits_to_be_redone(
    engine, settings, studio, monkeypatch
):
    """The Owner, 2026-10-11: «Nu trebuie să respingă un film, trebuie să îl refacă până trece
    QC». CLOSE is no longer hers to answer: it is not offered, an answer of CLOSE does not
    validate, and the film is neither closed nor retired; the report waits for her."""
    from app.runbook import stages

    film = failed_film(engine)
    registry, model = director_says(studio, answer(verdicts_for(film), "CLOSE"))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "WAITING" and outcome["passed_asset"] is None
    assert '"ACCEPT" | "REPAIR",' in model.asked[0] and "CLOSE" not in model.asked[0]
    with Session(engine) as session:
        assert session.get(Storyboard, film["board"]).status != "REJECTED"
    assert events(engine, stages.FILM_RETIRED_EVENT) == []
    assert events(engine, DECISION_EVENT) == []
    nothing_bought(engine)


# --------------------------------------------------------------- the watchdog and the walk


def _production(engine) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"


def _pass(engine, settings) -> dict[str, Any]:
    from app.workflows.passes import WatchdogContext
    from app.workflows.passes.director_qc_review import queue_director_reviews

    return dict(queue_director_reviews(WatchdogContext(engine, settings, "watchdog")))


def _continuations(engine) -> list[TaskQueueItem]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(TaskQueueItem).where(TaskQueueItem.task_type == FILM_CONTINUE_TASK)
            )
        )
        session.expunge_all()
        return rows


def test_the_pass_queues_her_review_once_per_report_and_only_in_production(
    engine, settings, studio
):
    film = failed_film(engine)
    assert _pass(engine, settings) == {"queued": []}  # TEST: the walk buys nothing there

    _production(engine)
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    (task,) = _continuations(engine)
    assert task.payload["cause"] == f"director_qc:{film['report']}"
    assert film["report"] in task.idempotency_key

    # Queued (or at work): nothing more. Done without a walk recorded: the same key, nothing.
    assert _pass(engine, settings) == {"queued": []}
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task.id).status = "DONE"
    assert _pass(engine, settings) == {"queued": []}
    assert len(_continuations(engine)) == 1

    # Her final decision ends it.
    with Session(engine) as session, session.begin():
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            film["report"],
            1,
            {
                "report_id": film["report"],
                "storyboard_id": film["board"],
                "decision": "CLOSE",
                "outcome": "CLOSED",
                "final": True,
            },
            "c",
        )
    assert _pass(engine, settings) == {"queued": []}


def test_a_report_she_could_not_decide_is_asked_again_only_after_a_while(
    engine, settings, studio, monkeypatch
):
    from app.workflows.passes import director_qc_review

    film = failed_film(engine)
    _production(engine)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            WAITING_EVENT,
            "quality_control_report",
            film["report"],
            1,
            {"storyboard_id": film["board"], "reason": "no model"},
            "c",
        )
    assert _pass(engine, settings) == {"queued": []}  # she was asked a moment ago

    monkeypatch.setattr(director_qc_review, "RETRY_MINUTES", 0)
    assert _pass(engine, settings) == {"queued": [film["board"]]}

    monkeypatch.setattr(director_qc_review, "MAX_TRIES", 1)
    with Session(engine) as session, session.begin():
        for task in session.scalars(select(TaskQueueItem)):
            task.status = "DONE"
        append_event(
            session,
            "runbook.film_continued",
            "storyboard",
            film["board"],
            1,
            {"status": "SKIPPED", "cause": f"director_qc:{film['report']}"},
            "c",
        )
    assert _pass(engine, settings) == {"queued": []}  # it waits in her inbox now


def test_after_the_restart_the_continuation_puts_the_film_before_her_and_publishes_it(
    engine, settings, studio, monkeypatch
):
    """babcf272 after the restart: d4ea68d2 FAILED and undecided; the pass queues the walk,
    the walk reads the report to her, she accepts, and the film goes to the publication path
    (under the channel's policy), with nothing redone."""
    from app.runbook import stages

    film = failed_film(engine, panels=False)
    _production(engine)
    assert _pass(engine, settings) == {"queued": [film["board"]]}
    (task,) = _continuations(engine)
    registry, _model = director_says(studio, answer(verdicts_for(film), "ACCEPT"))
    no_redo(monkeypatch)
    published: list[list[str]] = []

    def publish(engine_, settings_, vault, registry_, passed):
        published.append(list(passed))
        return {"status": "COMPLETED", "reason": "publicat", "artefacts": {"published": passed}}

    monkeypatch.setattr(stages, "_publish_passed", publish)

    outcome = stages.continue_film(
        engine,
        settings,
        None,
        registry,
        film["board"],
        cause=str(task.payload["cause"]),
        correlation_id=task.id,
    )

    assert outcome["status"] == "COMPLETED", outcome
    assert published == [[film["asset"]]]
    assert "Directoarea l-a acceptat" in outcome["reason"]
    nothing_bought(engine)
    # Decided: the pass does not ask her again.
    with Session(engine) as session, session.begin():
        session.get(TaskQueueItem, task.id).status = "DONE"
    assert _pass(engine, settings) == {"queued": []}


# ------------------------------------------- her REPAIR on the real paid path (his rules)
#
# The film of `test_daily_run_stages` assembled for real from faked vendors (two scenes, the
# stills gate's and clip QC's takes, none of them his): QC is scripted to fail on the sound's
# peak and scene 2's stuttering clip. She repairs the sound and scene 2's motion; everything
# below `redo_scene` is the studio's own code (may_act, his paid-media rule, the lease, the
# limits, the books).

requires_ffmpeg = pytest.mark.skipif(
    __import__("app.media.qc", fromlist=["find_ffmpeg"]).find_ffmpeg() is None,
    reason="ffmpeg not installed",
)


def _context_of(prompt: str) -> dict[str, Any]:
    head = '<untrusted_source_evidence hash="director-qc">\n'
    start = prompt.index(head) + len(head)
    return json.loads(prompt[start : prompt.index("\n</untrusted_source_evidence>", start)])


def _she_repairs_scene_2(prompt: str) -> str:
    """Every finding REAL; the sound and scene 2's motion redone."""
    context = _context_of(prompt)
    verdicts = [
        {"finding": item["id"], "verdict": "REAL", "reason": "măsurat"}
        for item in context["findings"]
    ]
    repairs = [
        {"redo": "audio", "reason": "vârful sunetului"},
        {"scene_index": 2, "redo": "motion", "reason": "clipul se poticnește"},
    ]
    return answer(verdicts, "REPAIR", repairs, "Refac sunetul și mișcarea scenei 2.")


def _real_film(
    engine, settings, tmp_path, monkeypatch, director=_she_repairs_scene_2
) -> tuple[str, str, dict, ProviderRegistry]:
    from test_daily_run_stages import _assembled_staircase_film

    storyboard_id, asset_id, world = _assembled_staircase_film(
        engine, settings, tmp_path, monkeypatch
    )
    with Session(engine) as session, session.begin():
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
        provider_id = session.scalar(select(Agent.provider_id))
    registry = ProviderRegistry()
    registry.register(provider_id, ScriptedModel(director))
    return storyboard_id, asset_id, world, registry


def _she_redoes_the_still_of_scene_2(prompt: str) -> str:
    """Every finding REAL; scene 2's picture redone (its motion follows it)."""
    context = _context_of(prompt)
    verdicts = [
        {"finding": item["id"], "verdict": "REAL", "reason": "măsurat"}
        for item in context["findings"]
    ]
    repairs = [{"scene_index": 2, "redo": "still", "reason": "imaginea nu este una singură"}]
    return answer(verdicts, "REPAIR", repairs, "Refac imaginea scenei 2.")


@requires_ffmpeg
def test_her_repair_buys_only_her_scene_under_his_rule_and_the_film_is_measured_again(
    engine, settings, tmp_path, monkeypatch
):
    from app.runbook import stages
    from test_daily_run_stages import _approvals, _provider_costs, _scripted_qc

    storyboard_id, asset_id, world, registry = _real_film(engine, settings, tmp_path, monkeypatch)
    posts_before = world["models"].posts()
    looked = _scripted_qc(monkeypatch, ["FAILED", "PASSED"])

    outcome = stages._edit_and_qc(engine, registry, settings, vault=None)

    # The sound remastered for 0 credits, scene 2's motion bought once under his MODE rule,
    # and the film that came of both measured once more and passed.
    assert looked[0] == asset_id and len(looked) == 2 and looked[1] != asset_id
    assert world["models"].posts() == posts_before + 1
    assert outcome["artefacts"]["passed_assets"] == [looked[1]]
    assert outcome["artefacts"]["decisions"][0]["outcome"] == "REPAIRED"
    (repair,) = events(engine, "runbook.qc_repair")
    assert [item["redo"] for item in repair.payload["applied"]] == ["audio"]
    assert [(i["redo"], i["scene_index"]) for i in repair.payload["bought"]] == [("motion", 2)]
    redo_costs = [
        cost
        for cost in _provider_costs(engine)
        if (cost.attribution_json or {}).get("step") == "motion_redo"
    ]
    assert len(redo_costs) == 1
    assert _approvals(engine) == []
    (letter,) = letters(engine, LETTER_KIND)
    assert letter.intent == "STATUS" and letter.body_json["storyboard_id"] == storyboard_id
    assert "a trecut controlul calității" in letter.body_text


@requires_ffmpeg
def test_under_every_paid_step_her_repair_is_asked_and_his_yes_carries_it_out(
    engine, settings, tmp_path, monkeypatch
):
    from app.runbook import stages
    from test_daily_run_stages import _answer, _approvals, _scripted_qc

    storyboard_id, _asset_id, world, registry = _real_film(engine, settings, tmp_path, monkeypatch)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).paid_media_approval = "EVERY_PAID_STEP"
    posts_before = world["models"].posts()
    looked = _scripted_qc(monkeypatch, ["FAILED", "FAILED", "PASSED"])

    stages._edit_and_qc(engine, registry, settings, vault=None)

    # Nothing bought without his yes: the redo is his question; the free sound fix was made.
    assert world["models"].posts() == posts_before
    (question,) = _approvals(engine)
    assert question.action == "media.scene_redo" and question.result == "PENDING"
    assert question.subject == storyboard_id
    asked = [e for e in events(engine, DECISION_EVENT) if e.payload["outcome"] == "ASKED"]
    assert asked, [e.payload["outcome"] for e in events(engine, DECISION_EVENT)]
    assert any("așteaptă răspunsul tău" in m.body_text for m in letters(engine, LETTER_KIND))

    # His yes continues the film: her REPAIR is carried out again (she is not asked twice),
    # the yes is spent on that redo, the film rejoined and measured once more.
    from app.models import ApprovalRequest as Approval

    _answer(engine, question.id, "APPROVED", note="Da, reface scena 2.")
    outcome = stages.continue_film(
        engine, settings, None, registry, storyboard_id, cause="x", correlation_id="c"
    )

    assert world["models"].posts() == posts_before + 1, outcome
    assert looked[-1] in outcome["passed_assets"]
    with Session(engine) as session:
        assert session.get(Approval, question.id).consumed_at is not None


@requires_ffmpeg
def test_when_his_limits_are_spent_nothing_is_bought_and_the_film_waits_for_her(
    engine, settings, tmp_path, monkeypatch
):
    from app.runbook import stages
    from test_daily_run_stages import _approvals, _scripted_qc

    _storyboard_id, _asset_id, world, registry = _real_film(engine, settings, tmp_path, monkeypatch)
    settings.film_max_paid_redos = 0
    posts_before = world["models"].posts()
    _scripted_qc(monkeypatch, ["FAILED", "FAILED"])

    stages._edit_and_qc(engine, registry, settings, vault=None)

    assert world["models"].posts() == posts_before
    assert _approvals(engine) == []
    decided = events(engine, DECISION_EVENT)
    limited = [e for e in decided if (e.payload.get("done") or {}).get("limited")]
    assert limited, [e.payload for e in decided]


@requires_ffmpeg
def test_her_still_repair_on_the_real_path_waits_for_his_look_and_then_gets_its_motion(
    engine, settings, tmp_path, monkeypatch
):
    """The review's real-path case (MODE rule): her new still for scene 2 is bought and the
    stills gate leaves its pictures to his look. Before: NOTHING_DONE, no letter to him, and
    the scene's paid round spent, so after his look the motion was refused by the limits and
    the video vendor was never called. Now: BOUGHT_WAITING with his letter; his look approving
    a new picture queues the film; the walk buys only the motion (one round), rejoins the film
    and measures it once more."""
    from app.economy.models import ProviderCostRecord
    from app.media.assembler import decide_take
    from app.runbook import stages
    from test_daily_run_stages import _approvals, _provider_costs, _scripted_qc

    storyboard_id, asset_id, world, registry = _real_film(
        engine, settings, tmp_path, monkeypatch, director=_she_redoes_the_still_of_scene_2
    )
    posts_before = world["models"].posts()
    looked = _scripted_qc(monkeypatch, ["FAILED", "PASSED"])
    began = utc_now()

    first = stages._edit_and_qc(engine, registry, settings, vault=None)

    (decision,) = first["artefacts"]["decisions"]
    report_id = decision["report_id"]
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["outcome"] == "BOUGHT_WAITING", decided.payload["done"]
    assert [(i["redo"], i["scene_index"]) for i in decided.payload["done"]["bought"]] == [
        ("still", 2)
    ]
    assert world["models"].posts() == posts_before
    assert _approvals(engine) == []
    (letter,) = letters(engine, LETTER_KIND)
    assert "Refăcut și cumpărat" in letter.body_text and "scena 2" in letter.body_text
    assert letters(engine, INBOX_KIND) == []
    assert decision_state(engine, report_id)["pending"] is True

    # His look on the sheet approves one of the new pictures (the gate could not look at them:
    # no employee's model sees in this world, so they wait for him). The redo wrote them into
    # the rows of the stills they replace: found by the moment, not by a new id.
    with Session(engine) as session:
        new_still = session.scalars(
            select(SceneTake.id)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == 2,
                SceneTake.kind == "still",
                SceneTake.status.in_(("PAID", "REJECTED")),
                SceneTake.path.is_not(None),
                SceneTake.updated_at >= began,
            )
            .order_by(SceneTake.updated_at.desc())
        ).first()
    assert new_still is not None
    decide_take(engine, new_still, "APPROVED", decided_by="owner")
    assert decision_state(engine, report_id)["ready"] is True

    outcome = stages.continue_film(
        engine, settings, None, registry, storyboard_id, cause=f"take:{new_still}"
    )

    assert world["models"].posts() == posts_before + 1, outcome
    assert len(looked) == 2 and looked[1] != asset_id
    assert looked[1] in outcome["passed_assets"], outcome
    still_redos = [
        cost
        for cost in _provider_costs(engine)
        if (cost.attribution_json or {}).get("step") == "still_redo"
    ]
    assert len(still_redos) == 1  # the still was not bought again
    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, storyboard_id) == {2: 1}
        assert session.scalars(select(ProviderCostRecord)).all()
    assert decision_state(engine, report_id)["outcome"] == "REPAIRED"


@requires_ffmpeg
def test_on_the_real_path_his_local_move_scene_gets_its_new_still_and_no_paid_motion(
    engine, settings, tmp_path, monkeypatch
):
    """babcf272's scene 5 on the real path: the Owner chose LOCAL_MOVE for scene 2. Her new
    still is bought, his look approves it, and the film is rejoined from its takes with the new
    still animated locally: the video vendor is never called (before, the repair planned a paid
    motion there on an auto-selected model)."""
    from app.media.assembler import decide_take
    from app.media.production_policy import LOCAL_MOVE
    from app.media.shooting_sheet import set_scene_model
    from app.runbook import stages

    storyboard_id, asset_id, world, registry = _real_film(
        engine, settings, tmp_path, monkeypatch, director=_she_redoes_the_still_of_scene_2
    )
    from test_daily_run_stages import _scripted_qc

    set_scene_model(engine, storyboard_id, 2, LOCAL_MOVE, issued_by="owner")
    posts_before = world["models"].posts()
    looked = _scripted_qc(monkeypatch, ["FAILED", "PASSED"])
    began = utc_now()

    stages._edit_and_qc(engine, registry, settings, vault=None)

    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["outcome"] == "BOUGHT_WAITING", decided.payload["done"]
    with Session(engine) as session:
        new_still = session.scalars(
            select(SceneTake.id)
            .where(
                SceneTake.storyboard_id == storyboard_id,
                SceneTake.scene_number == 2,
                SceneTake.kind == "still",
                SceneTake.status.in_(("PAID", "REJECTED")),
                SceneTake.path.is_not(None),
                SceneTake.updated_at >= began,
            )
            .order_by(SceneTake.updated_at.desc())
        ).first()
    assert new_still is not None
    decide_take(engine, new_still, "APPROVED", decided_by="owner")

    outcome = stages.continue_film(
        engine, settings, None, registry, storyboard_id, cause=f"take:{new_still}"
    )

    assert world["models"].posts() == posts_before, outcome  # no paid motion
    assert len(looked) == 2 and looked[1] != asset_id, outcome
    assert looked[1] in outcome["passed_assets"], outcome
    (repair,) = [
        e.payload for e in events(engine, "runbook.qc_repair") if e.payload.get("new_asset")
    ]
    assert [item["redo"] for item in repair["applied"]] == ["rejoin"]
    assert repair["bought"] == []


def test_a_report_of_weeks_ago_is_not_woken_up(engine, settings, studio):
    """The pass looks back `LOOKBACK_DAYS`: a film that failed long ago is not put before her
    to be published or bought for."""
    from datetime import UTC, datetime, timedelta

    film = failed_film(engine)
    _production(engine)
    with Session(engine) as session, session.begin():
        session.get(QualityControlReport, film["report"]).verified_at = (
            datetime.now(UTC) - timedelta(days=30)
        ).isoformat()
    assert _pass(engine, settings) == {"queued": []}


# ------------------------------------------------------- 2026-10-10 review of this package


def _in(days: float = 0.0) -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(days=days)).isoformat()


def _his_look(engine, take_id: str, decision: str) -> None:
    """His look at a take on the sheet, as `assembler.decide_take` records it (the fixture's
    takes have no file on disk, which his real look requires)."""
    from app.media.assembler import TAKE_DECIDED_EVENT

    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, take_id)
        row.status = decision
        row.approved_by = "owner" if decision == "APPROVED" else None
        row.updated_at = utc_now()
        append_event(
            session,
            TAKE_DECIDED_EVENT,
            "scene_take",
            take_id,
            1,
            {
                "storyboard_id": row.storyboard_id,
                "scene_number": row.scene_number,
                "kind": row.kind,
                "decision": decision,
                "decided_by": "owner",
            },
            str(uuid4()),
        )


def _accepting(film: dict[str, Any]) -> str:
    """Her ACCEPT of the film as it is: the panels a flaw she lets through."""
    return answer(
        [
            {**verdict, "verdict": "ACCEPTED"} if verdict["verdict"] == "REAL" else verdict
            for verdict in verdicts_for(film)
        ],
        "ACCEPT",
    )


def test_a_still_bought_for_her_that_waits_for_his_look_is_told_and_carried_on_once_approved(
    engine, settings, studio, monkeypatch
):
    """The review's scene-5 case: her new still is bought and waits for his look on the sheet.
    It used to be recorded «nothing could be done» (no letter about the money, a note in her
    inbox saying nothing was done), and the scene's one paid round was spent, so the motion
    filmed from the still, once he approved it, was refused by the limits: bought, never in a
    film. Now he is told (BOUGHT_WAITING), the decision stands while the still waits, and once
    his look approves it the walk buys only the motion, in the still's round, without asking
    her again or buying the still twice."""
    from app.runbook import stages
    from app.workflows.passes import director_qc_review

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")
    _production(engine)
    monkeypatch.setattr(director_qc_review, "RETRY_MINUTES", 0)

    first = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert first["outcome"] == "BOUGHT_WAITING" and first["passed_asset"] is None
    assert redo.calls == [("still", 5, True)]
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["final"] is True
    assert decided.payload["bought_so_far"] == [["still", 5]]
    (waiting,) = decided.payload["done"]["waiting"]
    assert waiting["scene_index"] == 5 and waiting["kind"] == "still"
    # He is told what was bought; nothing waits in her inbox as if nothing had been done.
    (letter,) = letters(engine, LETTER_KIND)
    assert letter.body_json["outcome"] == "BOUGHT_WAITING"
    assert "imaginea nouă este cumpărată" in letter.body_text
    assert letters(engine, INBOX_KIND) == []
    state = decision_state(engine, film["report"])
    assert state["final"] and state["pending"] and not state["ready"]
    assert _pass(engine, settings) == {"queued": []}  # it waits for his look, not for her
    again = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert again["outcome"] == "BOUGHT_WAITING" and redo.calls == [("still", 5, True)]

    # His look approves the new still: the walk carries on her list (the motion only).
    (new_still,) = redo.new_stills
    _his_look(engine, new_still, "APPROVED")
    assert decision_state(engine, film["report"])["ready"] is True
    assert _pass(engine, settings) == {"queued": [film["board"]]}

    done = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("still", 5, True), ("motion", 5, True)]
    assert len(model.asked) == 1  # her decision was carried on, not asked again
    assert done["outcome"] == "REPAIRED" and done["passed_asset"]
    still_round, motion_round = (e.payload for e in events(engine, "runbook.qc_paid_redo"))
    assert still_round["open_motion"] is True
    assert motion_round["continues"] and motion_round["kinds"] == ["motion"]
    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, film["board"]) == {5: 1}
    assert len(letters(engine, LETTER_KIND)) == 2


def test_his_look_rejecting_what_was_bought_puts_the_report_before_her_again(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")
    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    (new_still,) = redo.new_stills

    _his_look(engine, new_still, "REJECTED")

    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"] and not state["pending"]


def test_a_repair_he_said_no_to_is_put_before_her_again(engine, settings, studio, monkeypatch):
    """The review: an ASKED decision stood «final» for ever, so after his no (or an expired
    question) the film was never reviewed, accepted or closed again. Now his no lapses it: the
    watchdog queues the film and she reads the report again, with his answer in front of her."""
    from app.media.assembler import SceneRedoRefused
    from app.runbook import stages
    from app.workflows.passes import director_qc_review

    film = failed_film(engine)
    approval_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRequest(
                id=approval_id,
                action="media.scene_redo",
                subject=film["board"],
                risk_tier="T2",
                requester="video_editor",
                cost_usd=6.0,
                expires_at=_in(days=1),
                result="PENDING",
                created_at=utc_now(),
            )
        )
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    said: list[str] = []

    def director(prompt: str) -> str:
        said.append(prompt)
        if len(said) == 1:
            return answer(verdicts_for(film), "REPAIR", repairs)
        return _accepting(film)

    registry, _model = director_says(studio, director)
    asked = SceneRedoRefused("NEEDS_APPROVAL", "Întrebarea ta", approval_id=approval_id)
    FakeRedoPath(engine, monkeypatch, refuse={("still", 5): asked})
    _production(engine)
    monkeypatch.setattr(director_qc_review, "RETRY_MINUTES", 0)

    first = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert first["outcome"] == "ASKED"
    state = decision_state(engine, film["report"])
    assert state["final"] and state["pending"] and not state["ready"]
    assert _pass(engine, settings) == {"queued": []}  # his question is open

    with Session(engine) as session, session.begin():
        row = session.get(ApprovalRequest, approval_id)
        row.result, row.note, row.decided_at = "REFUSED", "Nu, prea scump.", utc_now()
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"]
    assert _pass(engine, settings) == {"queued": [film["board"]]}

    second = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(said) == 2 and '"result": "REFUSED"' in said[1]
    assert second["outcome"] == "ACCEPTED" and second["passed_asset"] == film["asset"]


def test_an_expired_question_lapses_her_repair_too(engine, settings, studio):
    film = failed_film(engine)
    approval_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ApprovalRequest(
                id=approval_id,
                action="media.scene_redo",
                subject=film["board"],
                risk_tier="T2",
                requester="video_editor",
                expires_at=_in(days=-0.01),
                result="PENDING",
                created_at=utc_now(),
            )
        )
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            film["report"],
            1,
            {
                "report_id": film["report"],
                "storyboard_id": film["board"],
                "decision": "REPAIR",
                "outcome": "ASKED",
                "final": True,
                "done": {"asked": [{"approval_id": approval_id}]},
            },
            "c",
        )
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"]


def _incident_limits(engine, film, settings) -> None:
    """The film's two paid redos spent on rounds that delivered (scenes 1 and 2: each left a
    candidate with its file, which the gate turned down) and its free fix made. (babcf272's
    own morning rounds delivered nothing and spend nothing, `_morning`.) The limits are the
    ones the studio had then (one a scene, two a film); since 2026-10-11 they default to the
    most the settings allow, and money decides the rest."""
    from app.runbook import stages

    settings.film_max_paid_redos_per_scene = 1
    settings.film_max_paid_redos = 2

    began = utc_now()  # after the film's own takes
    with Session(engine) as session, session.begin():
        for scene in (1, 2):
            append_event(
                session,
                stages.QC_PAID_REDO_EVENT,
                "storyboard",
                film["board"],
                1,
                {"scene_index": scene, "of_asset": film["asset"], "started_at": began},
                "c",
            )
            session.get(
                SceneTake, _take(session, film["board"], scene, "still", None)
            ).status = "REJECTED"
        append_event(
            session,
            stages.QC_REPAIR_EVENT,
            "storyboard",
            film["board"],
            1,
            {"of_asset": film["asset"], "made": [], "new_asset": None},
            "c",
        )


def test_with_his_limits_spent_she_is_told_repair_is_not_possible_and_accepts(
    engine, settings, studio, monkeypatch
):
    """The review: with his limits spent a REPAIR validated, did nothing (``limited``), and was
    asked again every hour until the watchdog gave up, the film neither published nor closed.
    Now her prompt says REPAIR is not possible and why; she accepts the panels as they are."""
    from app.runbook import stages

    film = failed_film(engine)
    _incident_limits(engine, film, settings)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(
        studio,
        lambda prompt: (
            _accepting(film)
            if "REPAIR is not possible" in prompt
            else answer(verdicts_for(film), "REPAIR", repairs)
        ),
    )
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 1
    assert "no paid redo left" in model.asked[0]
    assert outcome["outcome"] == "ACCEPTED"
    assert not [
        e for e in events(engine, DECISION_EVENT) if (e.payload.get("done") or {}).get("limited")
    ]


def test_a_repair_that_cannot_be_carried_out_is_refused_and_never_churns(
    engine, settings, studio, monkeypatch
):
    """She insists on a REPAIR nothing of which can be done: the answer does not validate, she
    is asked once more, the film waits; no ``limited`` round, no NOTHING_DONE re-read."""
    from app.runbook import stages

    film = failed_film(engine)
    _incident_limits(engine, film, settings)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 2
    assert outcome["outcome"] == "WAITING"
    assert events(engine, DECISION_EVENT) == []
    assert len(events(engine, WAITING_EVENT)) == 1


def test_a_repair_with_one_redo_that_can_be_done_is_valid():
    from app.agents.reviews import DirectorRedo, repair_refusal

    his = {"still": ["his"], "motion": ["his"]}
    context = {
        "free_fix_already_used": True,
        "scenes": [
            {
                "scene_index": 1,
                "kind": "LIVE",
                "paid_redos_left": 1,
                "owner_approved_would_be_retired_by": his,
            },
            {
                "scene_index": 5,
                "kind": "LIVE",
                "paid_redos_left": 0,
                "owner_choice_on_sheet": "LOCAL_MOVE",
            },
            {
                "scene_index": 6,
                "kind": "LIVE",
                "paid_redos_left": 0,
                "motion_after_new_still": True,
            },
            {"scene_index": 7, "kind": "LIVE", "paid_redos_left": 1},
        ],
    }

    def redo(scene: int, kind: Any) -> DirectorRedo:
        return DirectorRedo(scene_index=scene, redo=kind, reason="x")

    assert "approved" in str(repair_refusal([redo(1, "still")], context))
    assert "LOCAL_MOVE" in str(repair_refusal([redo(5, "motion")], context))
    assert "no paid redo left" in str(repair_refusal([redo(5, "still")], context))
    audio = DirectorRedo(redo="audio", reason="x")
    assert "free fix" in str(repair_refusal([audio], context))
    assert repair_refusal([redo(6, "motion")], context) is None  # the still's round goes on
    assert repair_refusal([redo(1, "still"), redo(7, "still")], context) is None


def _walks(engine, film, count: int, minutes_ago: int) -> None:
    """Walks of the film that never reached her (refused by his mode), ``minutes_ago``."""
    from datetime import UTC, datetime, timedelta

    moment = (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()
    # The history is immutable: the walks are written at that moment, not moved there.
    with pytest.MonkeyPatch.context() as patch, Session(engine) as session, session.begin():
        patch.setattr("app.services.utc_now", lambda: moment)
        for _ in range(count):
            append_event(
                session,
                "runbook.film_continued",
                "storyboard",
                film["board"],
                1,
                {"status": "SKIPPED", "cause": f"director_qc:{film['report']}"},
                "c",
            )


def test_walks_that_never_reached_her_do_not_use_up_her_tries(
    engine, settings, studio, monkeypatch
):
    """The review: two dozen walks refused by his mode (or safe mode, or a busy film) counted
    as her tries, and the pass dropped the film for good with no note anywhere. Now only rounds
    that reached her count; refused walks are retried ever more slowly, never dropped."""
    from app.workflows.passes import director_qc_review

    film = failed_film(engine)
    _production(engine)
    _walks(engine, film, 24, minutes_ago=90)

    # 24 refused walks: the wait has grown to its ceiling (a day), but she was never asked.
    assert _pass(engine, settings) == {"queued": []}
    monkeypatch.setattr(director_qc_review, "MAX_WAIT_MINUTES", 60)
    assert _pass(engine, settings) == {"queued": [film["board"]]}


@pytest.mark.parametrize(("count", "queued"), [(1, True), (3, False)])
def test_the_wait_doubles_with_each_walk_that_never_reached_her(
    engine, settings, studio, count, queued
):
    """One refused walk 90 minutes ago: RETRY_MINUTES (60) passed. Three: four hours."""
    film = failed_film(engine)
    _production(engine)
    _walks(engine, film, count, minutes_ago=90)

    assert (_pass(engine, settings) == {"queued": [film["board"]]}) is queued


# ------------------------------------- babcf272 after the restart (2026-10-10, second review)
#
# The end-to-end review walked babcf272 as it stood after the restart, on fakes: the mechanical
# repair's two morning rounds (scenes 1 and 2) had bought nothing (every candidate REFUSED, the
# GPU forced off) and still spent the film's two paid redos, so her REPAIR of scene 5's panels
# was refused; a still redo whose candidates were all refused gave the panels back with a fresh
# ``updated_at``, and the walk rejoined the same film as «repaired with the new picture»; a
# refused rejoin of an approved new still fell to NOTHING_DONE, and she was told REPAIR was not
# possible; candidates the gate turned down waited for his look for ever.

REPAIR_5 = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]


def _morning(engine, film) -> None:
    """What the mechanical repair of 11:05 UTC left on babcf272: one paid round each for
    scenes 1 and 2 (the old payload, no ``started_at``) that delivered nothing, and its repair
    on the film (the free fix used)."""
    from app.runbook import stages

    corr = str(uuid4())
    with Session(engine) as session, session.begin():
        for scene in (1, 2):
            append_event(
                session,
                stages.QC_PAID_REDO_EVENT,
                "storyboard",
                film["board"],
                1,
                {"scene_index": scene, "of_asset": film["asset"]},
                corr,
            )
            refused = _take(session, film["board"], scene, "still", None)
            row = session.get(SceneTake, refused)
            row.status, row.path, row.sha256 = "REFUSED", None, None
        append_event(
            session,
            stages.QC_REPAIR_EVENT,
            "storyboard",
            film["board"],
            1,
            {"of_asset": film["asset"], "made": [], "new_asset": None},
            corr,
        )


def _scene(prompt: str, index: int) -> dict[str, Any]:
    return next(s for s in _context_of(prompt)["scenes"] if s["scene_index"] == index)


def test_morning_rounds_that_delivered_nothing_leave_her_repair_of_scene_5_possible(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    # The limits the studio had then (one a scene, two a film); since 2026-10-11 they
    # default to the most the settings allow.
    settings.film_max_paid_redos_per_scene = 1
    settings.film_max_paid_redos = 2
    film = failed_film(engine)
    _morning(engine, film)
    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, film["board"]) == {}
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert "REPAIR is not possible" not in model.asked[0]
    assert _scene(model.asked[0], 5)["paid_redos_left"] == 1
    assert redo.calls == [("still", 5, True), ("rejoin", None, False)]
    assert outcome["outcome"] == "REPAIRED" and outcome["passed_asset"]
    # Her round delivered (a new still with its file): it counts against his limits.
    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, film["board"]) == {5: 1}


@pytest.mark.parametrize(
    ("status", "with_file", "counted"),
    [
        ("REFUSED", False, False),
        ("LOST", False, False),
        ("REJECTED", False, False),
        ("SUBMITTED", False, True),  # still at the vendor: it may deliver
        ("PAID", True, True),
        ("REJECTED", True, True),  # turned down by the gate after it came
    ],
)
def test_a_paid_round_counts_only_when_it_delivered(engine, status, with_file, counted):
    from app.runbook import stages

    film = failed_film(engine)
    began = utc_now()  # after the film's own takes
    with Session(engine) as session, session.begin():
        append_event(
            session,
            stages.QC_PAID_REDO_EVENT,
            "storyboard",
            film["board"],
            1,
            {"scene_index": 5, "of_asset": film["asset"], "started_at": began},
            "c",
        )
        row = session.get(SceneTake, _take(session, film["board"], 5, "still", None))
        row.status = status
        if not with_file:
            row.path, row.sha256 = None, None

    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, film["board"]) == ({5: 1} if counted else {})


def test_a_candidate_written_into_the_replaced_stills_row_is_a_new_take(engine):
    """The staircase film's still redo wrote its candidate into the row of the still it
    replaced (the same file of the same words is one row): it is new since the round began,
    and its round delivered. Given back since, an older row is the old picture."""
    from app.media.assembler import TAKE_RESTORED_EVENT, record_take
    from app.media.director_qc import new_approved_take
    from app.runbook import stages

    film = failed_film(engine)
    panels = film["takes"][5]["still"]
    since = utc_now()  # after the film's own takes
    with Session(engine) as session, session.begin():
        append_event(
            session,
            stages.QC_PAID_REDO_EVENT,
            "storyboard",
            film["board"],
            1,
            {"scene_index": 5, "of_asset": film["asset"], "started_at": since},
            "c",
        )
        row = session.get(SceneTake, panels)
        same = {
            "prompt_hash": row.prompt_hash,
            "sha256": row.sha256,
            "model_id": row.model_id,
            "resolution": row.resolution,
        }
    with Session(engine) as session:
        assert new_approved_take(session, film["board"], 5, "still", since) is None
        assert stages._paid_redo_rounds(session, film["board"]) == {}

    written = record_take(
        engine,
        storyboard_id=film["board"],
        scene_number=5,
        kind="still",
        status="PAID",
        correlation_id="c",
        **same,
    )
    assert written == panels
    with Session(engine) as session, session.begin():
        session.get(SceneTake, panels).status = "APPROVED"  # the gate chose it

    with Session(engine) as session:
        assert new_approved_take(session, film["board"], 5, "still", since) == panels
        assert stages._paid_redo_rounds(session, film["board"]) == {5: 1}

    with Session(engine) as session, session.begin():
        append_event(
            session,
            TAKE_RESTORED_EVENT,
            "scene_take",
            panels,
            1,
            {"storyboard_id": film["board"], "scene_number": 5, "kind": "still"},
            "c",
        )
    with Session(engine) as session:
        # A row that existed before and was given back since is the old picture.
        assert new_approved_take(session, film["board"], 5, "still", since) is None


def _panels_on_disk(engine, film, tmp_path) -> str:
    """Scene 5's three-panel still with its file on disk, so a redo can give it back."""
    import hashlib

    panels = film["takes"][5]["still"]
    data = b"three stacked panels"
    path = tmp_path / "panels.png"
    path.write_bytes(data)
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, panels)
        row.path = str(path)
        row.sha256 = hashlib.sha256(data).hexdigest()
    return panels


def _gpu_forced_off(redo: FakeRedoPath, panels: str, *, raise_after: bool):
    """The still redo of scene 5 with the GPU forced off: the panels retired, the one
    candidate REFUSED, the panels given back by the redo itself (`give_back_retired_takes`),
    then the redo returns (bought, nothing delivered) or refuses."""
    from app.media.assembler import (
        REDO_FAILURE_CODE,
        SceneRedoRefused,
        _event_mark,
        _retire_takes,
        give_back_retired_takes,
    )

    def run(engine_, storyboard_id, correlation_id, *, kind, scene_index=None, **kwargs):
        redo.calls.append((kind, scene_index, bool(kwargs.get("unasked"))))
        mark = _event_mark(engine_)
        with Session(engine_) as session, session.begin():
            _retire_takes(
                session, [panels], REDO_FAILURE_CODE, "redo", correlation_id, redo_kind="still"
            )
            now = utc_now()
            session.add(
                SceneTake(
                    id=str(uuid4()),
                    storyboard_id=storyboard_id,
                    scene_number=5,
                    kind="still",
                    prompt_hash=uuid4().hex,
                    model_id="seedream5_pro",
                    resolution="1080:1920",
                    status="REFUSED",
                    created_at=now,
                    updated_at=now,
                )
            )
        returned = give_back_retired_takes(
            engine_,
            storyboard_id,
            5,
            correlation_id=correlation_id,
            after_sequence=mark,
            cause="redo_delivered_nothing",
        )
        assert returned["restored"] == [panels], returned
        if raise_after:
            raise SceneRedoRefused("COMPUTE_NOT_READY", "GPU-ul a fost oprit.")
        return {"still": {"status": "REFUSED"}, "credits": 8, "given_back": returned}

    return run


@pytest.mark.parametrize("raise_after", [False, True])
def test_a_redo_that_gave_the_panels_back_never_rejoins_the_same_film(
    engine, settings, studio, monkeypatch, tmp_path, raise_after
):
    """Every candidate REFUSED (the GPU forced off): the panels come back with a fresh
    ``updated_at``. They are not the new still: no rejoin, no «repaired» film, and nothing
    waits (her decision is hers again at once)."""
    from app.media.director_qc import new_approved_take
    from app.runbook import stages

    film = failed_film(engine)
    panels = _panels_on_disk(engine, film, tmp_path)
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch, verdict="FAILED")
    began = utc_now()
    monkeypatch.setattr(
        "app.media.assembler.redo_scene", _gpu_forced_off(redo, panels, raise_after=raise_after)
    )

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert ("rejoin", None, False) not in redo.calls
    assert {kind for kind, _scene, _unasked in redo.calls} == {"still"}
    assert outcome["outcome"] != "REPAIRED" and outcome["passed_asset"] is None
    assert redo.measured == []
    with Session(engine) as session:
        assert session.get(SceneTake, panels).status == "APPROVED"  # given back as it was
        assert new_approved_take(session, film["board"], 5, "still", began) is None
        assert stages._paid_redo_rounds(session, film["board"]) == {}
    state = decision_state(engine, film["report"])
    assert not state["final"] and not state["pending"]


def test_a_refused_rejoin_keeps_her_decision_waiting_and_is_tried_again(
    engine, settings, studio, monkeypatch
):
    """Her new still for scene 5 (his LOCAL_MOVE) waits for his look, he approves it, and the
    film cannot be rejoined on the resumed walk: her decision keeps waiting (a ``rejoin``
    entry), she is not asked again and told REPAIR is not possible, the watchdog tries again,
    and the next walk rejoins the film without buying the still twice."""
    from app.runbook import stages
    from app.workflows.passes import director_qc_review

    film = failed_film(engine)
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")
    _production(engine)
    monkeypatch.setattr(director_qc_review, "RETRY_MINUTES", 0)

    first = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert first["outcome"] == "BOUGHT_WAITING"
    (new_still,) = redo.new_stills
    _his_look(engine, new_still, "APPROVED")
    assert decision_state(engine, film["report"])["ready"] is True

    def refused(engine_, settings_, vault, storyboard_id, result, correlation, **kwargs):
        redo.calls.append(("rejoin-refused", None, False))
        result["refused"].append(
            {"what": "reasamblarea filmului", "reason": "Filmul este ocupat de alt cumpărător"}
        )

    monkeypatch.setattr(stages, "_reencode_from_takes", refused)
    second = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert second["outcome"] == "BOUGHT_WAITING" and second["passed_asset"] is None
    outcomes = [e.payload["outcome"] for e in events(engine, DECISION_EVENT)]
    assert outcomes == ["BOUGHT_WAITING", "BOUGHT_WAITING"]
    newest = events(engine, DECISION_EVENT)[-1].payload
    (waiting,) = newest["waiting_so_far"]
    assert waiting["scene_index"] == 5 and waiting["kind"] == "rejoin"
    assert "ocupat" in waiting["next_ro"]
    assert len(model.asked) == 1
    assert letters(engine, INBOX_KIND) == []
    state = decision_state(engine, film["report"])
    assert state["final"] and state["pending"] and state["ready"]
    assert _pass(engine, settings) == {"queued": [film["board"]]}

    monkeypatch.setattr(stages, "_reencode_from_takes", redo.rejoin)
    third = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert third["outcome"] == "REPAIRED" and third["passed_asset"]
    assert redo.calls == [
        ("still", 5, True),
        ("rejoin-refused", None, False),
        ("rejoin", None, False),
    ]
    assert len(model.asked) == 1
    # His letters: the purchase, then the repaired film; the retry wrote none of its own.
    assert [m.body_json["outcome"] for m in letters(engine, LETTER_KIND)] == [
        "BOUGHT_WAITING",
        "REPAIRED",
    ]


def test_a_film_not_rejoined_for_days_is_hers_again(engine, settings, studio, monkeypatch):
    from app.media.director_qc import BOUGHT_WAIT_DAYS
    from app.runbook import stages

    film = failed_film(engine)
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch)

    def refused(engine_, settings_, vault, storyboard_id, result, correlation, **kwargs):
        redo.calls.append(("rejoin-refused", None, False))
        result["refused"].append({"what": "reasamblarea filmului", "reason": "ocupat"})

    monkeypatch.setattr(stages, "_reencode_from_takes", refused)
    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    assert decision_state(engine, film["report"])["ready"] is True

    monkeypatch.setattr("app.media.director_qc.utc_now", lambda: _in(days=BOUGHT_WAIT_DAYS + 1))
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"]


def test_an_approved_take_bought_for_her_and_in_no_film_is_something_she_can_still_do(
    engine, settings, studio, monkeypatch
):
    """Before the fix a refused rejoin left NOTHING_DONE: she was asked again with scene 5's
    one paid redo spent (its still delivered), was told REPAIR was not possible, and accepted
    the panels while the approved new still sat in no film. Her context now names that take,
    a REPAIR of scene 5 is valid, and it joins the take into the film without buying again."""
    from app.agents.reviews import DirectorRedo, repair_refusal
    from app.runbook import stages

    # The limits the studio had then (one a scene, two a film); since 2026-10-11 they
    # default to the most the settings allow.
    settings.film_max_paid_redos_per_scene = 1
    settings.film_max_paid_redos = 2
    film = failed_film(engine)
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch, still_status="PAID")
    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )
    (new_still,) = redo.new_stills
    _his_look(engine, new_still, "APPROVED")
    with Session(engine) as session, session.begin():
        # What the walk before this fix wrote after the refused rejoin.
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            film["report"],
            1,
            {
                "report_id": film["report"],
                "storyboard_id": film["board"],
                "decision": "REPAIR",
                "outcome": "NOTHING_DONE",
                "final": False,
            },
            "c",
        )

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    asked = model.asked[-1]
    scene_5 = _scene(asked, 5)
    assert scene_5["paid_redos_left"] == 0
    assert scene_5["approved_new_take_not_in_film"] == [new_still]
    assert "REPAIR is not possible" not in asked
    assert (
        repair_refusal(
            [DirectorRedo(scene_index=5, redo="still", reason="x")], {"scenes": [scene_5]}
        )
        is None
    )
    assert outcome["outcome"] == "REPAIRED" and outcome["passed_asset"]
    assert redo.calls == [("still", 5, True), ("rejoin", None, False)]  # not bought twice


def test_candidates_the_gate_turned_down_wait_for_her_look_then_the_film_is_hers_again(
    engine, settings, studio, monkeypatch, tmp_path
):
    """Her new still came with its file and the gate turned it down: it waits for her own look
    (it used to wait for his, «Decide Proprietarul»: the Owner, the same evening, wants her to
    decide), for `BOUGHT_WAIT_DAYS`; never looked at (nobody's model sees), the report is hers
    again (it used to wait for ever). Her look itself: tests/test_director_looks_at_pictures.py."""
    from app.media.director_qc import BOUGHT_WAIT_DAYS
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", REPAIR_5))
    redo = FakeRedoPath(engine, monkeypatch, still_status="REJECTED")

    first = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert first["outcome"] == "BOUGHT_WAITING"
    (refused,) = redo.new_stills
    state = decision_state(engine, film["report"])
    # No file on disk: nothing to look at, nothing waits for anybody.
    assert state["lapsed"] and not state["look"]
    picture = tmp_path / "refused.png"
    picture.write_bytes(b"refused still")
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, refused)
        row.path = str(picture)
    state = decision_state(engine, film["report"])
    assert state["final"] and state["pending"] and state["look"] and not state["ready"]

    monkeypatch.setattr("app.media.director_qc.utc_now", lambda: _in(days=BOUGHT_WAIT_DAYS + 1))
    state = decision_state(engine, film["report"])
    assert state["lapsed"] and not state["final"] and not state["pending"]


def test_a_motion_redo_the_step_held_is_a_refusal_in_its_words_never_a_purchase(
    engine, settings, studio, monkeypatch
):
    """2026-10-12, the cyclotron (aa170155): the motion step held the Director's redo of scenes
    4 and 5 NEEDS_OWNER (an unpriced RunPod profile) and bought nothing, yet the walk told the
    Owner «s-a cumpărat (1 refacere cumpărată); preluarea nouă așteaptă aprobarea» five times
    through the night. A redo that bought nothing is a refusal, in the step's own words."""
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 5, "redo": "motion", "reason": "the glow replaced the drawing"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch, motion_unbought={5})

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    # Nothing of her list could be bought: she reads the report once more, knowing why, and
    # the second round is refused the same way (one re-read, by design).
    assert redo.calls == [("motion", 5, True), ("motion", 5, True)]
    assert outcome["outcome"] == "NOTHING_DONE"
    for decided in events(engine, DECISION_EVENT):
        done = decided.payload["done"]
        assert done["bought"] == []
        (refused,) = [item for item in done["refused"] if item["scene_index"] == 5]
        assert refused["redo"] == "motion" and refused["status"] == "NEEDS_OWNER"
        assert "Profilul RunPod selectat" in refused["reason"]
    assert events(engine, "runbook.qc_paid_redo") == []
    for letter in letters(engine, LETTER_KIND):
        assert "refacere cumpărată" not in letter.body_text


def test_a_motion_rewrite_that_changed_nothing_turns_the_redo_to_the_picture(engine, monkeypatch):
    """2026-10-12, the cyclotron's scene 5: every hour the Director's brief rewrote the movement
    and the Video Editor's words came back the same, so the paid redo was refused
    PROMPT_NOT_CORRECTED and asked again the next hour. A movement that cannot be said
    differently on a picture that stays is the picture's turn (MOTION_REWRITES_BEFORE_STILL):
    the redo then buys the new still and its motion."""
    from app.media import scene_rewrite
    from app.runbook import stages

    asked: list[tuple[str, list[str]]] = []

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        asked.append((layer, list(reasons)))
        if layer == "motion":
            return {
                "rewritten": False,
                "rewritable": True,
                "same_prompt": True,
                "reason": "Rescrierea a dat același prompt; nimic nou de cumpărat.",
            }
        return {"rewritten": True, "rewritable": True, "layer": "still", "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    kinds = ["motion"]

    refusal = stages._correct_before_redo(
        engine, None, "board-1", 5, kinds, [], {"findings": []}, "c-1"
    )

    assert refusal is None
    assert kinds == ["still", "motion"], kinds
    assert [layer for layer, _ in asked] == ["motion", "still"]
    assert stages.SAME_PROMPT_NOTE in asked[1][1]


def test_a_picture_that_cannot_be_rewritten_either_keeps_the_refusal(engine, monkeypatch):
    from app.media import scene_rewrite
    from app.runbook import stages

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        if layer == "motion":
            return {"rewritten": False, "rewritable": True, "same_prompt": True, "reason": "la fel"}
        # His approved still: not the studio's to rewrite.
        return {"rewritten": False, "rewritable": False, "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    kinds = ["motion"]

    refusal = stages._correct_before_redo(
        engine, None, "board-1", 5, kinds, [], {"findings": []}, "c-2"
    )

    assert refusal is not None and refusal["status"] == stages.PROMPT_NOT_CORRECTED
    assert "la fel" in refusal["reason"] and kinds == ["motion"]
