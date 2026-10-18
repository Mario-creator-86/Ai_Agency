"""An autonomous day in PRODUCTION, end to end, under each of the Owner's paid-media rules.

2026-10-02 (CONTINUE_REDOS_E2E; A11, TS-02, A6, AR-05). Every end-to-end day of the suite ran
in TEST, where the daily run buys nothing from a paid vendor, so nothing showed that the
studio the Owner wants - his policy says AUTONOMOUS_CEO and his paid-media rule MODE - makes a
film from the clock to a private upload with nobody pressing anything. Nor that under
EVERY_PAID_STEP his yes moves the film on the same day, instead of at the next 05:00 run.

WHAT IS REAL: the scheduler-free day (`execute_daily_run` with the real stage runners), the
research, the script, the model shot plan, the shooting sheet with its lint, prices, caps,
budgets, leases and holds, the Policy Kernel and its `paid_media_approval` rule, the stills
gate's local checks, clip QC's verdict reading, the hero gate, the assembly from takes, FFmpeg,
the film's quality control, the Director's look, the publishing gate and the channel policy,
the books, the queue and the worker's FILM_CONTINUE handler.

WHAT IS FAKED: the vendors (tests/test_autonomous_day_end_to_end.VENDOR_FAKES plus the Runway
stills and video spies of tests/test_film_costing and tests/test_stills_stage), the vision
judges (a paid agent run) and the language model. No socket leaves the machine
(tests/conftest.py refuses one); nothing here costs money, and nothing activates daily_main.

Honest limit: a fake proves the studio's wiring and its money discipline, never that a real
film is good. The first capped paid film is the real test.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import pytest
from app.media.toolchain import find_ffmpeg
from app.models import OwnerPolicy
from app.runbook.stages import build_stage_runners
from sqlalchemy import select
from sqlalchemy.orm import Session

# `studio` is the end-to-end module's fixture (the whole studio, every vendor faked); imported
# so pytest registers it here, and read through `request` so no test parameter shadows it.
from test_autonomous_day_end_to_end import _test_clip, studio  # noqa: F401

requires_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None, reason="FFmpeg not installed; a day cannot be filmed"
)

pytestmark = [pytest.mark.slow]


# ------------------------------------------------------------------------- the world --


def _vault(engine):
    from app.integrations.vault import CredentialVault

    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def _production(engine, settings, *, rule: str, over_usd: float | None = None, budget: str = "100"):
    """PRODUCTION, AUTONOMOUS_CEO, his paid-media rule, and a daily budget (fail closed).

    The film's ceiling is his figure (STUDIO_FILM_BUDGET_USD): the default, the motion budget
    plus a six-scene stills cap (15,24 USD), is below the motion cap of four ten-second
    scenes, and the film would rightly wait OVER_FILM_BUDGET for him."""
    from app.economy.budget import BudgetCommand, set_budget

    settings.film_budget_usd = 60.0

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.environment = "PRODUCTION"
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.paid_media_approval = rule
        policy.paid_media_approval_over_usd = over_usd
    if budget:
        set_budget(engine, BudgetCommand(period="DAILY", limit_usd=budget))


def _runway(monkeypatch, tmp_path, *, balance: float = 10_000) -> dict[str, Any]:
    """The Runway connection the staircase climbs, faked: stills, a video model, an account.

    The stills are real 1080x1920 pictures with nobody in them; the clips a real h264 test
    pattern; the account a balance that each purchase lowers by its catalogue price."""
    from app.media import prompt_lint
    from app.runbook import stages
    from runpod_worker.contract import MAX_PROMPT
    from test_daily_run_stages import _noise_stills
    from test_film_costing import SEEDANCE, Account, Models, SpyVideo
    from test_stills_stage import SpyStills

    stills = _noise_stills(tmp_path)
    account = Account(balance)
    images = SpyStills(pictures=lambda prompt, call: list(stills), balance=balance)
    # The stills route allows what the GPU worker allows, as the studio's own does (Qwen on
    # RunPod since 2026-10-08): a serial's complete prompt is never cut to fit (2026-10-14)
    # and fits there as in production; still priced as seedream, so the staircase's figures
    # stay what the docstrings say.
    monkeypatch.setitem(prompt_lint.ALLOWANCES, images.model, MAX_PROMPT)

    class TimedVideo(SpyVideo):
        """A clip of exactly the seconds the shot asked for, as the vendor delivers it."""

        async def get_generation_status(self, job_id):
            result = await super().get_generation_status(job_id)
            if result.status == "COMPLETED":
                number = int(job_id.rsplit("-", 1)[1])
                seconds = float(self.asked[number - 1]["seconds"])
                result.video_bytes = _test_clip(round(seconds, 3))
            return result

    models = Models(TimedVideo("seedance2_5", account))
    monkeypatch.setattr(
        stages,
        "sheet_wiring",
        lambda engine_, vault, settings_: {
            "integration_id": None,
            "capabilities": [SEEDANCE],
            "image_adapter": images,
            "account": account,
            "adapter_for_model": models,
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
    )
    return {"images": images, "models": models, "account": account}


#: A shot plan with a different frame and subject per scene, as a real Video Editor writes
#: one: the end-to-end stand-in answers every scene alike, which the sheet's lint rightly
#: BLOCKs in PRODUCTION ("every filmed scene has the same framing"). The fake editor
#: must also return complete Kael-owned still/motion vendor texts and camera_move; legacy
#: plan-only shots are correctly rejected by the production prompt gate.
VARIED_SHOTS = (
    (
        "a wide, low angle, 24mm lens",
        "the observatory dome on a cold hillside at night",
        "the dome turns slowly, its shutter opening",
    ),
    (
        "a medium shot, eye-level, 50mm lens",
        "the segmented golden mirror of a telescope",
        "a faint reflection drifts across the segments",
    ),
    (
        "a detail shot, macro, 85mm lens",
        "a cloud of red dust around a young star",
        "the dust thins slowly and light shows through",
    ),
    (
        "an aerial shot, high angle",
        "an empty field under a clear starry sky",
        "the stars wheel slowly overhead",
    ),
)


def _serial_fake_shot(scene: dict, index: int, move: str) -> dict:
    """Fixture Kael answer based on the episode's real cast, not the factual astronomy plan.

    The first moment and canonical clothing enter the still, and the unchanged first
    moment and exact ending enter motion. Production lint and gates remain unchanged.
    """
    from app.media.prompt_agent import (
        _ending_sentence,
        _serial_package,
        _short_name,
        serial_still_moment,
    )
    from app.media.series_look import load_series_look, room_sentence

    look = load_series_look()
    probe = _serial_package({"action": ""}, None, scene, look)
    people = probe["in_frame"]
    focus = _short_name(people[0].get("name")) if people else "the speaker"
    action = "; ".join(
        f"{_short_name(person.get('name'))} stands beside the office desk"
        for person in people
    ) or "the speaker stands beside the office desk"
    probe["action"] = action
    first_moment = serial_still_moment(probe)
    identities = "; ".join(
        f"{_short_name(person.get('name'))}, "
        f"{str(person.get('face_hair') or '').split(';')[0]}, "
        f"wearing {person.get('outfit') or 'office clothes'}"
        for person in people
    )
    place = str(scene.get("location") or "studio house")
    still_prompt = " ".join(part for part in (
        str(look.get("block") or ""),
        room_sentence(look, place),
        f"A single, eye-level, vertical office shot of {focus}, facing the viewer.",
        f"The characters retain their canonical appearances: {identities}." if identities else "",
        f"{first_moment}.",
    ) if part)
    ending_frame = f"with {focus} standing beside the office desk"
    motion_prompt = (
        f"A steady {move} at a measured pace. {action}. "
        f"{_ending_sentence(ending_frame)}"
    )
    return {
        "scene_index": index,
        "story_purpose": "EVIDENCE",
        "subject": f"{focus} in the {place}",
        "action": action,
        "environment": place,
        "camera": "medium eye-level office shot",
        "camera_move": move,
        "lighting": "the warm amber lamps of the series look",
        "composition": "vertical office shot with the characters facing the viewer",
        "motion": action,
        "emotion": "quiet focus",
        "background": "wooden desks, amber lamps and bookshelves",
        "continuity": "the same room and canonical clothes across the episode",
        "ending_frame": ending_frame,
        "audio_intent": "office ambience, clear spoken dialogue",
        "transition": "cut",
        "avoid": ["writing in the picture"],
        "still_prompt": still_prompt,
        "motion_prompt": motion_prompt,
        "negative_prompt": "letters, logos",
    }


def _varied_shot_plan(studio_, monkeypatch) -> None:
    import json
    import re

    def shots(prompt: str) -> str:
        indices = sorted({int(n) for n in re.findall(r'"scene_index":\s*(\d+)', prompt)}) or [1]
        payload_match = re.search(
            r'<untrusted_source_evidence hash="approved-film">\s*(.*?)\s*</untrusted_source_evidence>',
            prompt, re.DOTALL,
        )
        payload = json.loads(payload_match.group(1)) if payload_match else {}
        episode = (payload.get("episode") or {}) if isinstance(payload, dict) else {}
        serial_scenes = {
            int(item["scene_index"]): item
            for item in episode.get("scenes", [])
            if isinstance(item, dict) and isinstance(item.get("scene_index"), int)
        }
        planned = []
        for index in indices:
            camera, subject, action = VARIED_SHOTS[(index - 1) % len(VARIED_SHOTS)]
            move = ("dolly in", "tracking left", "crane up", "slow pan right")[(index - 1) % 4]
            if index in serial_scenes:
                planned.append(_serial_fake_shot(serial_scenes[index], index, move))
                continue
            still_prompt = (
                f"Documentary photograph, {camera}. The first instant shows {subject} "
                "at a remote observatory beneath a dark, clear sky. Cold moonlight "
                "illuminates the foreground, with one warm lamp behind the subject. "
                "A single continuous vertical 9:16 frame, carefully composed."
            )
            ending_frame = f"{subject}, centred"
            motion_prompt = (
                f"A steady {move} at a measured pace while {action}. "
                "The world and subject remain consistent in one uninterrupted shot. "
                f"The shot ends on {ending_frame}."
            )
            planned.append(
                {
                    "scene_index": index,
                    "story_purpose": "EVIDENCE",
                    "camera_move": move,
                    "still_prompt": still_prompt,
                    "motion_prompt": motion_prompt,
                    "negative_prompt": "letters, logos",
                    "subject": subject,
                    "action": action,
                    "environment": "a remote observatory far from any city",
                    "camera": camera,
                    "lighting": "moonlight from the left, one warm lamp behind",
                    "composition": "vertical, the subject in the lower third",
                    "motion": action,
                    "emotion": "quiet anticipation",
                    "background": "stars, unmoving",
                    "continuity": "the same night sky as the previous shot",
                    "ending_frame": ending_frame,
                    "audio_intent": "wind, distant",
                    "transition": "cut",
                    "avoid": ["text of any kind"],
                }
            )
        return json.dumps({"shots": planned})

    monkeypatch.setattr(studio_["model"], "_shots", shots)


def _judges_pass(monkeypatch) -> None:
    """The stills judge and clip QC's verdict, faked as passing (both are paid agent runs)."""
    from app.media import qc as clip_qc
    from app.media import shooting_sheet
    from test_stills_stage import SpyJudge

    monkeypatch.setattr(
        shooting_sheet,
        "run_stills_stage",
        functools.partial(shooting_sheet.run_stills_stage, judge=SpyJudge()),
    )

    def passing(path, *, scene, **_kwargs):
        good = clip_qc.ClipCheck("picture", "PASSED", True, None, "arată ce s-a cerut")
        return clip_qc.ClipReport(
            scene=scene,
            path=str(path),
            checks=(good,),
            passed=True,
            blocks_ro=(),
            warnings_ro=(),
            unmeasured=(),
        )

    monkeypatch.setattr(clip_qc, "check_clip", passing)


def _run_day(engine, settings, studio_):
    from app.runbook.services import execute_daily_run

    runners = build_stage_runners(engine, settings, _vault(engine), studio_["registry"])
    result = execute_daily_run(
        engine, settings, _vault(engine), correlation_id="day-1", stage_runners=runners
    )
    from app.runbook.models import DailyRun

    with Session(engine) as session:
        run = session.get(DailyRun, result["id"])
        stages_ = {stage["stage"]: stage for stage in run.stages_json}
    return result, stages_


def _rows(engine, model) -> list[Any]:
    with Session(engine) as session:
        rows = list(session.scalars(select(model)))
        session.expunge_all()
        return rows


def _approvals(engine):
    from app.models import ApprovalRequest

    return _rows(engine, ApprovalRequest)


def _publications(engine):
    from app.publishing.models import PublicationRecord

    return _rows(engine, PublicationRecord)


def _costs(engine):
    from app.economy.models import ProviderCostRecord

    return _rows(engine, ProviderCostRecord)


def _channel_type(engine, channel_id: str) -> str:
    from app.publishing.models import ChannelRecord

    with Session(engine) as session:
        return str(session.get(ChannelRecord, channel_id).channel_type)


def _reasons(stages_) -> str:
    return "\n".join(f"{name} {s['status']}: {s['reason']}" for name, s in stages_.items())


# ---------------------------------------------------------------------- (a) MODE --


@requires_ffmpeg
def test_under_mode_one_production_day_makes_and_publishes_the_film_with_nobody_asked(
    engine, settings, request, monkeypatch, tmp_path
):
    """(a) PRODUCTION + AUTONOMOUS_CEO + MODE: one daily run climbs the sheet (stills judged,
    hero accepted by clip QC, motion), assembles, passes QC and uploads the film privately to
    Channel A. Nobody is asked; every purchase is in the books once."""
    from app.media.models import QualityControlReport

    the_studio = request.getfixturevalue("studio")
    _production(engine, settings, rule="MODE")
    world = _runway(monkeypatch, tmp_path)
    _judges_pass(monkeypatch)
    _varied_shot_plan(the_studio, monkeypatch)

    result, stages_ = _run_day(engine, settings, the_studio)

    assert stages_["media"]["status"] == "COMPLETED", _reasons(stages_)
    reports = _rows(engine, QualityControlReport)
    if not any(r.status == "PASSED" for r in reports):
        found = [(r.status, r.failure_reasons_json) for r in reports]
        pytest.fail(f"{found}\n{_reasons(stages_)}")
    factual = [
        p for p in _publications(engine) if _channel_type(engine, p.channel_id) == "MAIN_FACTUAL"
    ]
    assert len(factual) == 1, _reasons(stages_)
    assert factual[0].privacy_status == "private"
    assert _approvals(engine) == [], [(a.action, a.result) for a in _approvals(engine)]
    steps = sorted(c.attribution_json.get("step") for c in _costs(engine) if c.attribution_json)
    assert {"stills", "test_shot", "motion"} <= set(steps), steps
    assert world["models"].posts() >= 2


def _bought_credits(world) -> float:
    """What the fake vendors were paid, in credits: the stills and the video account."""
    return (10_000 - float(world["images"].balance)) + (10_000 - float(world["account"].balance))


def _booked_credits(engine) -> float:
    return sum(
        float((cost.attribution_json or {}).get("credits") or 0)
        for cost in _costs(engine)
        if (cost.attribution_json or {}).get("step") in ("stills", "test_shot", "motion")
    )


def _worker(engine, settings, studio_):
    from app.workflows.worker import build_task_handlers

    runners = build_stage_runners(engine, settings, _vault(engine), studio_["registry"])
    return build_task_handlers(engine, settings, _vault(engine), runners, studio_["registry"])


def _run_queue(engine, handlers) -> list[dict[str, Any]]:
    """Every task the queue holds now, run by the worker, as its loop would."""
    from app.workflows.worker import work_once

    ran = []
    while (result := work_once(engine, handlers)) is not None:
        ran.append(result)
    return ran


def _answer(engine, approval_id: str) -> None:
    from uuid import uuid4

    from app.schemas import ApprovalDecisionCommand
    from app.services import decide_approval

    decide_approval(
        engine,
        ApprovalDecisionCommand(
            command_id=uuid4(), approval_id=approval_id, decision="APPROVED", note="Da."
        ),
    )


def _pending(engine) -> list[Any]:
    return [a for a in _approvals(engine) if a.result == "PENDING"]


def _of_film(approvals: list[Any], storyboard_id: str) -> list[Any]:
    """The approvals asked for one film (the storyboard is the question's subject)."""
    return [a for a in approvals if a.subject == storyboard_id]


def _split_films(engine, films: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """The day's films by kind: (factual, serial). Since 3c30bc6 the serial's approved episode
    is walked the same day beside the factual film (its scenes composed from the series look
    are no shot-plan gap), so it asks its own questions and buys its own hero under his rule;
    the tests below follow the factual film and tell the serial's film apart by its storyboard."""
    from app.agents.editorial import is_serial_film
    from app.factual.models import ScriptDraft
    from app.media.models import Storyboard

    factual: list[dict] = []
    serial: list[dict] = []
    with Session(engine) as session:
        for film in films:
            board = session.get(Storyboard, film["storyboard_id"])
            script = (
                session.get(ScriptDraft, board.script_draft_id)
                if board is not None and board.script_draft_id
                else None
            )
            (serial if is_serial_film(board, script) else factual).append(film)
    return factual, serial


def _boards_bought(engine, kind: str | None = None) -> set[str]:
    """The storyboards with a take of ``kind`` (any kind when None): who bought something."""
    from app.media.models import SceneTake

    return {
        str(take.storyboard_id)
        for take in _rows(engine, SceneTake)
        if kind is None or take.kind == kind
    }


def _hero_take(engine, storyboard_id: str | None = None):
    from app.media.models import SceneTake

    return next(
        take
        for take in _rows(engine, SceneTake)
        if take.kind == "test_shot"
        and take.status == "PAID"
        and (storyboard_id is None or take.storyboard_id == storyboard_id)
    )


def _factual_publications(engine):
    return [
        p for p in _publications(engine) if _channel_type(engine, p.channel_id) == "MAIN_FACTUAL"
    ]


# ------------------------------------------------------------------ (b) OVER_USD --


@requires_ffmpeg
def test_under_over_usd_below_the_motion_cap_the_owner_is_asked_once_at_the_motion(
    engine, settings, request, monkeypatch, tmp_path
):
    """(b) His amount (20 USD) is above the stills' and the hero's caps and below the
    motion's (27,20 USD): the day buys the stills and the hero unasked and waits for his look
    at the hero; his look continues the film at once and asks exactly one question, at the
    motion; his yes continues it again, to a private upload the same day. The serial's
    episodes walk beside it since 3c30bc6 (its composed scenes are no shot-plan gap): today's,
    walked by the day's media stage, and tomorrow's, written by `serial_next` after the close
    and queued for filming the same evening (e565a6b), walked by the worker — each buys its
    own stills and hero unasked under his amount and waits for his look at its hero, with no
    question of its own."""
    the_studio = request.getfixturevalue("studio")
    _production(engine, settings, rule="OVER_USD", over_usd=20.0)
    world = _runway(monkeypatch, tmp_path)
    _judges_pass(monkeypatch)
    _varied_shot_plan(the_studio, monkeypatch)
    handlers = _worker(engine, settings, the_studio)

    _result, stages_ = _run_day(engine, settings, the_studio)

    factual, serial = _split_films(engine, stages_["media"]["artefacts"]["films"])
    (film,) = factual
    board = film["storyboard_id"]
    assert film["refusal"] == "HERO_NOT_APPROVED", _reasons(stages_)
    assert [f["refusal"] for f in serial] == ["HERO_NOT_APPROVED"], _reasons(stages_)
    assert world["models"].posts() == 2  # the factual film's hero and today's episode's
    assert _approvals(engine) == []

    from app.media.assembler import decide_take

    decide_take(engine, _hero_take(engine, board).id, "APPROVED", decided_by="owner")
    ran = _run_queue(engine, handlers)

    # The worker walked his continuation and tomorrow's episode (queued by serial_next): the
    # episode bought its stills and hero unasked and waits for his look, asking nothing.
    assert sorted(r["status"] for r in ran) == ["COMPLETED", "COMPLETED"], ran
    (question,) = _approvals(engine)
    assert question.subject == board
    assert question.action == "media.motion_purchase" and question.result == "PENDING"
    assert world["models"].posts() == 3
    assert len(_boards_bought(engine, "test_shot")) == 3

    _answer(engine, question.id)
    ran = _run_queue(engine, handlers)

    assert [r["status"] for r in ran] == ["COMPLETED"], ran
    assert world["models"].posts() == 6  # the factual film's three clips bought
    (published,) = _factual_publications(engine)
    assert published.privacy_status == "private", ran
    assert len(_approvals(engine)) == 1
    assert _booked_credits(engine) == pytest.approx(_bought_credits(world))


# ----------------------------------------------------------- (c) EVERY_PAID_STEP --


@requires_ffmpeg
def test_under_every_paid_step_each_yes_continues_the_film_the_same_day_to_a_private_upload(
    engine, settings, request, monkeypatch, tmp_path
):
    """(c) The day asks at the stills and buys nothing unasked; each of his yeses queues
    FILM_CONTINUE and the worker climbs exactly one more stair; his look at the hero and his
    yes on the motion take the film to a private upload, all on the same date. The serial's
    two episodes (today's, walked by the day; tomorrow's, queued by serial_next and walked by
    the worker) each ask their own stills question and, unanswered here, buy nothing."""
    from app.runbook.models import DailyRun

    the_studio = request.getfixturevalue("studio")
    _production(engine, settings, rule="EVERY_PAID_STEP")
    world = _runway(monkeypatch, tmp_path)
    _judges_pass(monkeypatch)
    _varied_shot_plan(the_studio, monkeypatch)
    handlers = _worker(engine, settings, the_studio)

    _result, stages_ = _run_day(engine, settings, the_studio)

    factual, serial = _split_films(engine, stages_["media"]["artefacts"]["films"])
    (film,) = factual
    board = film["storyboard_id"]

    def serial_questions() -> list[Any]:
        """The serial's own stills questions, pending: today's episode's after the day,
        tomorrow's too once the worker walked its queued continuation."""
        asked = [a for a in _pending(engine) if a.subject != board]
        assert {a.action for a in asked} <= {"media.stills_purchase"}, asked
        return asked

    (serial_stills,) = serial_questions()
    assert serial_stills.subject == serial[0]["storyboard_id"]
    (stills,) = _of_film(_pending(engine), board)
    assert stills.action == "media.stills_purchase"
    assert world["images"].asked == [] and world["models"].posts() == 0

    _answer(engine, stills.id)
    _run_queue(engine, handlers)
    assert len(world["images"].asked) > 0 and world["models"].posts() == 0
    (hero,) = _of_film(_pending(engine), board)
    assert hero.action == "media.test_shot"
    assert len(serial_questions()) == 2

    _answer(engine, hero.id)
    _run_queue(engine, handlers)
    assert world["models"].posts() == 1
    # The hero waits for his look, not for a question; the serial's questions still stand.
    assert _of_film(_pending(engine), board) == [] and len(serial_questions()) == 2

    from app.media.assembler import decide_take

    decide_take(engine, _hero_take(engine, board).id, "APPROVED", decided_by="owner")
    _run_queue(engine, handlers)
    (motion,) = _of_film(_pending(engine), board)
    assert motion.action == "media.motion_purchase"
    assert world["models"].posts() == 1

    _answer(engine, motion.id)
    ran = _run_queue(engine, handlers)

    assert world["models"].posts() == 4, ran
    (published,) = _factual_publications(engine)
    assert published.privacy_status == "private"
    asked = _of_film(_approvals(engine), board)
    assert sorted(a.action for a in asked) == [
        "media.motion_purchase",
        "media.stills_purchase",
        "media.test_shot",
    ]
    assert all(a.consumed_at is not None for a in asked)
    assert len(serial_questions()) == 2 and _boards_bought(engine) == {board}
    assert _booked_credits(engine) == pytest.approx(_bought_credits(world))
    # One scheduled day, whatever the continuations did.
    assert len(_rows(engine, DailyRun)) == 1


# --------------------------------------------------- (d) the ways a day stops short --


def _stage_world(engine, settings, monkeypatch, tmp_path, *, rule="MODE", balance=10_000.0):
    """One film at the bottom of its staircase and the media stage alone, run three times."""
    from app.runbook import stages
    from test_daily_run_stages import _bottom_of_the_staircase
    from test_daily_run_stages import _production as stage_production

    stage_production(engine)
    world = _runway(monkeypatch, tmp_path, balance=balance)
    monkeypatch.setattr(stages, "story_gate", lambda session, script_id: (True, ""))
    _judges_pass(monkeypatch)
    settings.film_budget_usd = 60.0
    storyboard_id = _bottom_of_the_staircase(engine, tmp_path, scenes=2)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).paid_media_approval = rule
    return storyboard_id, world


def _three_days(engine, settings) -> list[dict[str, Any]]:
    from app.runbook import stages

    return [stages._media(engine, settings, None, None) for _day in range(3)]


def _sheet_letters(engine) -> list[Any]:
    from app.agents.models import AgentMessage

    return [
        m
        for m in _rows(engine, AgentMessage)
        if isinstance(m.body_json, dict) and m.body_json.get("kind") == "owner_shooting_sheet"
    ]


def _holds(engine) -> list[Any]:
    from app.economy.models import SpendReservation

    return _rows(engine, SpendReservation)


@requires_ffmpeg
@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        ("low_balance", "LOW_BALANCE"),
        ("budget_exceeded", "OVER_DAILY_BUDGET"),
        ("no_budget", "BLOCKED_NO_BUDGET"),
    ],
)
def test_a_day_stopped_by_money_writes_once_buys_nothing_and_holds_nothing(
    engine, settings, monkeypatch, tmp_path, case, refusal
):
    """(d) No money on the account, a daily budget the stills' cap would pass, no daily budget
    at all under MODE: three days, one letter naming the reason, nothing bought or booked,
    and every hold let go."""
    from app.economy.budget import BudgetCommand, set_budget

    balance = 10.0 if case == "low_balance" else 10_000.0
    _storyboard_id, world = _stage_world(engine, settings, monkeypatch, tmp_path, balance=balance)
    if case == "budget_exceeded":
        set_budget(engine, BudgetCommand(period="DAILY", limit_usd="0.10"))
    elif case == "low_balance":
        set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))

    outcomes = _three_days(engine, settings)

    films = [outcome["artefacts"]["films"][0] for outcome in outcomes]
    assert {film["refusal"] for film in films} == {refusal}, films
    assert world["images"].asked == [] and world["models"].posts() == 0
    assert _costs(engine) == []
    (letter,) = _sheet_letters(engine)
    assert letter.body_json["status"] == refusal
    assert all(hold.status != "RESERVED" for hold in _holds(engine))
    assert _approvals(engine) == []


@requires_ffmpeg
@pytest.mark.parametrize("case", ["stills_rejected", "clip_fails_twice"])
def test_a_failing_still_or_hero_is_bought_once_over_three_days_and_waits_for_the_director(
    engine, settings, monkeypatch, tmp_path, case
):
    """(d) The judge rejects every still, or clip QC fails the hero: over three days the
    stills are requested once, or the hero bought once, and nothing is bought again — a
    quality refusal is the Director's (2026-10-12): her ladder re-rolls or retries from her
    brief, which this world cannot run (no shot plan, no registry), so the scene waits for
    her and no letter reaches the Owner; every purchase is in the books once, and no hold
    is left standing."""
    from app.economy.budget import BudgetCommand, set_budget
    from app.media import qc as clip_qc
    from test_daily_run_stages import _judge_rejects_every_still

    _storyboard_id, world = _stage_world(engine, settings, monkeypatch, tmp_path)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="100"))
    if case == "stills_rejected":
        _judge_rejects_every_still(monkeypatch)
    else:

        def failing(path, *, scene, **_kwargs):
            bad = clip_qc.ClipCheck("picture", "FAILED", True, None, "nu arată ce s-a cerut")
            return clip_qc.ClipReport(
                scene=scene,
                path=str(path),
                checks=(bad,),
                passed=False,
                blocks_ro=("nu arată ce s-a cerut",),
                warnings_ro=(),
                unmeasured=(),
            )

        monkeypatch.setattr(clip_qc, "check_clip", failing)

    outcomes = _three_days(engine, settings)

    film = outcomes[-1]["artefacts"]["films"][0]
    assert film["refusal"] == "NEEDS_OWNER", film
    # No sheet letter: quality stays with the Director (75f2267; the Owner hears of money,
    # accounts and security). This fixture film's scene carries no shot plan, so her ladder
    # cannot rewrite it yet and each day's register says she holds it; nothing is bought
    # again meanwhile.
    assert _sheet_letters(engine) == []
    assert all("Directoarea preia remedierea" in o["reason"] for o in outcomes)
    assert all(hold.status != "RESERVED" for hold in _holds(engine))
    steps = sorted((c.attribution_json or {}).get("step") for c in _costs(engine))
    if case == "stills_rejected":
        assert len(world["images"].asked) == 1 and world["models"].posts() == 0
        assert steps == ["stills"]
    else:
        assert len(world["images"].asked) == 2 and world["models"].posts() == 1
        assert steps == ["stills", "test_shot"]
