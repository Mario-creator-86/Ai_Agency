"""The Owner's renders cap at two (2026-10-16 ~12:00Z): «limităm acum la 2 randări, pentru că
sunt mai lungi și mai costisitoare, maxim încă o randare».

Each shot's picture and its motion get the first render and at most one more, on every route
that can buy them: the stills step and its re-rolls, the Director's ladder and the next walk,
the motion step and its clip-QC retry, the Director's paid redo, the studio's own proposal,
the delivery retry. The number lives in `Settings.renders_per_layer` and is read when it is
used (`app.media.renders_cap`); the holds are sized for it and the sentences say it.

The rest of the suite keeps the three its fixtures were written on (tests/conftest.py pins
STUDIO_RENDERS_PER_LAYER=3); every test here runs at two (the ``renders_per_layer`` marker).
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.identity import STANDING_RULES, standing_rules
from app.config import Settings
from app.media import assembler, renders_cap, scene_rewrite, shooting_sheet, stills_stage
from app.media import qc as clip_qc
from app.media.assembler import (
    CLIP_QC_EVENT,
    SceneRedoRefused,
    SpendMeter,
    _ShotRounds,
    clip_qc_of,
    motion_capped_reason,
    motion_plan,
    redo_scene,
)
from app.media.cost_plan import (
    STILLS_MODEL,
    STILLS_RESOLUTION,
    credits_to_micros,
    load_price_table,
    price_still,
)
from app.media.models import SceneTake
from app.media.qc import ClipCheck, ClipReport, clip_retry_decision
from app.media.renders_cap import (
    clip_retries,
    max_rerolls,
    paid_redos_per_scene,
    renders_of_ro,
    renders_per_layer,
    renders_ro,
    times_en,
)
from app.media.shooting_sheet import DEFAULT_CEILING_SCENES, film_ceiling_micros
from app.media.still_gate import StillReport, next_step
from app.media.toolchain import find_ffmpeg
from app.models import DomainEvent
from app.providers.media_http import MediaProviderError
from app.runbook import stages
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_delivery_routing import failed_delivery
from test_director_rewrites_failed_scene import BRIEF, Agents, agents_say
from test_director_rewrites_failed_scene import studio as studio  # noqa: F401 - fixture
from test_film_costing import (
    SEEDANCE,
    VEO_FAST,
    Account,
    Models,
    SpyVideo,
    approved,
    by_scene,
    hero_approved,
)
from test_film_costing import a_film as a_film_with_stills
from test_stills_stage import (
    FACE,
    NO_FACE,
    SUBJECTS,
    SpyJudge,
    SpyStills,
    approved_run,
    faces_in,
)
from test_stills_stage import a_film as a_film_to_buy

pytestmark = pytest.mark.renders_per_layer(2)
#: The motion plan and the motion step read clips as the film tests do.
needs_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


def _token() -> str:
    return secrets.token_urlsafe(48)


def _take(
    session: Session,
    board: str,
    scene: int,
    kind: str,
    *,
    status: str = "REJECTED",
    on_disk: Path | None = None,
    failure_code: str | None = "LOCAL.STILL_GATE",
    prompt_hash: str | None = None,
    credits: float | None = None,
) -> str:
    """One paid take of a scene's layer: on disk when ``on_disk`` names a file to write."""
    take_id = str(uuid4())
    path = sha = None
    if on_disk is not None:
        on_disk.write_bytes(f"{kind} {take_id}".encode())
        path, sha = str(on_disk), hashlib.sha256(on_disk.read_bytes()).hexdigest()
    now = utc_now()
    session.add(
        SceneTake(
            id=take_id,
            storyboard_id=board,
            scene_number=scene,
            kind=kind,
            prompt_hash=prompt_hash or uuid4().hex,
            model_id=STILLS_MODEL if kind == "still" else "seedance2_5",
            resolution="1530:2720" if kind == "still" else "1080:1920",
            status=status,
            failure_code=failure_code if status == "REJECTED" else None,
            failure_detail="nu arată ce cere scena" if status == "REJECTED" else None,
            path=path,
            sha256=sha,
            credits_quoted=credits,
            remote_task_id=f"task-{take_id[:8]}",
            created_at=now,
            updated_at=now,
        )
    )
    return take_id


def _still_report(scene: int) -> StillReport:
    return StillReport(
        path="still.png",
        sha256=uuid4().hex,
        scene=scene,
        checks=(),
        judgement=None,
        decision="BLOCKED",
        outcome="regenerate_still",
        reasons_ro=("imaginea e neclară",),
        warnings_ro=(),
        faces_found=False,
        violations=("blur",),
        unmeasured=(),
        score=0.2,
    )


def _failed_clip(scene: int) -> ClipReport:
    return ClipReport(
        scene=scene,
        path="clip.mp4",
        checks=(ClipCheck("motion", "FAILED", True, 0.1, "clipul aproape nu se mișcă"),),
        passed=False,
        blocks_ro=("clipul aproape nu se mișcă",),
        warnings_ro=(),
        unmeasured=(),
    )


# ------------------------------------------------------------- 1. one setting, read when used


def test_production_makes_each_layer_twice_and_the_suite_pins_three(monkeypatch):
    """The production default is two; the paid redos a scene gets follow it (none set: what
    the cap leaves after the first render)."""
    field = Settings.model_fields["renders_per_layer"]
    assert field.default == 2
    assert Settings.model_fields["film_max_paid_redos_per_scene"].default is None
    monkeypatch.delenv("STUDIO_RENDERS_PER_LAYER", raising=False)
    monkeypatch.delenv("STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE", raising=False)
    production = Settings(_env_file=None, owner_token=_token())
    assert production.renders_per_layer == 2
    assert renders_per_layer(production) == 2
    assert max_rerolls(production) == 1 and clip_retries(production) == 1
    assert paid_redos_per_scene(production) == 1  # the first purchase + one redo = 2


def test_the_cap_is_read_when_it_is_used_never_frozen_at_import(monkeypatch):
    assert renders_per_layer() == 2  # this module's marker
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "4")
    assert renders_per_layer() == 4 and max_rerolls() == 3 and clip_retries() == 1
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "1")
    assert max_rerolls() == 0 and clip_retries() == 0
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "2")
    # A settings object that carries the field is read first; one that does not (a stand-in,
    # a mock) leaves the studio's settings to say it.
    assert renders_per_layer(SimpleNamespace(renders_per_layer=3)) == 3
    assert renders_per_layer(SimpleNamespace()) == 2
    # The Owner's own per-scene figure only lowers the redos, never past the cap.
    assert paid_redos_per_scene(SimpleNamespace(film_max_paid_redos_per_scene=5)) == 1
    assert paid_redos_per_scene(SimpleNamespace(film_max_paid_redos_per_scene=0)) == 0
    assert paid_redos_per_scene(None) == 1


def test_no_module_keeps_the_number_as_a_constant():
    """The old constants are gone: a reader that kept one would freeze the cap at import."""
    from app.media import qc, still_gate

    assert not hasattr(still_gate, "MAX_REROLLS")
    assert not hasattr(qc, "MAX_CLIP_RETRIES")
    for module in (assembler, stills_stage, stages):
        assert not hasattr(module, "RENDERS_PER_LAYER"), module.__name__


# ------------------------------------------------------------- 2. the picture, on every route


def test_the_gate_rerolls_a_still_once_and_never_a_third_time():
    report = _still_report(3)
    first = next_step(report, rerolls_done=0)
    assert first.action == "reroll" and "(1/1)" in first.reason_ro
    second = next_step(report, rerolls_done=1)
    assert second.action == "needs_owner"
    assert "după 1 refacere" in second.reason_ro


def test_a_still_refused_after_the_ladder_stands_under_the_cap_instead_of_a_third(engine, tmp_path):
    """Scene 2 had a still on its old words (refused; the Director rewrote them). The next
    stills step buys ONE still on the new words — the second render — and when the gate
    refuses it too, the closest candidate stands as the picture: there is no third."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        _take(session, board, 2, "still", on_disk=tmp_path / "old_words.png")

    plan = stills_stage.stills_plan(engine, board)
    per_scene = plan["credits_per_scene"]
    # Scene 2 is held for one round only; the fresh scenes for their first render and one more.
    assert plan["to_buy"] == [1, 2, 3, 4]
    assert plan["max_rerolls"] == 1
    assert plan["cap_credits"] == per_scene * (2 + 1 + 2 + 2)

    def pictures(prompt, call):
        # Scene 2's new words come back with a face again: the gate refuses the still.
        return [FACE, FACE] if SUBJECTS[2] in prompt else list(NO_FACE)

    adapter = SpyStills(pictures=pictures)
    result = approved_run(engine, board, tmp_path, adapter, SpyJudge(), face_counter=faces_in())

    asked_two = [request for request in adapter.asked if SUBJECTS[2] in request["prompt"]]
    assert len(asked_two) == 1
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[2]["status"] == "APPROVED"
    with Session(engine) as session:
        made = renders_cap.renders_made(session, board, 2, "still")
        kept = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == board,
                SceneTake.scene_number == 2,
                SceneTake.status == "APPROVED",
            )
        ).all()
    assert made == 2
    assert [row.approved_by for row in kept] == [assembler.CAP_APPROVER]
    # The next plan reuses it: nothing more of scene 2 is ever offered for purchase.
    again = stills_stage.stills_plan(engine, board)
    assert 2 not in again["to_buy"]


def test_a_scene_at_two_stills_is_never_offered_again_even_with_nothing_on_disk(engine, tmp_path):
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        _take(session, board, 1, "still", on_disk=tmp_path / "one_a.png")
        newest = _take(session, board, 1, "still", on_disk=tmp_path / "one_b.png")
        # Scene 3: two paid requests, neither left a picture (charged, never delivered).
        for _ in range(2):
            _take(
                session,
                board,
                3,
                "still",
                status="REFUSED",
                failure_code=None,
                credits=float(price_still(STILLS_MODEL, STILLS_RESOLUTION, 1)),
            )
    _bible, scenes = stills_stage._read_scenes(engine, board)
    one = next(scene for scene in scenes if scene.index == 1)
    assert one.reuse is not None and one.reuse.id == newest
    assert one.reuse.approved_by == assembler.CAP_APPROVER
    plan = stills_stage.stills_plan(engine, board)
    assert 1 not in plan["to_buy"] and 3 not in plan["to_buy"]
    assert 3 in plan["held"]
    assert stills_stage._at_renders_cap(engine, board, 3)


def test_a_second_render_still_unjudged_is_judged_before_the_cap_keeps_an_older_still(
    engine, tmp_path
):
    """Scene 1's first still was refused; its second render was collected but not judged yet
    (a process stopped between the two). The cap is reached, but the paid second render is not
    passed over for the older refused still: the scene waits for its judgement, and nothing
    more of it is bought meanwhile."""
    board = a_film_to_buy(engine, tmp_path)
    _bible, before = stills_stage._read_scenes(engine, board)
    one = next(scene for scene in before if scene.index == 1)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 1, "still", on_disk=tmp_path / "older.png")
        pending = _take(
            session,
            board,
            1,
            "still",
            status="PAID",
            on_disk=tmp_path / "second.png",
            prompt_hash=assembler.take_hash(one.identity, STILLS_MODEL),
        )
        session.get(SceneTake, pending).failure_code = assembler.UNJUDGED_FAILURE_CODE
    _bible, scenes = stills_stage._read_scenes(engine, board)
    one = next(scene for scene in scenes if scene.index == 1)
    assert one.reuse is None and [take.id for take in one.pending] == [pending]
    with Session(engine) as session:
        assert session.get(SceneTake, older).status == "REJECTED"
        assert renders_cap.renders_made(session, board, 1, "still") == 2
    plan = stills_stage.stills_plan(engine, board)
    assert 1 not in plan["to_buy"]


def test_the_directors_still_redo_is_refused_at_two_renders_and_after_two_shots(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)  # one approved still a scene
    with Session(engine) as session, session.begin():
        _take(session, board, 1, "still", on_disk=tmp_path / "s1.png")  # its second render
        _take(session, board, 2, "motion", on_disk=tmp_path / "m2a.mp4", failure_code="QC.CLIP")
        _take(session, board, 2, "motion", on_disk=tmp_path / "m2b.mp4", failure_code="QC.CLIP")
    # A third picture of scene 1; a new picture of scene 2, whose motion cannot follow it.
    assert "2 randări" in (assembler._redo_past_cap(engine, board, 1, "still") or "")
    assert "nu mai poate fi animată" in (assembler._redo_past_cap(engine, board, 2, "still") or "")
    assert "2 randări" in (assembler._redo_past_cap(engine, board, 2, "motion") or "")
    # Scene 3 has had one render of each: the redo may buy the second.
    assert assembler._redo_past_cap(engine, board, 3, "still") is None
    assert assembler._redo_past_cap(engine, board, 3, "motion") is None

    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine,
            board,
            str(uuid4()),
            kind="still",
            scene_index=1,
            unasked=True,
            director_repair=True,
        )
    assert refused.value.status == assembler.RENDERS_CAP
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 1, "still") == 2


def test_the_still_redo_plan_holds_only_the_render_the_cap_leaves(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=2)
    plan = assembler.redo_plan(engine, board, "still", 2)
    # One render made (the approved still): the redo is the second, no re-roll after it.
    assert plan["max_rerolls"] == 0
    assert plan["cap_credits"] == plan["credits"]
    assert "fără reluări" in plan["reason_ro"] and "2 randări" in plan["reason_ro"]


def test_the_repair_limits_a_layer_at_two_and_a_picture_whose_motion_is_spent():
    renders = {(1, "still"): 2, (2, "motion"): 2, (3, "still"): 1, (3, "motion"): 1}
    cap = renders_per_layer()
    assert stages._over_renders(renders, 1, ["still"], cap) == {"still": 2}
    assert stages._over_renders(renders, 2, ["motion"], cap) == {"motion": 2}
    assert stages._over_renders(renders, 2, ["still"], cap) == {"motion": 2}
    assert stages._over_renders(renders, 3, ["still", "motion"], cap) == {}


# ------------------------------------------------------------- 3. the motion, on every route


def test_clip_qc_buys_one_retry_at_two_and_none_at_one(monkeypatch):
    report = _failed_clip(4)
    first = clip_retry_decision(
        report, seed=7, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert first.action == "RETRY" and first.seed == 8
    second = clip_retry_decision(
        report, seed=8, retries_done=1, committed_credits=10, price_credits=10, cap_credits=100
    )
    assert second.action == "ESCALATE"
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "1")
    only = clip_retry_decision(
        report, seed=7, retries_done=0, committed_credits=0, price_credits=10, cap_credits=100
    )
    assert only.action == "ESCALATE" and "o randare a mișcării" in only.reason_ro


@needs_ffmpeg
def test_a_scene_whose_motion_had_two_renders_is_never_planned_and_the_retry_is_not_held(
    engine, tmp_path
):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        # Scene 2: two shots made on older words, neither usable now.
        _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "a.mp4")
        _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "b.mp4")
        # Scene 3: one shot made: its next is the last, and no retry is held for it.
        _take(session, board, 3, "motion", status="PAID", on_disk=tmp_path / "c.mp4")
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scenes = {item["scene_index"]: item for item in plan["scenes"]}
    assert scenes[2]["status"] == "NEEDS_OWNER"
    assert "2 randări" in scenes[2]["reason_ro"]
    motion = plan["steps"]["motion"]
    assert 2 not in motion["to_buy"] and 3 in motion["to_buy"]
    each = {index: scenes[index]["credits"] for index in motion["to_buy"]}
    overhead = motion["round_overhead_credits"]
    if overhead:
        assert motion["cap_credits"] == sum(each.values()) + overhead
    else:
        assert motion["cap_credits"] == sum(each.values())
    # The hero (scene 1) has had none: its test shot holds its one retry.
    test_shot = plan["steps"]["test_shot"]
    hero = test_shot["to_buy"]
    assert hero == [1]
    first = scenes[1]["credits"]
    expected = 2 * first + 2 * overhead if overhead else 2 * first
    assert test_shot["cap_credits"] == expected


@needs_ffmpeg
def test_the_test_shot_bought_after_a_shot_on_older_words_is_the_last(engine, tmp_path):
    """The hero had one shot on older words. The test shot is its second render: clip QC
    refuses it and nothing more is bought — no retry, and no later plan offers a third. The
    renders cap stops the retry, not the money: no STOPPED_AT_CAP, no «Decide Proprietarul»;
    the refused clip stands under the cap, the Director's closest (the review of f7ba9ee)."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        _take(session, board, 1, "test_shot", status="PAID", on_disk=tmp_path / "old.mp4")
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    step = plan["steps"]["test_shot"]
    assert step["to_buy"] == [1]
    overhead = step["round_overhead_credits"]
    assert step["cap_credits"] == plan["scenes"][0]["credits"] + overhead  # no retry held

    def refused(path, **kwargs):
        return _failed_clip(int(kwargs["scene"]))

    account = Account(50_000)
    video = SpyVideo("seedance2_5", account)
    result = approved(
        engine, board, tmp_path, "test_shot", Models(video), account, clip_check=refused
    )

    assert len(video.asked) == 1
    entry = by_scene(result)[1]
    assert not str(result.get("stopped") or "").startswith("STOPPED_AT_CAP")
    assert "plafonul aprobat" not in str(entry.get("reason") or "")
    assert "Decide Proprietarul" not in str(entry.get("reason") or "")
    assert entry["status"] == "PAID" and entry["clip_qc"]["accepted_under_cap"] is True
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 1, "motion") == 2
        kept = session.get(SceneTake, entry["take_id"])
        assert kept.kind == "test_shot" and kept.approved_by == assembler.CAP_APPROVER
    again = motion_plan(engine, board, capabilities=[SEEDANCE])
    assert again["steps"]["test_shot"]["to_buy"] == []
    assert again["scenes"][0]["status"] != "PLANNED"


def test_the_motion_rounds_send_nothing_past_the_cap(engine, tmp_path):
    rounds = _ShotRounds(
        engine,
        storyboard_id="board",
        correlation_id="c",
        take_kind="motion",
        meter=SpendMeter(),
        cap=1000.0,
        overhead=0.0,
        credit_usd=0.01,
        work_dir=tmp_path,
        environment="TEST",
        bible={},
        ffmpeg_exe=None,
        registry=None,
        clip_judge=None,
        face_counter=None,
        clip_check=None,
        charged=[],
        bought_now=[],
        over_attempts=lambda _index: False,
        attempts_reason=lambda _index: "",
        sent={},
        scene_dicts={},
        over_renders=lambda _index: True,
    )
    first = SimpleNamespace(index=3, first_qc=None, outcome=None)
    assert rounds._send(first, seed=1, prompt="p") == []
    assert first.outcome["status"] == "NOT_BOUGHT"
    assert "2 randări" in first.outcome["reason"]
    # A refused clip's retry is not sent either; the clip's own verdict stands.
    retry = SimpleNamespace(index=4, first_qc={"verdict": "FAILED"}, outcome=None)
    assert rounds._send(retry, seed=2, prompt="p") == []
    assert retry.outcome is None


def test_two_refused_shots_settle_the_scene_whatever_its_pictures_count(engine, tmp_path):
    """The still had one render, the motion two: the ladder keeps the newest refused shot as
    the scene's clip instead of rewriting words a third shot would be bought on."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    with Session(engine) as session, session.begin():
        _take(session, board, 1, "motion", on_disk=tmp_path / "x.mp4", failure_code="QC.CLIP")
        newest = _take(
            session, board, 1, "motion", on_disk=tmp_path / "y.mp4", failure_code="QC.CLIP"
        )
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            newest,
            1,
            {
                "storyboard_id": board,
                "scene_number": 1,
                "take_id": newest,
                "verdict": "FAILED",
                "passed": False,
                "blocks_ro": ["clipul aproape nu se mișcă"],
                "seed": 7,
            },
            "c",
        )
    assert not stills_stage._at_renders_cap(engine, board, 1)
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film) == []
    assert film["settled_under_cap"] == [1]
    with Session(engine) as session:
        kept = session.get(SceneTake, newest)
        assert kept.status == "PAID" and kept.approved_by == assembler.CAP_APPROVER
        assert clip_qc_of(session, newest)["accepted_under_cap"] is True
        assert renders_cap.renders_made(session, board, 1, "motion") == 2


def test_a_delivery_retry_is_not_released_past_two_renders(engine, tmp_path, studio):
    """The hero's test shot expired at the vendor, undelivered and paid, after an earlier shot
    of it was made: the retry the Director would release is a third render of the motion, and
    it is not released; the paid attempts stay as they are."""
    board, take_id = failed_delivery(engine, tmp_path)
    with Session(engine) as session, session.begin():
        earlier = _take(
            session, board, 1, "test_shot", status="PAID", on_disk=tmp_path / "earlier.mp4"
        )
        expired_at = datetime.fromisoformat(str(session.get(SceneTake, take_id).created_at))
        session.get(SceneTake, earlier).created_at = (expired_at - timedelta(hours=1)).isoformat()
    agents = Agents(
        brief={
            **BRIEF,
            "action": "retry_delivery",
            "diagnosis": "No clip was delivered. This is a terminal delivery error, not visual QC.",
            "summary_ro": "Kael reia livrarea scenei; nu există încă un clip de judecat.",
        }
    )
    result = scene_rewrite.director_ladder(engine, agents_say(studio, agents), board, [1])
    assert result["recovered"] == [] and result["rewritten"] == []
    (outcome,) = result["not_rewritten"]
    assert "2 randări" in str(outcome)
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 1, "motion") == 2
        assert not list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == assembler.DELIVERY_RETRY_EVENT,
                    DomainEvent.aggregate_id == board,
                )
            )
        )
        assert session.get(SceneTake, take_id).status == "REFUSED"


# ------------------------------------------------------------- 4. the holds and the words


def test_the_films_fallback_ceiling_holds_each_still_twice():
    table = load_price_table()
    chosen = SimpleNamespace(film_budget_usd=None, motion_budget_usd=12.0)
    limit, source = film_ceiling_micros(chosen, table)
    # The candidates the sheet prices with, as the suite pins them (tests/conftest.py).
    candidates = shooting_sheet.STILL_CANDIDATES
    per_scene = price_still(STILLS_MODEL, STILLS_RESOLUTION, candidates, table=table)
    assert source == "implicit"
    assert limit == 12_000_000 + credits_to_micros(
        per_scene * 2 * DEFAULT_CEILING_SCENES, table.credit_usd
    )


def test_the_words_say_two(monkeypatch):
    assert renders_ro() == "2 randări" and renders_ro(1) == "o randare"
    assert renders_of_ro("imaginii") == "2 randări ale imaginii"
    assert renders_of_ro("mișcării", 1) == "o randare a mișcării"
    assert times_en() == "twice"
    assert "2 randări ale imaginii" in stills_stage.capped_reason(4)
    assert "2 randări" in motion_capped_reason(5)
    told = [rule for rule in standing_rules() if "made at most" in rule]
    assert told and "at most twice, the first render included" in told[0]
    # The template keeps the place, never a number; another setting is said as it stands.
    assert any("{renders_times}" in rule for rule in STANDING_RULES)
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "3")
    assert "at most 3 times" in next(r for r in standing_rules() if "made at most" in r)


# ------------------------------------------------- 5. the review of f7ba9ee, item by item


def _passed_clip(scene: int) -> ClipReport:
    return ClipReport(
        scene=scene,
        path="clip.mp4",
        checks=(ClipCheck("motion", "PASSED", True, 4.0, ""),),
        passed=True,
        blocks_ro=(),
        warnings_ro=(),
        unmeasured=(),
    )


def _at(session: Session, take_id: str, when: str) -> None:
    """A take's creation time, set: the newest is chosen by it."""
    row = session.get(SceneTake, take_id)
    row.created_at = row.updated_at = when


def test_a_charged_vendor_failure_is_a_render_and_its_retry_is_not_bought_past_the_cap(
    engine, tmp_path
):
    """Scene 2 had one paid refused still. Its next request is accepted (the task is heard)
    and then fails INTERNAL.BAD_OUTPUT: charged, so it is its second render. The technical
    retry the stills step would buy next is a third: it is not bought, and the closest still
    the scene has stands under the cap (review item 1)."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 2, "still", on_disk=tmp_path / "older.png")

    class Failing(SpyStills):
        async def generate_candidates(self, prompt, *, on_submitted=None, **kwargs):
            if SUBJECTS[2] in prompt:
                self.asked.append({"prompt": prompt, **kwargs})
                if on_submitted is not None:
                    on_submitted(f"img-task-bad-{len(self.asked)}")
                raise MediaProviderError("bad output", code="INTERNAL.BAD_OUTPUT")
            return await super().generate_candidates(prompt, on_submitted=on_submitted, **kwargs)

    adapter = Failing()
    result = approved_run(engine, board, tmp_path, adapter, SpyJudge(), face_counter=faces_in())

    assert len([asked for asked in adapter.asked if SUBJECTS[2] in asked["prompt"]]) == 1
    by_index = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_index[2]["status"] == "APPROVED"
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 2, "still") == 2
        kept = session.get(SceneTake, older)
        assert kept.status == "APPROVED" and kept.approved_by == assembler.CAP_APPROVER


@needs_ffmpeg
def test_a_clip_at_the_cap_stops_no_step_and_the_later_scene_is_still_bought(engine, tmp_path):
    """Scenes 2 (seedance, his choice) and 3 (veo) each had one shot on older words: their
    next is their last render and the plan holds no retry for either. Scene 2's clip fails
    clip QC. The renders cap, not the money, refuses its retry: no STOPPED_AT_CAP, scene 3 is
    bought, and scene 2's clip stands under the cap — nothing «Decide Proprietarul» (item 6)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    account = Account(50_000)
    caps = [SEEDANCE, VEO_FAST]
    hero_models = Models(SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account))
    hero_approved(engine, board, tmp_path, hero_models, account, capabilities=caps)
    with Session(engine) as session, session.begin():
        for scene in (2, 3):
            _take(
                session, board, scene, "motion", status="PAID", on_disk=tmp_path / f"o{scene}.mp4"
            )
    overrides = {2: "seedance2_5"}
    plan = motion_plan(engine, board, capabilities=caps, overrides=overrides)
    step = plan["steps"]["motion"]
    assert step["to_buy"] == [2, 3]
    each = {item["scene_index"]: item["credits"] for item in plan["scenes"]}
    assert each[2] > each[3]
    # Neither scene holds a retry: their next shot is their last render.
    assert step["cap_credits"] == each[2] + each[3] + step["round_overhead_credits"]

    def check(path, **kwargs):
        scene = int(kwargs["scene"])
        return _failed_clip(scene) if scene == 2 else _passed_clip(scene)

    seedance, veo = SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account)
    result = approved(
        engine,
        board,
        tmp_path,
        "motion",
        Models(seedance, veo),
        account,
        capabilities=caps,
        overrides=overrides,
        clip_check=check,
    )

    assert not str(result.get("stopped") or "").startswith("STOPPED_AT_CAP")
    scenes = by_scene(result)
    assert scenes[3]["status"] == "PAID" and len(veo.asked) == 1
    assert scenes[2]["status"] == "PAID" and len(seedance.asked) == 1
    assert scenes[2]["clip_qc"]["accepted_under_cap"] is True
    assert "Decide Proprietarul" not in str(scenes[2].get("reason") or "")
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 2, "motion") == 2


def test_the_retry_decision_names_the_cap_before_the_money():
    report = _failed_clip(2)
    capped = clip_retry_decision(
        report,
        seed=7,
        retries_done=0,
        committed_credits=340,
        price_credits=340,
        cap_credits=400,
        renders_left=0,
    )
    assert capped.action == "ESCALATE"
    assert "2 randări ale mișcării" in capped.reason_ro
    assert "plafonul aprobat" not in capped.reason_ro
    assert "Decide Proprietarul" not in capped.reason_ro
    # With a render left, the money decides as before.
    money = clip_retry_decision(
        report,
        seed=7,
        retries_done=0,
        committed_credits=340,
        price_credits=340,
        cap_credits=400,
        renders_left=1,
    )
    assert money.action == "ESCALATE" and "plafonul aprobat de 400" in money.reason_ro


@needs_ffmpeg
def test_a_motion_capped_scene_with_paid_shots_on_older_words_keeps_the_closest(engine, tmp_path):
    """Scene 2's motion had its two renders, both PAID on older words: the plan holds it, and
    the walk's ladder keeps the newest as its clip under the cap, without the Owner — the
    next plan reads it bought (item 7)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "a.mp4")
        newer = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "b.mp4")
        _at(session, older, "2026-10-16T09:00:00+00:00")
        _at(session, newer, "2026-10-16T10:00:00+00:00")
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert scene["status"] == "NEEDS_OWNER" and 2 not in plan["steps"]["motion"]["to_buy"]
    # The stop's words say the scene is the Director's, not his.
    said = stages._held_words(engine, board, "mișcarea", [2])
    assert "decizia Proprietarului" not in said and "2 randări" in said

    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    assert stages._ladder_scenes(engine, board, film) == []
    assert film["settled_under_cap"] == [2]
    with Session(engine) as session:
        kept = session.get(SceneTake, newer)
        assert kept.approved_by == assembler.CAP_APPROVER
        assert clip_qc_of(session, newer)["accepted_under_cap"] is True
        assert session.get(SceneTake, older).approved_by != assembler.CAP_APPROVER
        assert renders_cap.renders_made(session, board, 2, "motion") == 2
    again = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = next(item for item in again["scenes"] if item["scene_index"] == 2)
    assert scene["status"] == "BOUGHT" and scene["take_id"] == newer
    # Settled once: the next walk changes nothing, so it never loops on it.
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    stages._ladder_scenes(engine, board, film)
    assert "settled_under_cap" not in film


@needs_ffmpeg
def test_a_motion_capped_scene_with_no_clip_on_disk_is_moved_locally_by_the_director(
    engine, tmp_path
):
    """Scene 2's two renders were charged and delivered nothing: no clip to keep. The
    Director shows its approved still moved locally (0 credits): the plan reads it LOCAL and
    hers, and the PRODUCTION fallback gate lets the film through (item 7)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        for _ in range(2):
            _take(session, board, 2, "motion", status="REFUSED", failure_code=None, credits=340.0)
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    assert stages._ladder_scenes(engine, board, film) == []
    assert film["settled_under_cap"] == [2]
    with Session(engine) as session:
        assert renders_cap.cap_local_moves(session, board) == {2}
        assert clip_qc.chosen_local_moves(session, board) == {2}
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert scene["status"] == "LOCAL" and scene["decided_by"] == renders_cap.CAP_LOCAL_MOVE_BY
    assert "animată local" in scene["reason_ro"] and "2 randări" in scene["reason_ro"]
    assert 2 not in plan["steps"]["motion"]["to_buy"]
    production = {
        "scenes": [
            {"scene_index": 1, "scene_kind": "LIVE", "motion": {"bytes": 1}},
            {"scene_index": 2, "scene_kind": "LIVE", "motion": None},
            {"scene_index": 3, "scene_kind": "LIVE", "motion": {"bytes": 1}},
        ]
    }
    verdict = clip_qc.require_chosen_fallbacks(engine, board, production, environment="PRODUCTION")
    assert verdict["passed"]


def test_a_clip_too_short_at_the_cap_is_moved_locally_instead_of_redone(engine, tmp_path):
    """The narration came out longer than the clip of a scene whose motion had its two
    renders: the studio's longer-clip proposal buys nothing past the cap, and the Director
    shows the scene's still moved locally so the film is assembled (item 2)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        for name in ("s1.mp4", "s2.mp4"):
            _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / name)
        append_event(
            session,
            assembler.ASSEMBLY_REFUSED_EVENT,
            "storyboard",
            board,
            1,
            {
                "storyboard_id": board,
                "scenes": [
                    {
                        "scene_index": 2,
                        "code": assembler.CLIP_SHORT,
                        "needed_seconds": 9.0,
                        "reason_ro": "Scena 2: clipul este prea scurt.",
                    }
                ],
            },
            "c",
        )
    (outcome,) = assembler.propose_clip_redos(engine, board, "c", wiring={})
    assert outcome["status"] == assembler.RENDERS_CAP
    assert "animată local" in outcome["reason_ro"]
    with Session(engine) as session:
        assert renders_cap.cap_local_moves(session, board) == {2}
        assert renders_cap.renders_made(session, board, 2, "motion") == 2


def test_the_owners_own_press_is_refused_past_the_cap_and_his_plan_says_so(engine, tmp_path):
    """His «Refă imaginea» on a scene whose still was made twice is not priced as a third: the
    plan is not buyable and names the cap and its setting, and the press is refused before
    anything is bought (items 3 and 8)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        _take(session, board, 1, "still", on_disk=tmp_path / "second.png")
        for name in ("m2a.mp4", "m2b.mp4"):
            _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / name)
    plan = assembler.redo_plan(engine, board, "still", 1)
    assert plan["buyable"] is False and plan["renders_capped"] is True
    assert "2 randări" in plan["reason_ro"] and "STUDIO_RENDERS_PER_LAYER" in plan["reason_ro"]
    # A new picture of scene 2 could not be animated: not buyable either.
    animated = assembler.redo_plan(engine, board, "still", 2)
    assert animated["buyable"] is False and "nu mai poate fi animată" in animated["reason_ro"]
    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine, board, str(uuid4()), kind="still", scene_index=1, plan_hash=plan["plan_hash"]
        )
    assert refused.value.status == assembler.RENDERS_CAP
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 1, "still") == 2


@needs_ffmpeg
def test_the_owners_motion_redo_is_not_buyable_after_two_shots(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        for name in ("m2a.mp4", "m2b.mp4"):
            _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / name)
    plan = assembler.redo_plan(engine, board, "motion", 2, capabilities=[SEEDANCE])
    assert plan["buyable"] is False and plan["renders_capped"] is True
    assert "2 randări" in plan["reason_ro"]
    with pytest.raises(SceneRedoRefused) as refused:
        redo_scene(
            engine,
            board,
            str(uuid4()),
            kind="motion",
            scene_index=2,
            plan_hash=plan["plan_hash"],
            capabilities=[SEEDANCE],
        )
    assert refused.value.status == assembler.RENDERS_CAP


def test_a_scene_at_the_still_cap_keeps_a_still_approved_on_older_words(engine, tmp_path):
    """Scene 3's words were rewritten after its still was approved; a request on the new words
    was charged and left nothing. At the cap the approved still on the older words is the
    closest the scene has: it stands, nothing is bought and nobody waits (item 7, stills)."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        approved_before = _take(
            session, board, 3, "still", status="APPROVED", on_disk=tmp_path / "older.png"
        )
        _take(
            session,
            board,
            3,
            "still",
            status="REFUSED",
            failure_code=None,
            credits=float(price_still(STILLS_MODEL, STILLS_RESOLUTION, 1)),
        )
    _bible, scenes = stills_stage._read_scenes(engine, board)
    three = next(scene for scene in scenes if scene.index == 3)
    assert three.reuse is not None and three.reuse.id == approved_before
    assert three.reuse.approved_by == assembler.CAP_APPROVER
    assert 3 not in stills_stage.stills_plan(engine, board)["to_buy"]
    # A scene with nothing at all on disk waits, and his press is no promise any more.
    assert "apăsată de el" not in stills_stage.capped_reason(3)
    assert "STUDIO_RENDERS_PER_LAYER" in stills_stage.capped_reason(3)


def test_the_directors_letter_names_the_renders_cap_and_its_setting():
    """A scene her repair did not buy because a layer had its renders is said with the cap
    and STUDIO_RENDERS_PER_LAYER, never as a paid-redo limit he never set (item 9)."""
    (line,) = stages._repair_lines(
        {
            "limited": [
                {
                    "scene_index": 5,
                    "per_scene": 1,
                    "per_film": 20,
                    "renders": {"still": 2},
                    "renders_cap": 2,
                    "report_rounds": 0,
                    "report_rounds_cap": 2,
                    "per_scene_setting": renders_cap.ENV_NAME,
                }
            ]
        }
    )
    assert "imaginea ei a avut deja 2 randări" in line
    assert "STUDIO_RENDERS_PER_LAYER" in line
    assert "STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE" not in line
    # A per-scene limit he did not set is said from the cap's own setting.
    (per_scene,) = stages._repair_lines(
        {
            "limited": [
                {
                    "scene_index": 4,
                    "per_scene": 1,
                    "per_film": 20,
                    "renders": {},
                    "per_scene_setting": renders_cap.paid_redos_setting(
                        SimpleNamespace(film_max_paid_redos_per_scene=None)
                    ),
                }
            ]
        }
    )
    assert "(STUDIO_RENDERS_PER_LAYER, STUDIO_FILM_MAX_PAID_REDOS)" in per_scene
    assert (
        renders_cap.paid_redos_setting(SimpleNamespace(film_max_paid_redos_per_scene=0))
        == "STUDIO_FILM_MAX_PAID_REDOS_PER_SCENE"
    )


def test_the_writer_eval_fingerprint_follows_what_the_writers_are_told(monkeypatch):
    """The standing rules say the cap from the setting: two settings, two identities (item 5)."""
    from app.evals import variants

    told_twice = variants.fingerprint("serial")["identity_sha256"]
    monkeypatch.setenv("STUDIO_RENDERS_PER_LAYER", "3")
    told_three = variants.fingerprint("serial")["identity_sha256"]
    assert told_twice != told_three
    assert "app.agents.identity.standing_rules()" in variants.fingerprint("serial")["parts"]


# ------------------------------------- the review of a079fac: whose stop, and his own «Respinge»


def _held_for_him(engine, board: str, scene: int) -> None:
    """The motion step left ``scene`` to the Owner after one charged request the vendor never
    answered: one render of its motion, one left, the step's hold on its identity."""
    with Session(engine) as session, session.begin():
        refused = _take(session, board, scene, "motion", status="REFUSED", credits=340.0)
        row = session.get(SceneTake, refused)
        row.failure_code = assembler.UNANSWERED_FAILURE_CODE
        row.failure_detail = "Furnizorul nu a răspuns."
    state = assembler._motion_state(engine, board, capabilities=[SEEDANCE])
    with Session(engine) as session, session.begin():
        append_event(
            session,
            assembler.MOTION_HOLD_EVENT,
            "storyboard",
            board,
            1,
            {
                "scene_number": scene,
                "status": "NEEDS_OWNER",
                "failure_kind": "UNANSWERED",
                "reason": f"Scena {scene}: furnizorul nu a răspuns.",
                "identity": assembler.identity_key(state["fields"][scene]),
                "holds": True,
            },
            "c",
        )


@needs_ffmpeg
def test_a_motion_left_to_him_with_a_render_left_is_his_though_its_still_had_two(engine, tmp_path):
    """Scene 2's still was made twice (refused once, then approved: the normal path); its
    motion had one render and was left to the Owner. The cap stopped nothing here: the stop's
    words say the scene waits for him, the ladder settles nothing, and his letter is not
    written with «nu se mai cumpără nimic pentru ea» (review of a079fac, item 1)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        _take(session, board, 2, "still", on_disk=tmp_path / "older.png")
    _held_for_him(engine, board, 2)
    with Session(engine) as session:
        assert renders_cap.at_cap(session, board, 2, "still")
        assert renders_cap.renders_made(session, board, 2, "motion") == 1
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert scene["status"] == "NEEDS_OWNER" and 2 in plan["steps"]["motion"]["held"]

    said = stages._held_words(engine, board, stages.STEP_WORDS["motion"], [2])
    assert "scena 2 așteaptă decizia Proprietarului pe foaia de filmare" in said
    assert "plafonului" not in said and "nu se mai cumpără nimic" not in said
    assert said.endswith("nu se cumpără din nou până nu decide el.")
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2], "step": "motion"}
    assert stages._ladder_scenes(engine, board, film) == []
    assert "settled_under_cap" not in film
    assert not stages._ladders_stop(engine, board, film)


def test_a_scene_held_at_the_cap_with_nothing_to_keep_is_not_said_to_be_kept(engine, tmp_path):
    """Scene 3's two still renders were charged and left nothing on disk: the stills step
    holds it with the cap's own reason. Nothing can stand for it, so the stop does not say
    the Director keeps what is closest (review of a079fac, item 1)."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        for _ in range(2):
            _take(
                session,
                board,
                3,
                "still",
                status="REFUSED",
                failure_code=None,
                credits=float(price_still(STILLS_MODEL, STILLS_RESOLUTION, 1)),
            )
    _bible, scenes = stills_stage._read_scenes(engine, board)
    three = next(scene for scene in scenes if scene.index == 3)
    assert three.reuse is None and "STUDIO_RENDERS_PER_LAYER" in three.hold_ro
    assert not stills_stage.settle_scene_under_cap(engine, board, 3, "c")
    said = stages._held_words(engine, board, stages.STEP_WORDS["stills"], [3])
    assert "Directoarea păstrează" not in said and "decizia Proprietarului" in said


@needs_ffmpeg
def test_clips_the_owner_rejected_are_never_kept_under_the_cap(engine, tmp_path):
    """Scene 2's motion had its two renders and the Owner rejected both clips on the sheet
    («Are o față.»). Past the cap the Director keeps what is closest, but never a clip he
    turned down: neither is re-marked or cut into the film, and the scene is shown as its
    approved still moved locally, 0 credits. Scene 3's newer clip he rejected, its older one
    quality control refused: the older one is the closest (review of a079fac, item 2)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "a.mp4")
        newer = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "b.mp4")
        _at(session, older, "2026-10-16T09:00:00+00:00")
        _at(session, newer, "2026-10-16T10:00:00+00:00")
        refused_by_qc = _take(
            session, board, 3, "motion", on_disk=tmp_path / "c.mp4", failure_code="QC.CLIP"
        )
        his_three = _take(session, board, 3, "motion", status="PAID", on_disk=tmp_path / "d.mp4")
        _at(session, refused_by_qc, "2026-10-16T09:00:00+00:00")
        _at(session, his_three, "2026-10-16T10:00:00+00:00")
    for take_id in (older, newer, his_three):
        assembler.decide_take(
            engine, take_id, "REJECTED", decided_by=assembler.TAKE_DECIDER, note="Are o față."
        )
    film = {"status": "WAITING", "refusal": "TAKES_NOT_ACCEPTED", "scenes": [2, 3]}
    assert stages._ladder_scenes(engine, board, film) == []
    assert sorted(film["settled_under_cap"]) == [2, 3]
    with Session(engine) as session:
        for take_id in (older, newer, his_three):
            row = session.get(SceneTake, take_id)
            assert row.status == "REJECTED" and row.failure_code == "OWNER.REJECTED"
            assert row.approved_by != assembler.CAP_APPROVER
            assert (clip_qc_of(session, take_id) or {}).get("accepted_under_cap") is not True
        kept = session.get(SceneTake, refused_by_qc)
        assert kept.status == "PAID" and kept.approved_by == assembler.CAP_APPROVER
        assert renders_cap.cap_local_moves(session, board) == {2}
    reading = assembler.scene_readiness(engine, board, 2, environment="PRODUCTION")
    assert reading is not None and reading.get("take_id") not in (older, newer)
    assert not assembler._cuts_a_clip(reading)
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    two = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert two["status"] == "LOCAL" and two["decided_by"] == renders_cap.CAP_LOCAL_MOVE_BY
    three = next(item for item in plan["scenes"] if item["scene_index"] == 3)
    assert three["status"] == "BOUGHT" and three["take_id"] == refused_by_qc


def test_a_still_the_owner_rejected_is_never_approved_again_under_the_cap(engine, tmp_path):
    """Scene 2's motion had its two renders, and the Owner then rejected its still on the
    sheet. No new picture can be animated, but the one he turned down is not approved again
    under the cap, by the stills step nor by the walk's ladder: the scene waits for him
    (review of a079fac, item 2, the still's side)."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        for name in ("m2a.mp4", "m2b.mp4"):
            _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / name)
        still = session.scalar(
            select(SceneTake.id).where(
                SceneTake.storyboard_id == board,
                SceneTake.scene_number == 2,
                SceneTake.kind == "still",
            )
        )
    assembler.decide_take(
        engine, still, "REJECTED", decided_by=assembler.TAKE_DECIDER, note="Nu e scena."
    )
    _bible, scenes = stills_stage._read_scenes(engine, board)
    two = next(scene for scene in scenes if scene.index == 2)
    assert two.reuse is None and two.hold_ro and "respins" in two.hold_ro
    assert not stills_stage.settle_scene_under_cap(engine, board, 2, "c")
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    stages._ladder_scenes(engine, board, film)
    assert "settled_under_cap" not in film
    with Session(engine) as session:
        row = session.get(SceneTake, still)
        assert row.status == "REJECTED" and row.failure_code == "OWNER.REJECTED"
        assert row.approved_by != assembler.CAP_APPROVER
    said = stages._held_words(engine, board, stages.STEP_WORDS["stills"], [2])
    assert "Directoarea păstrează" not in said and "decizia Proprietarului" in said
