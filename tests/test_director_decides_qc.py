"""Offline regression tests for test director decides qc.

Providers are faked; all data is synthetic."""

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


#: Her lesson for the panels (2026-10-12): a general rule, positive, no title, no scene.
PANELS_LESSON = "Ask for one continuous photograph that fills the frame from edge to edge."


def verdicts_for(film: dict[str, Any], real: set[int] | None = None) -> list[dict[str, Any]]:
    """Her verdicts on every finding: the captions FALSE, the tunnel his choice, the panels
    REAL (and any finding id in ``real`` REAL), serious, with their cause and lesson."""
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
        entry: dict[str, Any] = {"finding": number, "verdict": verdict, "reason": why}
        if verdict == "REAL":
            entry.update(
                severity="serious",
                cause="the still prompt listed three moments, so the model drew three panels",
                lesson=PANELS_LESSON,
            )
        out.append(entry)
    return out


#: What `answer` gives a REAL or ACCEPTED verdict a test wrote without them (2026-10-12: the
#: severity, the cause and the lesson are required): REAL is serious, ACCEPTED minor.
DEFAULT_CAUSE = "the prompt left the subject unnamed"
DEFAULT_LESSON = "Name the visible subject first in every still prompt."


def answer(verdicts, decision: str, repairs=None, summary: str = "Am citit raportul.") -> str:
    """Her answer as JSON. A REAL or ACCEPTED verdict without a severity, a cause or a lesson
    gets the defaults above, so the many scripted answers written before 2026-10-12 still say
    what they said; a test of those rules writes its verdicts itself."""
    filled = []
    for verdict in verdicts:
        item = dict(verdict)
        if item.get("verdict") in ("REAL", "ACCEPTED"):
            item.setdefault("severity", "serious" if item["verdict"] == "REAL" else "minor")
            item.setdefault("cause", DEFAULT_CAUSE)
            item.setdefault("lesson", DEFAULT_LESSON)
        filled.append(item)
    return json.dumps(
        {"verdicts": filled, "decision": decision, "repairs": repairs or [], "summary": summary}
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
        new_takes: bool = False,
        checks: dict[str, Any] | None = None,
    ):
        from app.runbook import stages

        self.engine = engine
        #: The film a redo makes is cut from the new still it bought (``new_takes``), and its QC
        #: report records ``checks`` (round 3 of the 2026-10-12 review: a lesson is confirmed
        #: only by a scene with other takes that the same check passes).
        self.new_takes = new_takes
        self.checks = dict(checks or {})
        self.still_of: dict[int, str] = {}
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
            self.still_of[int(scene_index)] = take_id
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
            production = dict(made.production_json) if made is not None else {}
            if self.new_takes:
                production["scenes"] = [
                    {**entry, "still_take": {"take_id": self.still_of[entry["scene_index"]]}}
                    if entry.get("scene_index") in self.still_of
                    else entry
                    for entry in production.get("scenes") or []
                ]
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
                    production_json=production,
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
                    checks_json=dict(self.checks),
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
    """Her ACCEPT of the film as it is: the panels a minor flaw she lets through. (Since
    2026-10-12 a serious defect is never ACCEPTED; the fixture's panels are her own reading,
    not words quality control measured as serious, so she may call them minor.)"""
    return answer(
        [
            {**verdict, "verdict": "ACCEPTED", "severity": "minor"}
            if verdict["verdict"] == "REAL"
            else verdict
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
        # The film in hand is what its free fix made (the sound remastered): the same fix on it
        # would only make it again (`stages._made_by_free_fix`).
        append_event(
            session,
            stages.QC_REPAIR_EVENT,
            "storyboard",
            film["board"],
            1,
            {
                "of_asset": "the-cut-before-its-free-fix",
                "applied": [{"redo": "audio", "reason": "vârful sunetului"}],
                "made": [film["asset"]],
                "new_asset": film["asset"],
            },
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


def test_an_empty_round_is_not_delivered_by_the_next_rounds_still(engine):
    """1c038a99, scene 5 (2026-10-12): five rounds counted, his cap of five fallen — but two
    rounds were stopped by a restart before anything was asked and one was cancelled after a
    second; read without a window, the fourth round's still «delivered» each of them, since it
    came after they began. Each round is read inside its own window: the empty one counts
    for nothing and opens nothing, the one that made the still counts once."""
    import time

    from app.runbook import stages

    film = failed_film(engine)
    first = utc_now()
    with Session(engine) as session, session.begin():
        empty = append_event(
            session,
            stages.QC_PAID_REDO_EVENT,
            "storyboard",
            film["board"],
            1,
            {
                "scene_index": 5,
                "of_asset": film["asset"],
                "started_at": first,
                "open_motion": True,
            },
            "c1",
        )
        empty_id = str(empty.event_id)
    time.sleep(0.01)
    second = utc_now()
    with Session(engine) as session, session.begin():
        made = append_event(
            session,
            stages.QC_PAID_REDO_EVENT,
            "storyboard",
            film["board"],
            1,
            {
                "scene_index": 5,
                "of_asset": film["asset"],
                "started_at": second,
                "open_motion": True,
            },
            "c2",
        )
        made_id = str(made.event_id)
        _take(session, film["board"], 5, "still", None)  # the fourth round's still, approved

    with Session(engine) as session:
        assert stages._paid_redo_rounds(session, film["board"]) == {5: 1}
        assert stages._open_still_rounds(session, film["board"]) == {5: made_id}
        assert stages._round_delivered(session, film["board"], 5, first, second) is False
        assert stages._round_delivered(session, film["board"], 5, second, None) is True
    assert empty_id != made_id


def test_a_motion_with_the_same_words_is_bought_from_a_new_still_without_turning_to_the_picture(
    engine,
):
    """The cyclotron's scenes 4 and 5 (2026-10-12): their stills approved the day before and
    never animated were retired by the «same prompt» escalation and bought again (269 credits)
    while the Director had written «alătur imaginile aprobate, nu cumpăr nimic». A scene whose
    approved still is not the failed film's has a new picture already: the motion's unchanged
    words are right, and nothing turns to the picture."""
    import time

    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    with Session(engine) as session:
        # The film's own still is the approved one: the picture stays, the escalation stands.
        assert stages._still_newer_than_film(session, film["board"], 5, film["asset"]) is False
        # Scene 3's clip was made after its still: the still is the film's picture.
        assert stages._still_newer_than_film(session, film["board"], 3, film["asset"]) is False
    with Session(engine) as session, session.begin():
        _take(session, film["board"], 5, "still", None)  # a new still, approved, in no film
    with Session(engine) as session:
        assert stages._still_newer_than_film(session, film["board"], 5, film["asset"]) is True
        # A scene the film has no still for, with no approved still either: nothing new.
        assert stages._still_newer_than_film(session, film["board"], 9, film["asset"]) is False

    # 1c038a99, scene 5 (2026-10-12, 16:29): the render record still named the original still
    # while the clip in the film was made from the still the gate approved later — read by the
    # record, that still was «new» and its clip was bought a third time. The picture a film
    # shows is read by time against its clip, whatever the record's ``still_take`` says.
    with Session(engine) as session, session.begin():
        job = session.scalar(select(VideoRenderJob).where(VideoRenderJob.id == film["job"]))
        production = dict(job.production_json)
        for entry in production["scenes"]:
            if entry["scene_index"] == 3:
                stale = {"take_id": str(uuid4()), "status": "APPROVED", "reused": True}
                entry["still_take"] = stale
        job.production_json = production
    with Session(engine) as session:
        assert stages._still_newer_than_film(session, film["board"], 3, film["asset"]) is False
    time.sleep(0.01)
    with Session(engine) as session, session.begin():
        _take(session, film["board"], 3, "still", None)  # approved after the film's clip
    with Session(engine) as session:
        assert stages._still_newer_than_film(session, film["board"], 3, film["asset"]) is True


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
    """2026-10-12, the cyclotron (00000160): the motion step held the Director's redo of scenes
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


# --------------------------------------------- small defects, their causes and their lessons
#
# 2026-10-12, 16:50, the Owner stopped the studio: 19.50 USD of RunPod that day, 11.05 on redos,
# and all three films (f06808c9, 1c038a99, 00000160) still failing QC. «DIRECTOAREA ACCEPTĂ
# DEFECTELE MICI! DAR TREBUIE SĂ ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE
# ASIGURE CĂ NU MAI SUNT!» and «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost
# aprobată».


def _decision(**verdict: Any) -> dict[str, Any]:
    return {
        "verdicts": [{"finding": 1, "verdict": "REAL", "reason": "a stray mark", **verdict}],
        "decision": "REPAIR",
        "repairs": [{"scene_index": 2, "redo": "still", "reason": "the stray mark"}],
        "summary": "Refac imaginea scenei 2.",
    }


def test_a_minor_defect_is_accepted_never_real_and_every_defect_says_why():
    from app.agents.reviews import DirectorQcDecision, decision_schema
    from pydantic import ValidationError

    why = {"cause": "the prompt asked for a busy desk", "lesson": "Keep the desk to two objects."}
    with pytest.raises(ValidationError, match="a minor defect is ACCEPTED"):
        DirectorQcDecision.model_validate(_decision(severity="minor", **why))
    with pytest.raises(ValidationError, match="names its severity"):
        DirectorQcDecision.model_validate(_decision(**why))
    # Without her reading of the report every REAL or ACCEPTED finding writes its lesson; with
    # it, only one a picture or motion prompt can act on (`reviews.prompt_actionable`).
    with pytest.raises(ValidationError, match="lesson"):
        decision_schema({1}, {2}).model_validate(_decision(severity="serious", cause=why["cause"]))
    with pytest.raises(ValidationError, match="cause"):
        DirectorQcDecision.model_validate(_decision(severity="serious", lesson=why["lesson"]))
    decided = DirectorQcDecision.model_validate(_decision(severity=" Serious", **why))
    assert decided.verdicts[0].severity == "serious"
    assert decided.verdicts[0].lesson == why["lesson"]

    # Nothing REAL is nothing to redo: the film is ACCEPTed, not repaired.
    accepted = {
        **_decision(severity="minor", **why),
        "verdicts": [
            {"finding": 1, "verdict": "ACCEPTED", "reason": "small", "severity": "minor", **why}
        ],
    }
    with pytest.raises(ValidationError, match="none REAL"):
        DirectorQcDecision.model_validate(accepted)
    DirectorQcDecision.model_validate({**accepted, "decision": "ACCEPT", "repairs": []})
    # A serious defect is never ACCEPTED (the review of 2026-10-12: «ACCEPTED, serious» was
    # published silently).
    serious = {
        **accepted,
        "decision": "ACCEPT",
        "repairs": [],
        "verdicts": [{**accepted["verdicts"][0], "severity": "serious"}],
    }
    with pytest.raises(ValidationError, match="a serious defect is never ACCEPTED"):
        DirectorQcDecision.model_validate(serious)
    # A minor defect may be REAL for a free fix (audio, encode, card), never for a still.
    DirectorQcDecision.model_validate(
        {**_decision(severity="minor", **why), "repairs": [{"redo": "audio", "reason": "x"}]}
    )
    # A finding the control misread, or his choice, needs none of it.
    DirectorQcDecision.model_validate(
        {
            "verdicts": [{"finding": 1, "verdict": "FALSE", "reason": "our own subtitles"}],
            "decision": "ACCEPT",
            "repairs": [],
            "summary": "Publicăm.",
        }
    )


def _minor_verdicts(film: dict[str, Any]) -> list[dict[str, Any]]:
    """The captions FALSE; the tunnel a small light drift she accepts, with its cause and lesson."""
    out = []
    for number, text in enumerate(film["failures"], start=1):
        if CAPTIONS in text:
            out.append({"finding": number, "verdict": "FALSE", "reason": "our own subtitles"})
        else:
            out.append(
                {
                    "finding": number,
                    "verdict": "ACCEPTED",
                    "reason": "the tunnel is a little lighter than the bible's void",
                    "severity": "minor",
                    "cause": "the prompt named a tunnel light before the void",
                    "lesson": "Name the background as near-black before any light source.",
                }
            )
    return out


#: A later film's span look that passed every scene.
SPANS_PASSED = {
    "picture_spans_qc": {
        "passed": True,
        "status": "MEASURED",
        "scenes": [
            {"scene_index": index, "status": "PASSED", "passed": True} for index in range(1, 6)
        ],
    }
}


class LessonDesk:
    """`prompt_agent`'s shared lesson contract (2026-10-12: `record_prompt_lesson` with a source,
    a scope and a provisional flag, `confirm_prompt_lessons`, `prompt_lessons`), faked: what is
    asserted here is what the Director's decision hands it and when, not how it stores."""

    def __init__(self, monkeypatch, *, refuse: tuple[str, ...] = ()):
        self.rows: list[dict[str, Any]] = []
        self.confirmed: list[list[str]] = []
        self.withdrawn: list[tuple[list[str], str]] = []
        self.refuse = refuse
        monkeypatch.setattr("app.media.prompt_agent.record_prompt_lesson", self.record)
        monkeypatch.setattr(
            "app.media.prompt_agent.confirm_prompt_lessons", self.confirm, raising=False
        )
        monkeypatch.setattr(
            "app.media.prompt_agent.withdraw_prompt_lessons", self.withdraw, raising=False
        )
        monkeypatch.setattr("app.media.prompt_agent.prompt_lessons", self.lessons)

    def record(self, session, lesson, *, source_id=None, scope="all", provisional=False):
        text = " ".join(str(lesson or "").split())
        if not text or any(word in text for word in self.refuse):
            return False
        self.rows.append(
            {"lesson": text, "source_id": source_id, "scope": scope, "provisional": provisional}
        )
        return True

    def confirm(self, session, source_ids):
        ids = list(source_ids)
        self.confirmed.append(ids)
        changed = [row for row in self.rows if row["source_id"] in ids and row["provisional"]]
        for row in changed:
            row["provisional"] = False
        return len(changed)

    def withdraw(self, session, source_ids, reason):
        ids = list(source_ids)
        self.withdrawn.append((ids, reason))
        gone = [row for row in self.rows if row["source_id"] in ids and row["provisional"]]
        self.rows = [row for row in self.rows if row not in gone]
        return len(gone)

    def lessons(self, session=None, limit=12, *, scope=None):
        return [
            row["lesson"] + (" (unverified)" if row["provisional"] else "")
            for row in reversed(self.rows)
        ][:limit]


def test_a_film_whose_defects_are_all_minor_is_accepted_and_nothing_is_bought(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    LessonDesk(monkeypatch)
    film = failed_film(engine, panels=False)
    registry, model = director_says(studio, answer(_minor_verdicts(film), "ACCEPT"))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "ACCEPTED" and outcome["passed_asset"] == film["asset"]
    nothing_bought(engine)
    # She was told what minor and serious are, and that a minor defect is accepted.
    assert "A minor defect is ACCEPTED" in model.asked[-1]
    assert "A serious defect is never ACCEPTED" in model.asked[-1]
    assert "background figures a bit larger than asked" in model.asked[-1]
    (decided,) = events(engine, DECISION_EVENT)
    tunnel = [item for item in decided.payload["verdicts"] if TUNNEL in str(item["text"])]
    assert tunnel and all(item["severity"] == "minor" for item in tunnel)
    assert all(item["cause"] and item["lesson"] for item in tunnel)
    (letter,) = letters(engine, LETTER_KIND)
    assert "defect mic" in letter.body_text


def test_her_lessons_go_to_the_shared_desk_once_scoped_and_provisional(
    engine, settings, studio, monkeypatch
):
    """The review of 2026-10-12: her lessons were compared by a word overlap of their own and
    stored for every film alike. Now each goes through `prompt_agent.record_prompt_lesson` once,
    with the run of her decision as its source, the film's kind as its scope, provisional; only
    a lesson a prompt can act on is handed over, and what the desk refuses is not counted."""
    from app.media.director_qc import DIRECTOR, learn_from_decision, lesson_source
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    film = failed_film(engine, panels=False)
    registry, _model = director_says(studio, answer(_minor_verdicts(film), "ACCEPT"))
    no_redo(monkeypatch)

    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    lesson = "Name the background as near-black before any light source."
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["lessons_recorded"] == [lesson]
    assert decided.payload["film_kind"] == "factual"
    # Two tunnel findings taught the same lesson: handed over once, never again when her
    # decision's event was written. Each lesson has its own source, made from her run (round 3
    # of the review: withdrawn or confirmed alone), as long as a run id.
    source = lesson_source(decided.payload["run_id"], 1)
    assert len(source) == 36 and source != lesson_source(decided.payload["run_id"], 2)
    assert decided.payload["lesson_sources"] == {lesson: source}
    assert desk.rows == [
        {
            "lesson": lesson,
            "source_id": source,
            "scope": "factual",
            "provisional": True,
        }
    ]

    payload = {
        "decided_by": DIRECTOR,
        "resumed": False,
        "run_id": "run-1",
        "film_kind": "serial",
        "verdicts": [
            {"verdict": "REAL", "check": "picture_spans_qc", "scene_index": 3,
             "lesson": "Keep the ledger page blank."},
            # The same rule from another scene: handed over once.
            {"verdict": "REAL", "check": "picture_qc", "scene_index": 4,
             "lesson": "Keep the ledger page blank."},
            # His choice teaches nothing.
            {"verdict": "OWNER_CHOICE", "check": "picture_qc", "scene_index": 2,
             "lesson": "Use warm amber light on brass."},
            # The sound, and a whole check's «a picat», are not a rule for a picture.
            {"verdict": "ACCEPTED", "check": "audio_mix_qc", "lesson": "Keep the music low."},
            {"verdict": "REAL", "check": "picture_qc", "check_level": True,
             "lesson": "Look harder at every frame."},
            # A picture already settled for its check (her reading said so).
            {"verdict": "ACCEPTED", "check": "picture_qc", "scene_index": 5, "teaches": False,
             "lesson": "Keep the desk lamp off."},
            {"verdict": "ACCEPTED", "check": "picture_qc", "scene_index": 1,
             "lesson": "Show people only from behind, small in frame."},
        ],
    }  # fmt: skip
    with Session(engine) as session, session.begin():
        assert learn_from_decision(session, payload) == [
            "Keep the ledger page blank.",
            "Show people only from behind, small in frame.",
        ]
    assert [row["scope"] for row in desk.rows[-2:]] == ["serial", "serial"]
    assert [row["source_id"] for row in desk.rows[-2:]] == [
        lesson_source("run-1", 1),
        lesson_source("run-1", 2),
    ]
    with Session(engine) as session, session.begin():
        # What the desk refuses (a lesson naming a scene) is not counted as learned.
        desk.refuse = ("scene 3",)
        named = {
            **payload,
            "verdicts": [
                {"verdict": "REAL", "check": "picture_qc", "scene_index": 3,
                 "lesson": "Keep scene 3 dark."}
            ],
        }  # fmt: skip
        assert learn_from_decision(session, named) == []
        # A decision carried on, or his card that publishes a film, teaches nothing.
        assert learn_from_decision(session, {**payload, "resumed": True}) == []
        assert learn_from_decision(session, {**payload, "decided_by": "owner"}) == []


def test_her_lesson_is_kept_before_her_repair_rewrites_or_buys_anything(
    engine, settings, studio, monkeypatch
):
    """The rewrite of the scenes her REPAIR redoes reads `prompt_lessons`: her lesson about the
    panels is there before the first step of the repair, and named in her decision's event; the
    film her repair made passed scene 5, so the lesson is confirmed (2026-10-12 review)."""
    from app.media.director_qc import lesson_source
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    # The film her repair made is cut from the new still of scene 5, and its span look passed
    # every scene.
    redo = FakeRedoPath(engine, monkeypatch, new_takes=True, checks=SPANS_PASSED)
    seen: list[list[str]] = []
    carry_out = stages._carry_out

    def carry_out_reading_lessons(engine_, *args, **kwargs):
        seen.append(desk.lessons())
        return carry_out(engine_, *args, **kwargs)

    monkeypatch.setattr(stages, "_carry_out", carry_out_reading_lessons)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "REPAIRED" and redo.calls[0] == ("still", 5, True)
    assert seen and f"{PANELS_LESSON} (unverified)" in seen[0]
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["lessons_recorded"] == [PANELS_LESSON]
    (panels,) = [item for item in decided.payload["verdicts"] if item["verdict"] == "REAL"]
    assert panels["severity"] == "serious" and "three moments" in panels["cause"]
    assert panels["teaches"] is True
    assert [row["lesson"] for row in desk.rows] == [PANELS_LESSON]
    # The new film, with a new still for the scene her lesson was about, passed it on the same
    # check: it worked.
    assert desk.confirmed == [[lesson_source(decided.payload["run_id"], 1)]]
    assert desk.rows[0]["provisional"] is False


def test_a_lesson_whose_scene_fails_again_is_not_confirmed(engine, settings, studio, monkeypatch):
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    FakeRedoPath(engine, monkeypatch, verdict="FAILED")  # the new film fails on «Scena 5: x»

    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert [row["lesson"] for row in desk.rows] == [PANELS_LESSON]
    assert desk.confirmed == [] and desk.rows[0]["provisional"] is True


def test_a_failure_storing_her_lessons_keeps_her_decision(engine, settings, studio, monkeypatch):
    """The review of 2026-10-12: a failure while storing her lessons discarded her validated
    decision, and the film waited for an answer she had already given."""
    from app.media import director_qc
    from app.runbook import stages

    def broken(*_args, **_kwargs):
        raise RuntimeError("the lesson store is down")

    monkeypatch.setattr("app.media.prompt_agent.record_prompt_lesson", broken)
    film = failed_film(engine, panels=False)
    registry, _model = director_says(studio, answer(_minor_verdicts(film), "ACCEPT"))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert outcome["outcome"] == "ACCEPTED" and outcome["passed_asset"] == film["asset"]
    (decided,) = events(engine, DECISION_EVENT)
    assert "lessons_recorded" not in decided.payload
    # Written without having been read first, the decision is not lost to its lessons either.
    payload = {
        **{k: v for k, v in decided.payload.items() if k != "lessons_recorded"},
        "report_id": film["report"],
        "outcome": "NOTHING_DONE",
    }
    assert director_qc.record_decision(engine, payload, str(uuid4()))
    assert len(events(engine, DECISION_EVENT)) == 2


def _earlier_passing_film(
    engine,
    film: dict[str, Any],
    passed: set[int],
    failed: set[int],
    checks: tuple[str, ...] = ("picture_qc", "picture_spans_qc"),
) -> str:
    """A film of the same storyboard cut from the same takes, measured before ``film``: its
    picture ``checks`` passed the scenes in ``passed`` and refused those in ``failed``, each
    entry recorded with the carry key it was measured with (`picture_qc.carry_keys`)."""
    from app.media.picture_qc import storyboard_carry_keys

    ids = {k: str(uuid4()) for k in ("asset", "job", "report")}
    scenes = sorted(passed | failed)
    with Session(engine) as session:
        made = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == film["asset"])
        ).one()
        production = dict(made.production_json)
        keys = {
            check: storyboard_carry_keys(session, film["board"], production, check)
            for check in ("picture_qc", "picture_spans_qc")
        }
    recorded = {
        "picture_qc": {
            "passed": not failed,
            "status": "MEASURED",
            "scenes": [
                {
                    "scene": index,
                    "status": "MEASURED",
                    "is_a_picture": True,
                    "one_picture": True,
                    "shows_the_scene": index in passed,
                    "reason": "as asked" if index in passed else "something else",
                    "carry_key": keys["picture_qc"].get(index),
                }
                for index in scenes
            ],
        },
        "picture_spans_qc": {
            "passed": not failed,
            "status": "MEASURED",
            "scenes": [
                {
                    "scene_index": index,
                    "status": "PASSED" if index in passed else "FAILED",
                    "passed": index in passed,
                    "carry_key": keys["picture_spans_qc"].get(index),
                }
                for index in scenes
            ],
        },
    }
    with Session(engine) as session, session.begin():
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
                provenance_hash="2" * 64,
                created_at="2000-01-01T00:00:00+00:00",
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=ids["job"],
                storyboard_id=film["board"],
                status="COMPLETED",
                output_asset_id=ids["asset"],
                started_at="2000-01-01T00:00:00+00:00",
                finished_at="2000-01-01T00:00:00+00:00",
                production_json=production,
            )
        )
        session.flush()
        session.add(
            QualityControlReport(
                id=ids["report"],
                media_asset_id=ids["asset"],
                status="FAILED" if failed else "PASSED",
                score=1.0,
                checks_json={name: recorded[name] for name in checks},
                failure_reasons_json=[],
                verified_at="2000-01-01T00:00:00+00:00",
            )
        )
    return ids["report"]


def _schema_of(context: dict[str, Any]):
    from app.agents.reviews import decision_schema

    return decision_schema(
        {item["id"] for item in context["findings"]},
        {scene["scene_index"] for scene in context["scenes"]},
        context,
    )


def test_a_scene_that_passed_before_with_the_same_takes_is_never_real_nor_redone(engine):
    """00000160, 2026-10-12: scene 1 (still 7a0be480, clip 843617b8) passed the film QCs of
    14:45 and 15:03 (10-11) and 08:15 UTC, failed the one of 10:35 UTC unchanged, and her REPAIR
    bought a new still and clip for it."""
    from app.agents.reviews import failed_render_reading
    from app.media.director_qc import film_qc_context
    from pydantic import ValidationError

    film = failed_film(engine, local_move=False)
    earlier = _earlier_passing_film(engine, film, passed={5}, failed={1})

    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))

    scenes = {scene["scene_index"]: scene for scene in context["scenes"]}
    assert scenes[5]["passed_before_unchanged"] is True
    assert scenes[5]["passed_before"]["picture_spans_qc"]["report_id"] == earlier
    assert "aceleași preluări" in scenes[5]["passed_before"]["picture_qc"]["note"]
    assert scenes[5]["failing_now"] == ["picture_spans_qc"]
    # Refused before (scene 1), or never looked at (2-4): judged on what this report says.
    assert [scenes[index]["passed_before_unchanged"] for index in (1, 2, 3, 4)] == [False] * 4
    assert "passed_before" not in scenes[1]

    schema = _schema_of(context)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    with pytest.raises(ValidationError, match="passed_before"):
        schema.model_validate_json(answer(verdicts_for(film), "REPAIR", repairs))
    # The same picture read differently is FALSE: no cause, no lesson to invent (the review of
    # 2026-10-12), and the film is published.
    calm = [
        {"finding": verdict["finding"], "verdict": "FALSE", "reason": "the same picture passed"}
        if verdict["verdict"] == "REAL"
        else verdict
        for verdict in verdicts_for(film)
    ]
    assert schema.model_validate_json(answer(calm, "ACCEPT")).decision == "ACCEPT"
    # Accepted as minor it needs no lesson either: there is nothing for a prompt to learn.
    minor = [
        {**verdict, "verdict": "ACCEPTED", "severity": "minor", "cause": "read differently"}
        if verdict["verdict"] == "REAL"
        else verdict
        for verdict in verdicts_for(film)
    ]
    for verdict in minor:
        verdict.pop("lesson", None)
    parsed = schema.model_validate(json.loads(answer(minor, "ACCEPT")) | {"verdicts": minor})
    assert parsed.decision == "ACCEPT"


def test_what_passed_before_is_settled_check_by_check(engine):
    """The review of 2026-10-12: «passed before» covered every check of the scene, and a
    finding no check claimed. A finding of the span look on a scene only the one-frame look
    passed is the span look's own, judged as any other; what she settled stays settled."""
    from app.agents.reviews import failed_render_reading
    from app.media.director_qc import film_qc_context
    from pydantic import ValidationError

    film = failed_film(engine, local_move=False)
    earlier = _earlier_passing_film(engine, film, {5}, set(), checks=("picture_qc",))
    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))

    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    assert set(scene["passed_before"]) == {"picture_qc"}
    assert scene["failing_now"] == ["picture_spans_qc"]
    assert scene["passed_before_unchanged"] is False
    panels = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    assert _schema_of(context).model_validate_json(answer(verdicts_for(film), "REPAIR", panels))

    # Her FALSE, or her minor ACCEPTED, on the span look's findings of this very picture: since
    # round 3 of the review her verdict carries the scene's carry key (the takes, the check's
    # version, the bible and look, the span and speed), and only that picture is settled by it.
    from app.media.picture_qc import storyboard_carry_keys

    with Session(engine) as session:
        production = (
            session.scalars(
                select(VideoRenderJob).where(VideoRenderJob.output_asset_id == film["asset"])
            )
            .one()
            .production_json
        )
        key = storyboard_carry_keys(session, film["board"], production, "picture_spans_qc")[5]

    def her_word(**extra: Any) -> None:
        with Session(engine) as session, session.begin():
            append_event(
                session,
                DECISION_EVENT,
                "quality_control_report",
                earlier,
                1,
                {
                    "report_id": earlier,
                    "storyboard_id": film["board"],
                    "decided_by": "Director",
                    "decision": "ACCEPT",
                    "run_id": str(uuid4()),
                    "verdicts": [
                        {
                            "finding": 1,
                            "verdict": "ACCEPTED",
                            "severity": "minor",
                            "check": "picture_spans_qc",
                            "scene_index": 5,
                            "reason": "a faint seam, accepted",
                            **extra,
                        }
                    ],
                },
                str(uuid4()),
            )

    # Recorded without the key (before round 3), or with another picture's: nothing settled.
    her_word()
    her_word(carry_key={**key, "speed": 1.5})
    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))
    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    assert "accepted_before" not in scene
    her_word(carry_key=key)
    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))
    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    assert scene["accepted_before"]["picture_spans_qc"]["verdicts"] == ["ACCEPTED"]
    assert scene["accepted_before_unchanged"] is True
    assert scene["passed_before_unchanged"] is True
    with pytest.raises(ValidationError, match="accepted_before"):
        _schema_of(context).model_validate_json(answer(verdicts_for(film), "REPAIR", panels))


def test_a_finding_no_check_claimed_is_never_settled():
    context = {
        "findings": [{"id": 1, "text": "Scena 5: odd", "check": None, "scene_index": 5}],
        "scenes": [
            {
                "scene_index": 5,
                "kind": "LIVE",
                "paid_redos_left": 1,
                "passed_before": {"picture_qc": {"report_id": "r"}},
                "failing_now": ["unattributed"],
                "passed_before_unchanged": False,
            }
        ],
    }
    decided = _schema_of(context).model_validate_json(
        answer(
            [{"finding": 1, "verdict": "REAL", "reason": "odd"}],
            "REPAIR",
            [{"scene_index": 5, "redo": "still", "reason": "odd"}],
        )
    )
    assert decided.repairs[0].scene_index == 5


def test_only_a_scene_a_real_finding_names_is_redone(engine):
    """00000160, 08:18 UTC: scenes 4 and 5 had passed that very report; her REPAIR of scene 3
    listed their stills too (to join takes bought for an earlier repair) and new motion was
    bought for both."""
    from app.agents.reviews import failed_render_reading
    from app.media.director_qc import film_qc_context
    from pydantic import ValidationError

    film = failed_film(engine, local_move=False)
    context = film_qc_context(
        engine,
        failed_render_reading(engine, film["report"]),
        limits={"per_scene": 2, "per_film": 4},
    )
    schema = _schema_of(context)
    panels = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    also_4 = panels + [{"scene_index": 4, "redo": "still", "reason": "join the new still"}]

    with pytest.raises(ValidationError, match=r"scenes \[4\] are named by no REAL finding"):
        schema.model_validate_json(answer(verdicts_for(film), "REPAIR", also_4))
    assert schema.model_validate_json(answer(verdicts_for(film), "REPAIR", panels)).repairs


# ------------------------------------------- the review of 2026-10-12, finding by finding
#
# The adversarial review of the four commits of 2026-10-12 confirmed what follows; each test
# names the defect it holds shut. Every model and provider is faked; nothing is bought.

#: Today's words of the checks (00000160 and 1c038a99, read on a copy of the studio's database).
YUNET = "Scena 4: YuNet a găsit fețe în cadrul first (1), deși biblia vizuală interzice fețele"
NO_SOUND = "The film has no audio stream"
CAVERN = (
    "Scena 5: privit la 1080 px: nu arată ce cere planul; încalcă biblia vizuală: The detector "
    "cavern in scenes 1, 4 and 5 is the same location with identical ring structure («a tower "
    "in a shaft, unlike scene 2»)"
)
FROZEN = "Motion QC: Scena 2, Scena 3: imagine fixă (fallback) fără alegerea Proprietarului."


def _context_of_words(*texts: str, scenes=(1, 2, 3, 4, 5), checks=None) -> dict[str, Any]:
    findings = report_findings({"failure_reasons_json": list(texts), "checks_json": checks or {}})
    return {
        "findings": findings,
        "scenes": [
            {"scene_index": index, "kind": "LIVE", "paid_redos_left": 1} for index in scenes
        ],
    }


def test_what_quality_control_measured_as_serious_is_never_accepted():
    """Finding 1: «ACCEPTED» (minor or serious) published a serious defect silently."""
    from pydantic import ValidationError

    context = _context_of_words(YUNET, NO_SOUND)
    first, second = context["findings"]
    assert first["measured_serious"] == "a face where the visual bible forbids faces"
    assert second["measured_serious"] == "no audio stream" and second["check"] == "audio_qc"
    schema = _schema_of(context)
    small = {"verdict": "ACCEPTED", "reason": "barely visible", "severity": "minor"}
    with pytest.raises(ValidationError, match="a serious defect is never ACCEPTED"):
        schema.model_validate_json(
            answer(
                [{"finding": 1, **small}, {"finding": 2, "verdict": "FALSE", "reason": "x"}],
                "ACCEPT",
            )
        )
    # REAL «minor» is serious all the same, and its still and the sound are redone.
    decided = schema.model_validate_json(
        answer(
            [
                {"finding": 1, "verdict": "REAL", "reason": "a face", "severity": "minor"},
                {"finding": 2, "verdict": "REAL", "reason": "silent", "severity": "minor"},
            ],
            "REPAIR",
            [{"scene_index": 4, "redo": "still", "reason": "a face"}, {"redo": "audio",
              "reason": "no sound"}],
        )
    )  # fmt: skip
    assert [verdict.severity for verdict in decided.verdicts] == ["serious", "serious"]
    # Quality control can misread a film: her FALSE stands.
    assert schema.model_validate_json(
        answer(
            [
                {"finding": 1, "verdict": "FALSE", "reason": "a statue's profile"},
                {"finding": 2, "verdict": "FALSE", "reason": "the probe failed"},
            ],
            "ACCEPT",
        )
    )


def test_with_his_limits_spent_a_serious_defect_goes_to_his_card_and_nothing_is_bought(
    engine, settings, studio, monkeypatch
):
    """Finding 1, the money side: a serious defect may not be ACCEPTED, and with his cap spent a
    REPAIR could not validate either — the film waited in her inbox and he heard nothing. Now
    her REPAIR is carried out to his cap: nothing bought, his card asks him, she is not asked
    again while it waits."""
    from app.decisions.models import OwnerDecision
    from app.decisions.producers.redo_cap import dedupe_key
    from app.runbook import stages

    film = failed_film(engine)
    _incident_limits(engine, film, settings)
    rounds_before = len(events(engine, "runbook.qc_paid_redo"))  # the two that spent his cap
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 1
    assert "REPAIR is not possible" in model.asked[0] and "REPAIR it anyway" in model.asked[0]
    assert redo.calls == [] and outcome["passed_asset"] is None
    assert outcome["outcome"] == "NOTHING_DONE"
    (decided,) = events(engine, DECISION_EVENT)
    assert decided.payload["done"]["limited"] and decided.payload["done"]["card_id"]
    with Session(engine) as session:
        card = session.scalar(
            select(OwnerDecision).where(OwnerDecision.dedupe_key == dedupe_key(film["board"]))
        )
        assert card is not None and card.status == "PENDING"
    assert len(events(engine, "runbook.qc_paid_redo")) == rounds_before


def test_a_repair_that_cannot_be_carried_out_is_refused_and_never_churns(
    engine, settings, studio, monkeypatch
):
    """She insists on a REPAIR nothing of which can be done (a paid motion for his LOCAL_MOVE
    scene): the answer does not validate, she is asked once more, the film waits; no round, no
    NOTHING_DONE re-read. (A REPAIR his cap alone stops goes to his card, above.)"""
    from app.runbook import stages

    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "motion", "reason": "animate the panels away"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 2
    assert outcome["outcome"] == "WAITING"
    assert events(engine, DECISION_EVENT) == []
    assert len(events(engine, WAITING_EVENT)) == 1


def test_controlul_a_picat_is_real_only_with_its_scenes():
    """Finding 2: on 2026-10-12 she marked «Controlul «picture_qc» a picat» REAL every time;
    it named no scene and bypassed the minor rule and the scene-naming rule."""
    from pydantic import ValidationError

    look = "Scene 5: the picture is not what the scene asked for — a tower in a shaft"
    checks = {
        "picture_qc": {
            "passed": False,
            "status": "MEASURED",
            "scenes": [{"scene": 5, "status": "MEASURED", "is_a_picture": True,
                        "one_picture": True, "shows_the_scene": False}],
        },
        "picture_spans_qc": {
            "passed": False,
            "scenes": [{"scene_index": 5, "passed": False, "status": "FAILED", "reason": "?"}],
        },
    }  # fmt: skip
    context = _context_of_words(look, scenes=(5,), checks=checks)
    own, whole = context["findings"]
    # The one-frame look's own words are its own (they were filed under the span look, or no
    # check, and «Controlul «picture_qc» a picat» was added beside them).
    assert own["check"] == "picture_qc" and own["scene_index"] == 5
    assert whole["text"] == "Controlul «picture_spans_qc» a picat"
    assert whole["check_level"] is True and whole["scenes_of_check"] == [5]
    schema = _schema_of(context)
    redo_5 = [{"scene_index": 5, "redo": "still", "reason": "a tower"}]
    with pytest.raises(ValidationError, match="only says that the check"):
        schema.model_validate_json(
            answer(
                [
                    {"finding": 1, "verdict": "FALSE", "reason": "it is the cavern"},
                    {"finding": 2, "verdict": "REAL", "reason": "the check failed"},
                ],
                "REPAIR",
                redo_5,
            )
        )
    assert schema.model_validate_json(
        answer(
            [
                {"finding": 1, "verdict": "REAL", "reason": "a tower"},
                {"finding": 2, "verdict": "REAL", "reason": "the same tower"},
            ],
            "REPAIR",
            redo_5,
        )
    )
    # Every REAL finding about no scene: only a free fix.
    alone = {
        "findings": [
            {"id": 1, "text": "Controlul «editorial_qc» a picat", "check": "editorial_qc",
             "scene_index": None, "check_level": True, "scenes_of_check": []}
        ],
        "scenes": [{"scene_index": 5, "kind": "LIVE", "paid_redos_left": 1}],
    }  # fmt: skip
    real = [{"finding": 1, "verdict": "REAL", "reason": "the cuts are off"}]
    with pytest.raises(ValidationError, match="no REAL finding is about a scene"):
        _schema_of(alone).model_validate_json(answer(real, "REPAIR", redo_5))
    assert _schema_of(alone).model_validate_json(
        answer(real, "REPAIR", [{"redo": "encode", "reason": "the cuts"}])
    )


def test_a_scene_is_named_by_its_index_or_scene_words_never_a_bare_digit():
    """Finding 3, on today's words: «cadrul first (1)» named scene 1, «Frames 1-2» scenes 1 and
    2, and the bible's rule quoted on scene 5 named scenes 1 and 4."""
    from app.agents.reviews import _names_scene, scenes_named

    yunet = {"scene_index": 4, "text": YUNET}
    assert _names_scene(yunet, 4) and not _names_scene(yunet, 1)
    assert scenes_named("Frames 1-2 are darker than the plan") == set()
    assert scenes_named(CAVERN, own=5) == {5}
    assert scenes_named(FROZEN, own=2) == {2, 3}
    assert scenes_named("Scenele 1, 2: imagine fixă") == {1, 2}
    assert scenes_named("scenes 1, 4 and 5 are frozen") == {1, 4, 5}
    assert scenes_named("scenele 2-4 au aceeași lampă") == {2, 3, 4}
    assert scenes_named("lumina scenei 4 e prea caldă") == {4}
    findings = report_findings({"failure_reasons_json": [YUNET, FROZEN, CAVERN], "checks_json": {}})
    assert [item["scenes"] for item in findings] == [[4], [2, 3], [5]]
    assert findings[1]["measured_serious"] == "a frozen or broken clip"
    assert findings[2]["measured_serious"] is None


def test_a_minor_defect_gets_its_free_fix_but_never_a_paid_redo():
    """Finding 13: REAL «minor» was refused even for a free fix."""
    from pydantic import ValidationError

    context = _context_of_words(MUSIC_LEVEL, "Scena 2: a small mark on the wall", "Scena 3: a face")
    schema = _schema_of(context)
    music = {"finding": 1, "verdict": "REAL", "reason": "too loud", "severity": "minor"}
    mark = {"finding": 2, "verdict": "ACCEPTED", "reason": "a mark", "severity": "minor"}
    face = {"finding": 3, "verdict": "FALSE", "reason": "a statue"}
    assert schema.model_validate_json(
        answer([music, mark, face], "REPAIR", [{"redo": "audio", "reason": "lower the music"}])
    )
    with pytest.raises(ValidationError, match="a minor defect is ACCEPTED"):
        schema.model_validate_json(
            answer(
                [music, {**mark, "verdict": "REAL"}, face],
                "REPAIR",
                [{"scene_index": 2, "redo": "still", "reason": "the mark"}],
            )
        )
    # With a serious defect elsewhere, a minor one still buys nothing for its own scene.
    with pytest.raises(ValidationError, match=r"scenes \[2\] are named by no REAL finding"):
        schema.model_validate_json(
            answer(
                [music, {**mark, "verdict": "REAL"}, {**face, "verdict": "REAL"}],
                "REPAIR",
                [
                    {"scene_index": 2, "redo": "still", "reason": "the mark"},
                    {"scene_index": 3, "redo": "still", "reason": "the face"},
                ],
            )
        )


def test_the_rewrite_before_a_redo_reads_why_her_defect_appeared(engine, monkeypatch):
    """Finding 8: her verdict's cause was read by nobody. The rewrite before the purchase now
    reads, for the scene, the REAL findings' words, «cauza: …» and her second look's words."""
    from app.media import scene_rewrite
    from app.runbook import stages

    asked: list[tuple[str, list[str]]] = []

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        asked.append((layer, list(reasons)))
        return {"rewritten": True, "rewritable": True, "layer": layer, "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    reading = {
        "verdicts": [
            {"verdict": "REAL", "text": "Scena 5: a tower, not the cavern", "scene_index": 5,
             "check": "picture_spans_qc", "cause": "the prompt named a shaft before the cavern"},
            {"verdict": "REAL", "text": "Scena 4: a face", "scene_index": 4,
             "cause": "a person at the desk"},
            {"verdict": "FALSE", "text": "Scena 5: apare text sau un logo", "scene_index": 5},
        ]
    }  # fmt: skip

    refusal = stages._correct_before_redo(
        engine,
        None,
        "board-1",
        5,
        ["still"],
        [],
        reading,
        "c-1",
        extra_reasons=["Directoarea a privit din nou scena: turnul e acolo."],
    )

    assert refusal is None
    ((layer, reasons),) = asked
    assert layer == "still"
    assert "Scena 5: a tower, not the cavern" in reasons
    assert "cauza: the prompt named a shaft before the cavern" in reasons
    assert not any("a person at the desk" in reason or "logo" in reason for reason in reasons)
    assert reasons[-1] == "Directoarea a privit din nou scena: turnul e acolo."


def test_a_motion_redo_the_motion_layer_cannot_treat_turns_to_the_picture(engine, monkeypatch):
    """Finding 9: a MOTION redo she picked for a finding about the picture could never be
    rewritten (every untreated finding was the picture's), and stayed PROMPT_NOT_CORRECTED."""
    from app.media import scene_rewrite
    from app.runbook import stages

    asked: list[tuple[str, list[str]]] = []

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        asked.append((layer, list(reasons)))
        if layer == "motion":
            return {"rewritten": False, "rewritable": True, "layer_exhausted": True,
                    "reason": "Cuvintele mișcării nu pot trata ce e în imagine."}  # fmt: skip
        return {"rewritten": True, "rewritable": True, "layer": "still", "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    kinds = ["motion"]

    refusal = stages._correct_before_redo(
        engine, None, "board-1", 5, kinds, [], {"findings": []}, "c-3"
    )

    assert refusal is None and kinds == ["still", "motion"]
    assert [layer for layer, _ in asked] == ["motion", "still"]
    assert stages.LAYER_EXHAUSTED_NOTE in asked[1][1]

    # A newer approved still already waits: the motion is bought from it as its words are.
    film = failed_film(engine, local_move=False)
    with Session(engine) as session, session.begin():
        _take(session, film["board"], 5, "still", None)
    asked.clear()
    kinds = ["motion"]
    reading = {"findings": [], "media_asset_id": film["asset"]}
    assert (
        stages._correct_before_redo(engine, None, film["board"], 5, kinds, [], reading, "c-4")
        is None
    )
    assert kinds == ["motion"] and [layer for layer, _ in asked] == ["motion"]


def _standing(film: dict[str, Any], repairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Her REPAIR as a decision from before 2026-10-12 recorded it (no severities), waiting on
    his answer, which has now come (`decision_state` ``ready``)."""
    return {
        "final": True,
        "pending": True,
        "ready": True,
        "look": False,
        "lapsed": False,
        "outcome": "ASKED",
        "tries": 1,
        "last_at": utc_now(),
        "decision": {
            "report_id": film["report"],
            "media_asset_id": film["asset"],
            "storyboard_id": film["board"],
            "decided_by": "Director",
            "run_id": "old-run",
            "decision": "REPAIR",
            "summary": "Refac scenele.",
            "verdicts": [
                {
                    "finding": number,
                    "text": text,
                    "check": "picture_spans_qc",
                    "scene_index": int(text.split(":")[0].split()[-1]),
                    "verdict": "REAL" if PANELS in text else "FALSE",
                    "reason": "x",
                }
                for number, text in enumerate(film["failures"], start=1)
            ],  # fmt: skip
            "repairs": repairs,
            "bought_so_far": [],
            "started_at": utc_now(),
            "outcome": "ASKED",
            "final": True,
        },
    }


def test_a_resumed_repair_is_carried_out_only_as_todays_rules_allow(
    engine, settings, studio, monkeypatch
):
    """Finding 14: a REPAIR decided before the rules of 2026-10-12, resumed after his answer,
    was carried out as it was. Its still of scene 4 (no REAL finding names it) is dropped and
    said; its still of scene 5 (the panels) is bought; she is not asked again."""
    from app.media import director_qc
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"},
        {"scene_index": 4, "redo": "still", "reason": "join the new still"},
    ]
    monkeypatch.setattr(director_qc, "decision_state", lambda *_a: _standing(film, repairs))
    registry, model = director_says(studio, lambda prompt: pytest.fail("she was asked again"))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert model.asked == []
    assert ("still", 5, True) in redo.calls and ("still", 4, True) not in redo.calls
    assert outcome["outcome"] == "REPAIRED"
    (decided,) = events(engine, DECISION_EVENT)
    (dropped,) = [item for item in decided.payload["done"]["skipped"] if item["scene_index"] == 4]
    assert dropped["status"] == director_qc.DROPPED_ON_RESUME
    assert "nicio constatare reală a unui defect serios" in dropped["reason"]


def test_a_resumed_repair_with_nothing_left_is_read_by_her_again(
    engine, settings, studio, monkeypatch
):
    from app.media import director_qc
    from app.runbook import stages

    film = failed_film(engine, local_move=False)
    repairs = [{"scene_index": 4, "redo": "still", "reason": "join the new still"}]
    monkeypatch.setattr(director_qc, "decision_state", lambda *_a: _standing(film, repairs))
    registry, model = director_says(studio, _accepting(film))
    no_redo(monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 1 and outcome["outcome"] == "ACCEPTED"


class SecondLook:
    """`media.second_look.second_look` (2026-10-12, the shared contract), faked with the
    answer it gives; the frames of the failed film are faked too (its file is not on disk)."""

    def __init__(self, monkeypatch, answer: dict[str, Any]):
        import sys
        import types

        self.answer = answer
        self.calls: list[dict[str, Any]] = []
        module = types.ModuleType("app.media.second_look")
        module.second_look = self  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "app.media.second_look", module)
        monkeypatch.setattr(
            "app.runbook.stages._failed_film_frames",
            lambda *_a, **_k: ["first.png", "middle.png", "last.png"],
        )

    def __call__(self, engine, registry, **kwargs):
        self.calls.append(kwargs)
        return dict(self.answer)


def test_her_second_look_overturning_the_refusal_buys_nothing(
    engine, settings, studio, monkeypatch
):
    """Finding 15, the Owner's rule: «LLM-ul este pe abonament! NU COSTĂ BANI»; «trece
    imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect». Before the
    paid still of scene 5 is bought she looks at the scene in the failed film: the defect is a
    minor one, so nothing is bought; and, her look having overturned the film's only REAL
    finding, her decision is ACCEPT in the same walk (the Owner, 2026-10-12 19:00: «trebuie să
    aibă și puterea de a trece de QC»): she is not asked again, and the film is published."""
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    look = SecondLook(
        monkeypatch,
        {"verdict": "OVERTURNED", "severity": "minor", "redo": False,
         "reason_ro": "Imaginea e o singură fotografie; banda e cerul nopții.",
         "run_id": "look-1"},
    )  # fmt: skip
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [], "nothing was bought for a refusal her look overturned"
    ((asked),) = look.calls
    assert asked["kind"] == "film_scene" and asked["scene_index"] == 5
    assert asked["images"] == ["first.png", "middle.png", "last.png"]
    assert any(PANELS in words for words in asked["refusal"])
    assert film["takes"][5]["still"] in asked["take_ids"]
    (decided,) = events(engine, DECISION_EVENT)
    (overturned,) = decided.payload["done"]["overturned"]
    assert overturned["scene_index"] == 5 and overturned["checks"] == ["picture_spans_qc"]
    assert "cerul nopții" in overturned["reason"]
    # The picture her look kept, by its carry key: only that picture is settled by it.
    assert overturned["carry_keys"]["picture_spans_qc"]["still"] == film["takes"][5]["still"]
    assert len(model.asked) == 1 and decided.payload["decision"] == "ACCEPT"
    assert decided.payload["accepted_by_second_look"] is True
    (panels,) = [item for item in decided.payload["verdicts"] if item.get("before_look")]
    assert panels["verdict"] == "ACCEPTED" and panels["severity"] == "minor"
    assert outcome["outcome"] == "ACCEPTED" and outcome["passed_asset"] == film["asset"]
    nothing_bought(engine)
    # A minor flaw keeps the lesson she wrote for it: its cause is still worth learning.
    assert desk.withdrawn == [] and [row["lesson"] for row in desk.rows] == [PANELS_LESSON]


def test_her_second_look_confirming_the_refusal_buys_with_her_words(
    engine, settings, studio, monkeypatch
):
    from app.media import scene_rewrite
    from app.runbook import stages

    SecondLook(
        monkeypatch,
        {"verdict": "CONFIRMED", "severity": "serious", "redo": True,
         "reason_ro": "Trei panouri, se reface.", "run_id": "look-2"},
    )  # fmt: skip
    asked: list[list[str]] = []

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        asked.append(list(reasons))
        return {"rewritten": True, "rewritable": True, "layer": layer, "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls[0] == ("still", 5, True) and outcome["outcome"] == "REPAIRED"
    (reasons,) = asked
    assert "Directoarea a privit din nou scena: Trei panouri, se reface." in reasons
    assert any(
        reason.startswith("cauza: the still prompt listed three moments") for reason in reasons
    )


def test_without_her_second_look_the_purchase_goes_on_as_before(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    SecondLook(
        monkeypatch,
        {"verdict": "UNAVAILABLE", "severity": "none", "redo": True, "reason_ro": "",
         "run_id": None},
    )  # fmt: skip
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls == [("still", 5, True), ("rejoin", None, False)]
    assert outcome["outcome"] == "REPAIRED"


# ------------------------------------------- round 3 of the 2026-10-12 review (FD3)
#
# The Owner, 2026-10-12: «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost
# aprobată sau este în regulă!»; at 19:00: «și după ce se uită Directoarea, trebuie să aibă și
# puterea de a trece de QC și merge mai departe cu publicarea». Every model is faked.

FACE = "Scena 5: YuNet a găsit fețe în cadrul middle (1), deși biblia vizuală interzice fețele"
LAMP = "Scena 4: the frame shows a desk lamp, not the detector"
SILENT = "The film has no audio stream"


def test_when_her_looks_overturn_every_real_finding_she_passes_the_film_and_it_is_published(
    engine, settings, studio, monkeypatch
):
    """Finding 0: her REPAIR of scenes 4 and 5; before each purchase she looks again, and the
    refusal is wrong at both (no defect at all). Her decision becomes ACCEPT in the same walk:
    a PASSED report by her decision with her looks as its evidence, the film's continuation
    goes on to publication, nothing is bought, no film QC round and no second reading."""
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    look = SecondLook(
        monkeypatch,
        {"verdict": "OVERTURNED", "severity": "none", "redo": False,
         "reason_ro": "Nu e niciun defect în imagine.", "run_id": "look-0"},
    )  # fmt: skip
    film = failed_film(engine, local_move=False, extra_failures=[LAMP])
    real = {number for number, text in enumerate(film["failures"], start=1) if text == LAMP}
    repairs = [
        {"scene_index": 4, "redo": "still", "reason": "a lamp, not the detector"},
        {"scene_index": 5, "redo": "still", "reason": "three stacked panels"},
    ]
    registry, model = director_says(studio, answer(verdicts_for(film, real), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)
    _production(engine)
    published: list[list[str]] = []

    def publish(engine_, settings_, vault, registry_, passed):
        published.append(list(passed))
        return {"status": "COMPLETED", "reason": "publicat", "artefacts": {"published": passed}}

    monkeypatch.setattr(stages, "_publish_passed", publish)

    outcome = stages.continue_film(
        engine, settings, None, registry, film["board"], cause=f"director_qc:{film['report']}"
    )

    assert outcome["status"] == "COMPLETED", outcome
    assert published == [[film["asset"]]]
    assert redo.calls == [] and redo.measured == [], "nothing bought, no film QC round"
    assert sorted(call["scene_index"] for call in look.calls) == [4, 5]
    assert len(model.asked) == 1, "she was not asked a second time"
    (decided,) = events(engine, DECISION_EVENT)
    payload = decided.payload
    assert payload["decision"] == "ACCEPT" and payload["outcome"] == "ACCEPTED"
    assert payload["decided_by"] == "Director" and payload["accepted_by_second_look"] is True
    assert [entry["scene_index"] for entry in payload["second_looks"]] == [4, 5]
    assert [item["scene_index"] for item in payload["repairs_before_look"]] == [4, 5]
    assert not [item for item in payload["verdicts"] if item["verdict"] == "REAL"]
    cleared = [item for item in payload["verdicts"] if item.get("before_look") == "REAL"]
    assert len(cleared) == 2 and {item["verdict"] for item in cleared} == {"FALSE"}
    with Session(engine) as session:
        passed = session.get(QualityControlReport, payload["passed_report_id"])
        assert passed.status == "PASSED" and passed.media_asset_id == film["asset"]
        check = passed.checks_json["director_qc"]
        assert check["decided_by"] == "Director" and len(check["second_looks"]) == 2
    nothing_bought(engine)
    # No defect at all: the lesson only those findings taught is withdrawn.
    ((sources, reason),) = desk.withdrawn
    assert sources == [payload["lesson_sources"][PANELS_LESSON]] and "nu s-a confirmat" in reason
    assert desk.rows == []
    # Decided: the pass does not ask her again.
    assert _pass(engine, settings) == {"queued": []}


def test_her_looks_pass_the_film_only_when_no_real_finding_stands():
    """Finding 0 and finding 1, as code: a measured serious defect is passed only by a look that
    finds no defect at all; a REAL finding about the sound, about a scene she did not look at,
    or a finding that is not hers keeps the film from passing."""
    from app.media.director_qc import accepted_by_looks

    decided = {
        "decision": "REPAIR",
        "summary": "Refac scena 5.",
        "repairs": [{"scene_index": 5, "redo": "still", "reason": "a face"}],
        "verdicts": [
            {"finding": 1, "verdict": "REAL", "text": FACE, "scene_index": 5, "scenes": [5],
             "measured_serious": "a face where the visual bible forbids faces",
             "severity": "serious", "reason": "a face"},
            {"finding": 2, "verdict": "FALSE", "text": f"Scena 1: {CAPTIONS}",
             "scene_index": 1, "scenes": [1], "reason": "our subtitles"},
        ],
    }  # fmt: skip
    minor = [{"scene_index": 5, "severity": "minor", "reason": "o față mică în fundal"}]
    none = [{"scene_index": 5, "severity": "none", "reason": "nu e nicio față, e o lampă"}]

    assert accepted_by_looks(decided, minor) is None
    passed = accepted_by_looks(decided, none)
    assert passed is not None and passed["decision"] == "ACCEPT" and passed["repairs"] == []
    face = passed["verdicts"][0]
    assert face["verdict"] == "FALSE" and face["before_look"] == "REAL"
    assert "nu e nicio față" in face["reason"]
    assert passed["done"] == {"overturned": none}
    assert "scena 5" in passed["summary"]

    def plus(verdict: dict[str, Any]) -> dict[str, Any]:
        return {**decided, "verdicts": [*decided["verdicts"], verdict]}

    sound = {"finding": 3, "verdict": "REAL", "text": SILENT, "scene_index": None, "scenes": []}
    rights = {"finding": 3, "verdict": "FALSE", "text": "Invalid license", "not_yours": True}
    other = {"finding": 3, "verdict": "REAL", "text": LAMP, "scene_index": 4, "scenes": [4]}
    for verdict in (sound, rights, other):
        assert accepted_by_looks(plus(verdict), none) is None
    assert accepted_by_looks({**decided, "decision": "ACCEPT"}, none) is None


def test_a_face_yunet_measured_is_redone_unless_her_look_finds_no_face_at_all(
    engine, settings, studio, monkeypatch
):
    """Finding 1: an overturn «minor» of a face YuNet counted on a faceless bible dropped the
    redo, and the face was published. Now only a look that finds no face at all drops it; a
    minor one buys under his caps, with her words, and records no overturn."""
    from app.media import scene_rewrite
    from app.runbook import stages
    from app.runbook.stages import _look_drops_redo

    assert _look_drops_redo({"verdict": "OVERTURNED", "severity": "minor"})
    assert not _look_drops_redo({"verdict": "OVERTURNED", "severity": "minor"}, measured=True)
    assert _look_drops_redo({"verdict": "OVERTURNED", "severity": "none"}, measured=True)
    assert not _look_drops_redo({"verdict": "CONFIRMED", "severity": "minor", "redo": False})

    SecondLook(
        monkeypatch,
        {"verdict": "OVERTURNED", "severity": "minor", "redo": False,
         "reason_ro": "O față mică, în fundal.", "run_id": "look-f"},
    )  # fmt: skip
    asked: list[list[str]] = []

    def fake_rewrite(engine_, registry, storyboard_id, scene, layer, reasons, correlation):
        asked.append(list(reasons))
        return {"rewritten": True, "rewritable": True, "layer": layer, "reason": ""}

    monkeypatch.setattr(scene_rewrite, "rewrite_for_redo", fake_rewrite)
    film = failed_film(engine, local_move=False, extra_failures=[FACE])
    real = {len(film["failures"])}
    repairs = [{"scene_index": 5, "redo": "still", "reason": "a face on a faceless bible"}]
    registry, _model = director_says(studio, answer(verdicts_for(film, real), "REPAIR", repairs))
    redo = FakeRedoPath(engine, monkeypatch)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert redo.calls[0] == ("still", 5, True) and outcome["outcome"] == "REPAIRED"
    (decided,) = events(engine, DECISION_EVENT)
    assert not decided.payload["done"].get("overturned")
    (reasons,) = asked
    assert any("se reface totuși" in reason for reason in reasons)


def test_what_yunet_or_the_band_measured_is_never_settled():
    """Finding 2: a settlement of the span look on the same picture covered YuNet and the flat
    band, so a face newly counted could only be called FALSE. What those free detectors measure
    is read again on every film and judged each time: REAL is allowed, a lesson is asked for,
    and the scene is not «passed before, unchanged»."""
    from app.agents.reviews import (
        decision_schema,
        measured_by_detector,
        passed_scene_refusal,
        prompt_actionable,
    )

    band = "Scena 5: nu e o singură fotografie: cadrul middle are o bandă plată pe toată lățimea"
    assert measured_by_detector(FACE) and measured_by_detector(band)
    assert not measured_by_detector(f"Scena 5: {CAPTIONS}")
    finding = {"id": 1, "text": FACE, "check": "picture_spans_qc", "scene_index": 5,
               "scenes": [5], "measured_serious": "a face", "detector": True}  # fmt: skip
    context = {
        "findings": [finding],
        "scenes": [
            {
                "scene_index": 5,
                "kind": "LIVE",
                "paid_redos_left": 1,
                "accepted_before": {"picture_spans_qc": {"report_id": "r"}},
                "failing_now": ["picture_spans_qc"],
                "passed_before_unchanged": False,
            }
        ],
    }
    assert prompt_actionable(finding, context)
    real = [{"finding": 1, "verdict": "REAL", "reason": "a face"}]
    repairs = [{"scene_index": 5, "redo": "still", "reason": "a face"}]
    parsed = decision_schema({1}, {5}, context).model_validate_json(answer(real, "REPAIR", repairs))
    assert parsed.decision == "REPAIR" and passed_scene_refusal(parsed, context) is None


def test_her_reading_keeps_the_carry_key_and_never_settles_a_detector(engine):
    """Finding 2, in her reading: each verdict carries the scene's carry key (its family's),
    and a scene whose finding now is YuNet's is never «passed before, unchanged»."""
    from app.agents.reviews import failed_render_reading
    from app.media.director_qc import annotate_verdicts, film_qc_context

    film = failed_film(engine, local_move=False, extra_failures=[FACE])
    _earlier_passing_film(engine, film, {5}, set())
    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))

    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    assert set(scene["passed_before"]) == {"picture_qc", "picture_spans_qc"}
    assert scene["passed_before_unchanged"] is False, "YuNet's face is judged, never settled"
    face = next(item for item in context["findings"] if item["text"] == FACE)
    assert face["detector"] is True
    (annotated,) = annotate_verdicts(
        [{"finding": face["id"], "verdict": "REAL", "reason": "a face", "severity": "serious",
          "cause": "a desk with a person", "lesson": DEFAULT_LESSON}],
        context,
    )  # fmt: skip
    family = "picture_spans_qc" if face["check"] == "picture_spans_qc" else "unattributed"
    assert annotated["carry_key"] == context["_settle_keys"][family][5]
    assert annotated["detector"] is True and annotated["teaches"] is True
    # The bookkeeping is never shown to her.
    from app.agents.reviews import _director_payload

    assert "_settle_keys" not in json.loads(_director_payload(context))


def test_no_audio_stream_after_every_free_fix_is_the_developers_never_a_card_to_him(
    engine, settings, studio, monkeypatch
):
    """Finding 7: «The film has no audio stream» is measured serious, never ACCEPTED; its only
    fix, the audio redo, is free. The Owner, 2026-10-12 22:50: «Dacă "decide Proprietarul"
    înseamnă că nu este o agenție autonomă!» — a free fix costs nothing, so it is made again,
    up to FREE_FIXES_PER_FILM times; when every free fix is made and the defect stays, her
    REPAIR validates, nothing is done, NO card reaches the Owner, and one note goes to the
    developer; she is not asked again about the same report."""
    from app.agents.director import DEVELOPER_DEFECT_KIND
    from app.agents.models import AgentMessage
    from app.agents.reviews import decision_schema
    from app.decisions.models import OwnerDecision
    from app.runbook import stages
    from app.runbook.stages import FREE_FIXES_PER_FILM, QC_REPAIR_EVENT
    from pydantic import ValidationError

    film = failed_film(engine, panels=False, extra_failures=[SILENT])
    with Session(engine) as session, session.begin():
        # The film already had every free fix it may have.
        for _round in range(FREE_FIXES_PER_FILM):
            append_event(
                session,
                QC_REPAIR_EVENT,
                "storyboard",
                film["board"],
                1,
                {
                    "of_asset": str(uuid4()),
                    "made": [film["asset"]],
                    "new_asset": film["asset"],
                    "applied": [{"what": "audio", "redo": "audio"}],
                },
                "c",
            )
    real = {len(film["failures"])}
    audio = [{"redo": "audio", "reason": "the film has no sound"}]
    registry, model = director_says(studio, answer(verdicts_for(film, real), "REPAIR", audio))
    no_redo(monkeypatch)
    _production(engine)

    outcome = stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert len(model.asked) == 1 and outcome["outcome"] == "NOTHING_DONE"
    (repair,) = outcome["repairs"]
    assert not repair.get("card_id") and repair["developer_note"]
    with Session(engine) as session:
        assert list(session.scalars(select(OwnerDecision))) == [] or all(
            card.kind != "free_fix_used" for card in session.scalars(select(OwnerDecision))
        ), "a quality stall never reaches the Owner"
        note = session.get(AgentMessage, repair["developer_note"])
        assert note.body_json["kind"] == DEVELOPER_DEFECT_KIND
        assert note.body_json["report_id"] == film["report"] and note.to_agent_id is not None
    nothing_bought(engine)
    assert _pass(engine, settings) == {"queued": []}, "she is not asked again on the same report"

    # A REPAIR nothing can carry out, on a defect not measured as serious: refused, and the
    # refusal no longer steers her to «decide ACCEPT».
    context = {
        "findings": [{"id": 1, "text": "Scena 1: o lumină caldă", "check": "picture_qc",
                      "scene_index": 1, "scenes": [1]}],
        "scenes": [{"scene_index": 1, "kind": "LIVE", "paid_redos_left": 0}],
        "free_fix_already_used": True,
    }  # fmt: skip
    with pytest.raises(ValidationError) as refused:
        decision_schema({1}, {1}, context).model_validate_json(
            answer([{"finding": 1, "verdict": "REAL", "reason": "x", "severity": "minor"}],
                   "REPAIR", [{"redo": "audio", "reason": "x"}])
        )  # fmt: skip
    assert "decide ACCEPT" not in str(refused.value)


def test_a_motion_qc_fallback_needs_no_invented_lesson():
    """Finding 8: a vendor that delivered no clip is no prompt's fault: a lesson was required
    for it, and so invented."""
    from app.agents.reviews import decision_schema, prompt_actionable, vendor_fallback
    from app.media.director_qc import teachable_lessons

    fallback = (
        "Motion QC: Scena 4: imagine fixă (fallback) fără alegerea Proprietarului. În PRODUCȚIE "
        "nicio scenă filmată nu rămâne imagine fixă"
    )
    finding = {"id": 1, "text": fallback, "check": "motion_qc", "scene_index": 4, "scenes": [4],
               "measured_serious": "a frozen or broken clip"}  # fmt: skip
    context = {
        "findings": [finding],
        "scenes": [{"scene_index": 4, "kind": "LIVE", "paid_redos_left": 1}],
    }
    assert vendor_fallback(finding) and not prompt_actionable(finding, context)
    verdict = {"finding": 1, "verdict": "REAL", "reason": "the vendor delivered no clip",
               "severity": "serious", "cause": "the vendor's job failed"}  # fmt: skip
    parsed = decision_schema({1}, {4}, context).model_validate_json(
        json.dumps(
            {
                "verdicts": [verdict],
                "decision": "REPAIR",
                "repairs": [{"scene_index": 4, "redo": "motion", "reason": "film the scene"}],
                "summary": "Refac mișcarea.",
            }
        )
    )
    assert parsed.verdicts[0].lesson == ""
    recorded = {**verdict, "check": "motion_qc", "scene_index": 4, "text": fallback,
                "lesson": "Ask the vendor again."}  # fmt: skip
    assert teachable_lessons({"verdicts": [recorded]}) == []


def test_a_lesson_is_not_confirmed_by_a_scene_nothing_changed_in(
    engine, settings, studio, monkeypatch
):
    """Finding 6: her lessons were confirmed by scenes that never changed (the same still,
    passed again, proves nothing about the words)."""
    from app.runbook import stages

    desk = LessonDesk(monkeypatch)
    film = failed_film(engine)
    repairs = [{"scene_index": 5, "redo": "still", "reason": "three stacked panels"}]
    registry, _model = director_says(studio, answer(verdicts_for(film), "REPAIR", repairs))
    # The new film passed every scene on the span look, cut from the old takes.
    FakeRedoPath(engine, monkeypatch, checks=SPANS_PASSED)

    stages.director_decides_failed_film(
        engine, settings, None, registry, film["report"], film["asset"]
    )

    assert [row["lesson"] for row in desk.rows] == [PANELS_LESSON]
    assert desk.confirmed == [] and desk.rows[0]["provisional"] is True


def test_her_reading_shows_the_small_traces_accepted_and_her_earlier_overturns(engine):
    """Finding 10: the small traces a look accepted on a take (and her look that approved it)
    were not in her reading, and came back as findings after the money; finding 4: her earlier
    second looks were not shown either."""
    from app.agents.reviews import _DIRECTOR_QC_INSTRUCTIONS, failed_render_reading
    from app.media import fix_check
    from app.media.director_qc import film_qc_context

    film = failed_film(engine)
    with Session(engine) as session, session.begin():
        fix_check.record_take_note(
            session,
            storyboard_id=film["board"],
            scene_number=5,
            take_id=str(film["takes"][5]["still"]),
            kind="still",
            approved_by="director_look",
            minor=[{"finding": "a thin seam at the top", "seen": "a faint line"}],
            look={"verdict": "OVERTURNED", "severity": "minor", "redo": False,
                  "reason_ro": "Un rând subțire, nu panouri.", "run_id": "look-x"},
            correlation_id="c",
        )  # fmt: skip
        append_event(
            session,
            DECISION_EVENT,
            "quality_control_report",
            film["report"],
            1,
            {
                "report_id": film["report"],
                "storyboard_id": film["board"],
                "decided_by": "Director",
                "decision": "REPAIR",
                "run_id": "her-run",
                "outcome": "NOTHING_DONE",
                "verdicts": [],
                "done": {
                    "overturned": [
                        {"scene_index": 3, "checks": ["motion_qc"], "severity": "none",
                         "reason": "the clip moves"}
                    ]
                },
            },
            "c",
        )  # fmt: skip

    context = film_qc_context(engine, failed_render_reading(engine, film["report"]))

    scene = next(item for item in context["scenes"] if item["scene_index"] == 5)
    note = scene["accepted_on_takes"]["still"]
    assert note["approved_by"] == "director_look"
    assert note["minor_traces_accepted"] == [
        {"finding": "a thin seam at the top", "seen": "a faint line"}
    ]
    assert note["director_look"]["severity"] == "minor"
    assert "accepted_on_takes" in _DIRECTOR_QC_INSTRUCTIONS
    (earlier,) = context["earlier_reviews"]
    assert earlier["overturned"] == [
        {"scene_index": 3, "checks": ["motion_qc"], "severity": "none",
         "reason": "the clip moves"}
    ]  # fmt: skip


def test_her_second_look_sees_the_scene_as_quality_control_judged_it(engine, monkeypatch, tmp_path):
    """Finding 5: her look was shown the film's frames with the studio's burnt-in subtitles,
    confirmed a refusal for «text» that was our own captions, and a still was bought. The
    frames are now the view the second look prepares (the scene's shot, else the film with the
    caption rows cut out…), at quality control's own frame numbers."""
    import sys
    import types

    from app.agents.reviews import failed_render_reading
    from app.runbook import stages

    film = failed_film(engine)
    with Session(engine) as session, session.begin():
        report = session.get(QualityControlReport, film["report"])
        checks = json.loads(json.dumps(report.checks_json))
        for entry in checks["picture_spans_qc"]["scenes"]:
            if entry["scene_index"] == 5:
                entry["frames"] = [
                    {"at": at, "time": frame / 30, "frame": frame}
                    for at, frame in (("first", 603), ("middle", 640), ("last", 677))
                ]
        report.checks_json = checks
    asked: list[tuple[str, int, list[int]]] = []

    def view(engine_, media_asset_id, scene_index, *, work_dir=None, ffmpeg_path=None,
             frame_numbers=()):  # fmt: skip
        asked.append((media_asset_id, scene_index, list(frame_numbers)))
        return ["a.png", "b.png", "c.png"], {"source": "FILM_CROPPED"}

    module = types.ModuleType("app.media.second_look")
    module.film_scene_view = view  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.media.second_look", module)

    frames = stages._failed_film_frames(
        engine, failed_render_reading(engine, film["report"]), 5, None, tmp_path
    )

    assert frames == ["a.png", "b.png", "c.png"]
    assert asked == [(film["asset"], 5, [603, 640, 677])]
