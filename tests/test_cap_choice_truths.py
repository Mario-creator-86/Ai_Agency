"""Past the renders cap the words tell what really happened (the dishonest-code audit of
2026-10-16, track 1).

The Owner, 2026-10-15: past the cap «the Director looks at what exists and picks the closest
to the plan». The studio said so on every route while the code kept the newest file and nobody
looked (STUB-001); a clip kept under the cap was recorded as a clip-QC pass and closed the
Director's motion items (STUB-003); film QC listed her local moves as the Owner's (STUB-004);
and a still whose file was no longer the one bought was «settled» again on every walk
(SAFE-013, its first half; the walk's bound is tests/test_free_walks_bounded.py). Every model,
vendor and look is faked here: nothing is bought and no model is called.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.agents import reviews
from app.agents.identity import PROFILE_BARE, standing_rules, task_context
from app.media import assembler, cap_choice, director_qc, fix_check, renders_cap, stills_stage
from app.media import qc as clip_qc
from app.media.assembler import CAP_APPROVER, CAP_VERDICT, CLIP_QC_EVENT, clip_qc_of, motion_plan
from app.media.models import SceneTake
from app.models import DomainEvent
from app.runbook import stages
from app.services import append_event
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE
from test_film_costing import a_film as a_film_with_stills
from test_renders_cap import _at, _take
from test_stills_stage import a_film as a_film_to_buy

pytestmark = pytest.mark.renders_per_layer(2)


class Registry:
    """A model registry with one model registered: the look may be asked (and is faked)."""

    def registered_ids(self) -> list[str]:
        return ["a-model-that-sees"]


class Look:
    """The Director's look past the cap, faked: records what she was shown and answers."""

    def __init__(self, answer: dict[str, Any] | Exception | None = None):
        self.answer = answer
        self.asked: list[dict[str, Any]] = []

    def __call__(self, engine, registry, shown, images, correlation_id=None, **kwargs):
        self.asked.append({"shown": shown, "images": list(images), **kwargs})
        if isinstance(self.answer, Exception):
            raise self.answer
        if self.answer is None:
            raise AssertionError("nobody may be asked here")
        return {
            "agent_id": "sarah",
            "agent_name": "Sarah",
            "run_id": "run-1",
            "model": "a-model-that-sees",
            **self.answer,
        }


@pytest.fixture
def eyes(monkeypatch):
    """Every take can be shown: one picture per still, three frames per clip."""
    monkeypatch.setattr(director_qc, "no_picture", lambda row, ffmpeg: None)
    monkeypatch.setattr(
        director_qc,
        "look_pictures",
        lambda row, ffmpeg_path, work_dir: (
            [f"still:{row.id}"] if row.kind == "still" else [f"f{n}:{row.id}" for n in range(3)]
        ),
    )


def _choices(engine, board: str) -> list[dict[str, Any]]:
    with Session(engine) as session:
        return [
            dict(event.payload)
            for event in session.scalars(
                select(DomainEvent)
                .where(
                    DomainEvent.event_type == cap_choice.CAP_CHOICE_EVENT,
                    DomainEvent.aggregate_id == board,
                )
                .order_by(DomainEvent.sequence)
            )
        ]


# ----------------------------------------------- STUB-001: she looks, and the words say so


def test_past_the_still_cap_the_director_chooses_among_the_stills_and_it_is_recorded(
    engine, tmp_path, monkeypatch, eyes
):
    """Scene 1 had its two stills, both refused. Past the cap she is shown both, against the
    scene's plan, in ONE look, and the one she chooses — the older one here, never simply the
    newest — is the scene's picture; her choice is an event with her reason and her run."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 1, "still", on_disk=tmp_path / "older.png")
        newer = _take(session, board, 1, "still", on_disk=tmp_path / "newer.png")
        _at(session, older, "2026-10-16T09:00:00+00:00")
        _at(session, newer, "2026-10-16T10:00:00+00:00")
    look = Look({"decision": "CHOOSE", "candidate": 2, "reason": "Biroul e larg, ca în plan."})
    monkeypatch.setattr(reviews, "review_bought_pictures", look)

    assert stills_stage.settle_scene_under_cap(engine, board, 1, "c", registry=Registry())

    (asked,) = look.asked
    assert asked["cap"] is True and asked["storyboard_id"] == board
    shown = asked["shown"]
    assert shown["kind"] == "still" and shown["past_the_renders_cap"] is True
    assert [item["candidate"] for item in shown["candidates"]] == [1, 2]
    assert shown["scene"]["picture_prompt"]  # judged against the scene's plan
    assert asked["images"] == [f"still:{newer}", f"still:{older}"]
    with Session(engine) as session:
        kept = session.get(SceneTake, older)
        assert kept.status == "APPROVED" and kept.approved_by == CAP_APPROVER
        assert session.get(SceneTake, newer).status == "REJECTED"
    (choice,) = _choices(engine, board)
    assert choice["take_id"] == older and choice["layer"] == "still"
    assert choice["chosen_by"] == "director" and choice["how"] == cap_choice.LOOKED
    assert choice["run_id"] == "run-1" and choice["reason_ro"] == "Biroul e larg, ca în plan."
    assert choice["candidates"] == [newer, older]
    assert choice["previous"]["status"] == "REJECTED" and choice["previous"]["failure_detail"]
    assert "Directoarea a privit 2 imagini ale scenei 1" in choice["words_ro"]
    # Settled once: the next walk changes nothing and asks her nothing again.
    look.answer = None
    assert not stills_stage.settle_scene_under_cap(engine, board, 1, "c", registry=Registry())


def test_a_reading_of_the_plan_asks_nobody_and_holds_a_scene_with_stills_to_choose_from(
    engine, tmp_path, monkeypatch
):
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        _take(session, board, 2, "still", on_disk=tmp_path / "a.png")
        _take(session, board, 2, "still", on_disk=tmp_path / "b.png")
    monkeypatch.setattr(reviews, "review_bought_pictures", Look(None))
    plan = stills_stage.stills_plan(engine, board)
    two = next(scene for scene in plan["scenes"] if scene["scene_index"] == 2)
    assert 2 in plan["held"] and 2 not in plan["to_buy"]
    assert "Directoarea alege dintre cele 2 imagini" in two["reason_ro"]


def test_with_one_still_it_stays_with_no_look_and_the_words_say_so(engine, tmp_path, monkeypatch):
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        only = _take(session, board, 1, "still", on_disk=tmp_path / "only.png")
        # A second request charged that left nothing on disk.
        _take(session, board, 1, "still", status="REFUSED", failure_code=None, credits=10.0)
    monkeypatch.setattr(reviews, "review_bought_pictures", Look(None))

    assert stills_stage.settle_scene_under_cap(engine, board, 1, "c", registry=Registry())

    (choice,) = _choices(engine, board)
    assert choice["take_id"] == only and choice["how"] == cap_choice.ONLY_ONE
    assert choice["chosen_by"] == "studio"
    assert choice["words_ro"] == (
        "Scena 1 are o singură imagine pe disc care poate rămâne; rămâne aceasta, fără nicio "
        "alegere."
    )
    assert "Directoarea" not in choice["words_ro"]


def test_when_she_cannot_look_the_studio_keeps_one_qc_passed_and_says_it_was_the_studio(
    engine, tmp_path, monkeypatch, eyes
):
    """No model that sees: the studio keeps its own pick — the runner-up the gate passed,
    before the newer still it refused — and the note and the event say the studio kept it."""
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        passed = _take(session, board, 1, "still", status="PAID", on_disk=tmp_path / "p.png")
        refused = _take(session, board, 1, "still", on_disk=tmp_path / "r.png")
        _at(session, passed, "2026-10-16T09:00:00+00:00")
        _at(session, refused, "2026-10-16T10:00:00+00:00")
    blind = Look(reviews.ReviewError("niciun model al studioului nu vede imagini"))
    monkeypatch.setattr(reviews, "review_bought_pictures", blind)

    assert stills_stage.settle_scene_under_cap(engine, board, 1, "c", registry=Registry())

    assert len(blind.asked) == 1
    (choice,) = _choices(engine, board)
    assert choice["take_id"] == passed
    assert choice["chosen_by"] == "studio" and choice["how"] == cap_choice.FALLBACK
    assert choice["words_ro"].startswith("Studioul a păstrat o imagine din cele 2 imagini")
    assert "întâi una trecută de control, apoi cea mai nouă" in choice["words_ro"]
    assert "Directoarea nu a ales: niciun model al studioului nu vede imagini" in choice["words_ro"]


def test_past_the_motion_cap_she_chooses_among_the_clips_by_their_frames(
    engine, tmp_path, monkeypatch, eyes
):
    """Scene 2's motion had its two renders, both clips on older words: past the cap she is
    shown each clip's three frames and chooses; the clip she chose is the scene's shot."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "a.mp4")
        newer = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "b.mp4")
        _at(session, older, "2026-10-16T09:00:00+00:00")
        _at(session, newer, "2026-10-16T10:00:00+00:00")
    look = Look({"decision": "CHOOSE", "candidate": 2, "reason": "Mișcarea e cea din plan."})
    monkeypatch.setattr(reviews, "review_bought_pictures", look)

    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    assert stages._ladder_scenes(engine, board, film, registry=Registry()) == []

    assert film["settled_under_cap"] == [2]
    (asked,) = look.asked
    assert asked["cap"] is True and asked["shown"]["kind"] == "shot"
    assert asked["images"] == [
        *(f"f{n}:{newer}" for n in range(3)),
        *(f"f{n}:{older}" for n in range(3)),
    ]
    with Session(engine) as session:
        assert session.get(SceneTake, older).approved_by == CAP_APPROVER
        assert session.get(SceneTake, newer).approved_by != CAP_APPROVER
        record = clip_qc_of(session, older)
    assert record["accepted_under_cap"] is True and record["chosen_by"] == "director"
    assert "Directoarea a privit 2 clipuri ale scenei 2" in record["cap_note_ro"]
    (choice,) = _choices(engine, board)
    assert choice["take_id"] == older and choice["layer"] == "motion"
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    two = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert two["status"] == "BOUGHT" and two["take_id"] == older


def test_her_look_past_the_cap_is_its_own_bare_task_and_must_choose(engine, monkeypatch):
    """Her look past the cap is `director_cap_choice` (the BARE context), told that REJECT is
    not an answer, and an answer that rejects them all does not validate."""
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    assert task_context(reviews.DIRECTOR_CAP_CHOICE_TASK).profile == PROFILE_BARE
    schema = reviews.look_schema(2, must_choose=True)
    with pytest.raises(ValueError):
        schema.model_validate({"decision": "REJECT", "reason": "niciuna"})
    assert schema.model_validate({"decision": "CHOOSE", "candidate": 2, "reason": "a doua"})
    with pytest.raises(ValueError):
        schema.model_validate({"decision": "CHOOSE", "candidate": 3, "reason": "a treia"})

    asked: dict[str, Any] = {}

    def structured_run(engine, registry, agent_id, task, prompt, version, corr, model, *a, **k):
        asked.update(task=task, prompt=prompt, version=version, model=model, extra=k.get("extra"))
        return (
            model.model_validate({"decision": "CHOOSE", "candidate": 1, "reason": "x"}),
            {
                "id": str(uuid4()),
                "status": "COMPLETED",
            },
            None,
        )

    monkeypatch.setattr("app.agents.structured.structured_run", structured_run)
    monkeypatch.setattr("app.agents.vision.seeing_model", lambda session, agent, *looks: None)
    shown = {"film": "F", "kind": "shot", "scene": {"scene_index": 4}, "candidates": [{}, {}]}
    with pytest.raises(reviews.ReviewError):  # nobody's model sees: nothing is chosen
        reviews.review_bought_pictures(engine, Registry(), shown, ["a", "b"], "c", cap=True)

    from app.agents.models import ModelRecord

    with Session(engine) as session:
        any_model = session.scalars(select(ModelRecord.id)).first()
    monkeypatch.setattr("app.agents.vision.seeing_model", lambda session, agent, *looks: any_model)
    answer = reviews.review_bought_pictures(engine, Registry(), shown, ["a", "b"], "c", cap=True)
    assert answer["decision"] == "CHOOSE" and answer["candidate"] == 1
    assert asked["task"] == "director_cap_choice"
    assert asked["version"] == reviews.DIRECTOR_CAP_CHOICE_TEMPLATE_VERSION
    assert "REJECT is not an answer here" in asked["prompt"]
    assert "three frames per candidate" in asked["prompt"]
    assert asked["extra"] == {"images": ["a", "b"]}


def test_no_sentence_says_the_director_chose_what_the_studio_kept():
    """Every text the audit listed says what happens past the cap: she chooses among several
    takes when she can look, else the studio keeps its pick; one take stays."""
    said = [
        assembler.motion_capped_reason(3),
        clip_qc.clip_capped_words(3),
        renders_cap.cap_local_move_words(3),
        stages._limited_line({"scene_index": 3, "renders": {"motion": 2}, "renders_cap": 2}),
        *standing_rules(),
    ]
    for text in said:
        assert "Directoarea alege cel mai apropiat" not in text
        assert "Directoarea păstrează" not in text
        assert "cel mai apropiat de plan, iar filmul" not in text
        assert "looks at everything the scene has" not in text
    assert cap_choice.CAP_KEEPS_RO in said[0] and cap_choice.CAP_KEEPS_RO in said[1]
    rule = next(text for text in standing_rules() if "made at most" in text)
    assert "when she cannot look, the studio keeps one quality control passed" in rule
    assert "with one take, that one stays" in rule


# ----------------------------------------------------- STUB-003: a kept clip is not a pass


def test_a_clip_kept_under_the_cap_is_not_a_pass_and_closes_none_of_her_items(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        refused = _take(
            session, board, 2, "motion", on_disk=tmp_path / "r.mp4", failure_code="QC.CLIP"
        )
        _take(session, board, 2, "motion", status="REFUSED", failure_code=None, credits=340.0)
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            refused,
            1,
            {
                "storyboard_id": board,
                "scene_number": 2,
                "take_id": refused,
                "verdict": "FAILED",
                "passed": False,
                "blocks_ro": ["o fereastră în laboratorul fără ferestre"],
            },
            "c",
        )
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [2]}
    assert stages._ladder_scenes(engine, board, film) == []
    with Session(engine) as session:
        record = clip_qc_of(session, refused)
        take = session.get(SceneTake, refused)
        assert record["verdict"] == CAP_VERDICT and record["passed"] is False
        assert record["qc_verdict"] == "FAILED" and record["accepted_under_cap"] is True
        assert "Scena 2 are un singur clip pe disc" in record["cap_note_ro"]
        # The film may use it, as before ...
        assert assembler.clip_accepted(session, take, "PRODUCTION") == (True, "")
        assert assembler.clip_kept(record)
        # ... but it closes none of the Director's motion items, and ranks as no pass.
        assert not fix_check._passing_clip_after(session, board, 2, "2000-01-01T00:00:00")
        assert assembler._cap_shot_candidates(session, board, 2)[0].id == refused
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    two = next(item for item in plan["scenes"] if item["scene_index"] == 2)
    assert two["status"] == "BOUGHT" and two["take_id"] == refused


def test_a_real_pass_ranks_before_a_clip_only_kept_under_the_cap(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        passed = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "p.mp4")
        kept = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "k.mp4")
        _at(session, passed, "2026-10-16T09:00:00+00:00")
        _at(session, kept, "2026-10-16T10:00:00+00:00")
        for take_id, verdict in ((passed, "PASSED"), (kept, CAP_VERDICT)):
            append_event(
                session,
                CLIP_QC_EVENT,
                "scene_take",
                take_id,
                1,
                {"storyboard_id": board, "scene_number": 2, "take_id": take_id, "verdict": verdict},
                "c",
            )
    with Session(engine) as session:
        ranked = [row.id for row in assembler._cap_shot_candidates(session, board, 2)]
    assert ranked == [passed, kept]


def test_the_register_says_a_kept_clip_did_not_pass(engine):
    from test_events_feed import TITLE, page, record, studio

    ids = studio(engine)
    record(
        engine,
        "media.clip_qc_checked",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "scene_number": 3,
            "take_id": str(uuid4()),
            "attempt": 2,
            "scene": 3,
            "passed": False,
            "verdict": CAP_VERDICT,
            "qc_verdict": "FAILED",
            "accepted_by": CAP_APPROVER,
            "accepted_under_cap": True,
            "chosen_by": "director",
            "blocks_ro": ["o față"],
        },
    )
    clip = page(engine)["media.clip_qc_checked"]
    assert clip["words_ro"] == (
        f"Clipul scenei 3 din «{TITLE}» nu a trecut controlul, dar rămâne sub plafonul de "
        "randări: Directoarea l-a ales."
    )
    assert "a trecut controlul ✓" not in str(clip.get("bubble_ro"))


# -------------------------------------------- STUB-004: her local moves are not his choices


def test_film_qc_records_her_cap_moves_apart_from_his_choices(engine, tmp_path):
    production = {
        "scenes": [
            {"scene_index": 1, "scene_kind": "LIVE", "motion": None},
            {"scene_index": 2, "scene_kind": "LIVE", "motion": None},
            {"scene_index": 3, "scene_kind": "LIVE", "motion": None},
        ]
    }
    verdict = clip_qc.fallback_verdict(
        production, environment="PRODUCTION", owner_choices={1}, cap_choices={2}
    )
    assert verdict["owner_chosen"] == [1] and verdict["director_cap_chosen"] == [2]
    assert verdict["unchosen"] == [3] and verdict["passed"] is False
    assert "Directoarea a mutat-o local după plafonul de randări" in verdict["reason_ro"]

    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        for _ in range(2):
            _take(session, board, 2, "motion", status="REFUSED", failure_code=None, credits=340.0)
        renders_cap.record_cap_local_move(session, board, 2, "c")
    gate = clip_qc.require_chosen_fallbacks(
        engine,
        board,
        {"scenes": [{"scene_index": 2, "scene_kind": "LIVE", "motion": None}]},
        environment="PRODUCTION",
    )
    assert gate["passed"] and gate["owner_chosen"] == [] and gate["director_cap_chosen"] == [2]


# ------------------- SAFE-013 (its first half): a still that cannot stand is never settled


def test_a_still_whose_file_changed_is_not_settled_again_and_again(engine, tmp_path):
    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        changed = _take(session, board, 1, "still", on_disk=tmp_path / "changed.png")
        _take(session, board, 1, "still", status="REFUSED", failure_code=None, credits=10.0)
    Path(tmp_path / "changed.png").write_bytes(b"another picture since")
    assert stills_stage._at_renders_cap(engine, board, 1)
    assert not stills_stage.settle_scene_under_cap(engine, board, 1, "c")
    with Session(engine) as session:
        assert session.get(SceneTake, changed).status == "REJECTED"


# ----------------------- the review of this fix (2026-10-16): her choice of an earlier still


class ChooseTake(Look):
    """Her look past the cap, faked: she chooses the take whose picture is ``image``, wherever
    it was shown."""

    def __init__(self, image: str):
        super().__init__({"decision": "CHOOSE", "reason": "Cea din runda trecută e mai aproape."})
        self.image = image

    def __call__(self, engine, registry, shown, images, correlation_id=None, **kwargs):
        self.answer = {**dict(self.answer or {}), "candidate": list(images).index(self.image) + 1}
        return super().__call__(engine, registry, shown, images, correlation_id, **kwargs)


def _her_second_look_confirms(monkeypatch) -> None:
    """Her second look confirms every refusal, and her reading of older briefs is a no-op."""
    monkeypatch.setattr(
        stills_stage,
        "_director_looks",
        lambda *a, **k: stills_stage._RoundEnd(confirmed=["Directoarea confirmă refuzul."]),
    )
    monkeypatch.setattr(fix_check, "read_film_reasons", lambda *a, **k: None)


def test_her_choice_of_an_earlier_rounds_still_is_the_scenes_picture_and_figure_one(
    engine, tmp_path, monkeypatch, eyes
):
    """Scene 1 had a still refused in an earlier round. This round buys its second render,
    the gate refuses both candidates and her second look confirms it; past the cap she chooses
    the EARLIER round's still. It is the scene's picture and the film's Figure 1, and the rest
    of the film is bought with it. Until the review of this fix the round had no report for
    that still and the step fell over on ``outcome['status']`` after the round was paid for."""
    from test_approvals import answer
    from test_stills_stage import FACE, NO_FACE, SUBJECTS, SpyJudge, SpyStills, faces_in

    board = a_film_to_buy(engine, tmp_path)
    with Session(engine) as session, session.begin():
        older = _take(session, board, 1, "still", on_disk=tmp_path / "older.png")
        _at(session, older, "2026-10-16T09:00:00+00:00")
    older_bytes = (tmp_path / "older.png").read_bytes()
    _her_second_look_confirms(monkeypatch)
    look = ChooseTake(f"still:{older}")
    monkeypatch.setattr(reviews, "review_bought_pictures", look)
    adapter = SpyStills(
        pictures=lambda prompt, call: [FACE, FACE] if SUBJECTS[1] in prompt else list(NO_FACE)
    )

    def go() -> dict[str, Any]:
        return stills_stage.run_stills_stage(
            engine,
            board,
            str(uuid4()),
            plan_hash=stills_stage.stills_plan(engine, board)["plan_hash"],
            image_adapter=adapter,
            registry=Registry(),
            judge=SpyJudge(),
            face_counter=faces_in(),
            measure=("faces",),
            storage_root=tmp_path / "media",
        )

    with pytest.raises(stills_stage.StillsStageRefused) as asked:
        go()
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    (shown,) = look.asked
    with Session(engine) as session:
        this_round = [
            row.id
            for row in session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == board,
                    SceneTake.scene_number == 1,
                    SceneTake.id != older,
                )
            )
        ]
    # The round's measured still first (the studio's own pick), then the earlier round's.
    assert shown["images"] == [*(f"still:{take}" for take in this_round), f"still:{older}"]
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["status"] == "APPROVED" and by_scene[1]["take_id"] == older
    assert by_scene[1]["approved_by"] == CAP_APPROVER
    with Session(engine) as session:
        assert session.get(SceneTake, older).status == "APPROVED"
    (choice,) = _choices(engine, board)
    assert choice["take_id"] == older and choice["chosen_by"] == "director"
    # The rest of the film is bought, each request carrying the still she chose as Figure 1.
    later = [call for call in adapter.asked if SUBJECTS[1] not in call["prompt"]]
    assert len(later) == 3 and all(call["references"] == [older_bytes] for call in later)
    assert all(by_scene[n]["status"] == "APPROVED" for n in (2, 3, 4))


def test_a_collected_round_settled_on_an_earlier_still_is_approved_not_refused(
    engine, tmp_path, monkeypatch, eyes
):
    """The free settle of what was bought: scene 1's second render was collected and refused,
    and past the cap she chooses the still of its first render. The scene is APPROVED with
    that still, never reported as «judecate și respinse»."""
    import hashlib

    from test_stills_stage import FACE, SpyJudge, faces_in

    board = a_film_to_buy(engine, tmp_path)
    _bible, scenes = stills_stage._read_scenes(engine, board)
    identity = next(scene for scene in scenes if scene.index == 1).identity
    with Session(engine) as session, session.begin():
        older = _take(session, board, 1, "still", on_disk=tmp_path / "older.png")
        _at(session, older, "2026-10-16T09:00:00+00:00")
        collected = _take(
            session,
            board,
            1,
            "still",
            status="PAID",
            on_disk=tmp_path / "collected.jpg",
            prompt_hash=assembler.take_hash(identity, stills_stage.STILLS_MODEL),
        )
        (tmp_path / "collected.jpg").write_bytes(FACE.read_bytes())
        row = session.get(SceneTake, collected)
        row.sha256 = hashlib.sha256(FACE.read_bytes()).hexdigest()
        row.failure_code = assembler.UNJUDGED_FAILURE_CODE
        row.failure_detail = assembler.UNJUDGED_DETAIL
        _at(session, collected, "2026-10-16T10:00:00+00:00")
    _her_second_look_confirms(monkeypatch)
    monkeypatch.setattr(reviews, "review_bought_pictures", ChooseTake(f"still:{older}"))

    summary = stills_stage.settle_stills(
        engine,
        board,
        "c",
        image_adapter=None,
        registry=Registry(),
        judge=SpyJudge(),
        face_counter=faces_in(),
        measure=("faces",),
    )

    (one,) = [entry for entry in summary["scenes"] if entry["scene_index"] == 1]
    assert one["status"] == "APPROVED" and one["take_id"] == older, one
    assert one["approved_by"] == CAP_APPROVER and one["credits"] == 0
    with Session(engine) as session:
        assert session.get(SceneTake, older).status == "APPROVED"
        assert session.get(SceneTake, collected).status == "REJECTED"


def test_the_runpod_rounds_take_figure_one_from_a_still_of_an_earlier_round(tmp_path, monkeypatch):
    """The RunPod rounds read the round's end as the other buyers do: a still kept under the
    cap from an earlier round (no report in this one) is APPROVED and gives Figure 1 its
    file."""
    from types import SimpleNamespace

    picture = tmp_path / "older.png"
    picture.write_bytes(b"the still of an earlier round")
    end = stills_stage._RoundEnd(take_id="older", approved_by=CAP_APPROVER, path=str(picture))
    monkeypatch.setattr(stills_stage, "_settle_round", lambda *a, **k: end)
    rounds = SimpleNamespace(
        engine=None,
        registry=None,
        storyboard_id="b",
        correlation_id="c",
        first_live=1,
        figure_one=None,
    )
    state = SimpleNamespace(
        scene=SimpleNamespace(index=1), verdicts=[], rerolls=0, outcome=None, entry={}
    )

    assert stills_stage._StillRounds._settled(rounds, state) is None

    assert state.outcome["status"] == "APPROVED" and state.outcome["take_id"] == "older"
    assert state.outcome["approved_by"] == CAP_APPROVER
    assert rounds.figure_one == b"the still of an earlier round"


def test_every_buyer_reads_an_approved_round_by_its_take_not_by_its_report():
    """The paid still redo, the RunPod rounds, the per-request path and the free settle read a
    round's approval from its take, so a still kept from an earlier round is approved there."""
    import inspect

    for code in (
        inspect.getsource(assembler._StillRedoBuyer.run),
        inspect.getsource(stills_stage._StillRounds._settled),
        inspect.getsource(stills_stage.run_stills_stage),
        inspect.getsource(stills_stage._settle_pending),
    ):
        assert "end.report is not None" not in code
        assert "end.take_id is not None" in code


# ------------ the review of this fix: clip records the old cap-keep wrote as a pass (STUB-003)


def _legacy_cap_record(session: Session, board: str, scene: int, take_id: str) -> None:
    """A clip-QC record as the cap-keep wrote it before 2026-10-16: PASSED, passed, kept by
    the cap, no QC verdict of its own; its refusal only in its blocks (as on 87c05891 scene 5)."""
    append_event(
        session,
        CLIP_QC_EVENT,
        "scene_take",
        take_id,
        1,
        {
            "storyboard_id": board,
            "scene_number": scene,
            "take_id": take_id,
            "verdict": "PASSED",
            "passed": True,
            "accepted_by": CAP_APPROVER,
            "accepted_under_cap": True,
            "blocks_ro": ["repetă greșeala pe care rescrierea mișcării trebuia să o corecteze"],
            "cap_note_ro": "Acceptat sub plafonul Proprietarului (2 randări): clipul rămâne.",
        },
        "c",
    )


def test_a_clip_the_old_cap_keep_wrote_as_passed_is_read_as_kept_not_passed(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        passed = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "p.mp4")
        legacy = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "k.mp4")
        _at(session, passed, "2026-10-16T09:00:00+00:00")
        _at(session, legacy, "2026-10-16T10:00:00+00:00")
        session.get(SceneTake, legacy).approved_by = CAP_APPROVER
        _legacy_cap_record(session, board, 2, legacy)
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            passed,
            1,
            {"storyboard_id": board, "scene_number": 2, "take_id": passed, "verdict": "PASSED"},
            "c",
        )
    with Session(engine) as session:
        record = clip_qc_of(session, legacy)
        assert record["verdict"] == CAP_VERDICT and record["passed"] is False
        assert record["qc_verdict"] == "FAILED" and record["accepted_under_cap"] is True
        # The film may still use it, as it was kept ...
        take = session.get(SceneTake, legacy)
        assert assembler.clip_accepted(session, take, "PRODUCTION") == (True, "")
        # ... but it is no pass: a real pass ranks before it.
        ranked = [row.id for row in assembler._cap_shot_candidates(session, board, 2)]
        assert ranked == [passed, legacy]


def test_a_clip_the_old_cap_keep_wrote_as_passed_closes_none_of_her_motion_items(engine, tmp_path):
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        legacy = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "k.mp4")
        session.get(SceneTake, legacy).approved_by = CAP_APPROVER
        _legacy_cap_record(session, board, 2, legacy)
    with Session(engine) as session:
        assert not fix_check._passing_clip_after(session, board, 2, "2000-01-01T00:00:00")


def test_the_register_says_a_clip_the_old_cap_keep_wrote_as_passed_did_not_pass(engine):
    from test_events_feed import TITLE, page, record, studio

    ids = studio(engine)
    record(
        engine,
        "media.clip_qc_checked",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "scene_number": 5,
            "take_id": str(uuid4()),
            "scene": 5,
            "passed": True,
            "verdict": "PASSED",
            "accepted_by": CAP_APPROVER,
            "accepted_under_cap": True,
            "blocks_ro": ["repetă greșeala"],
        },
    )
    clip = page(engine)["media.clip_qc_checked"]
    assert clip["words_ro"] == (
        f"Clipul scenei 5 din «{TITLE}» nu a trecut controlul, dar rămâne sub plafonul de "
        "randări: studioul l-a păstrat."
    )


def test_her_look_that_passed_a_clip_once_kept_under_the_cap_stays_a_pass(engine, tmp_path):
    """A clip her second look kept (`fix_check.DIRECTOR_LOOK_APPROVER`) after an old cap-keep
    carries the old record's fields; it is her pass, and it is read as one."""
    board = a_film_with_stills(engine, tmp_path, scenes=3)
    with Session(engine) as session, session.begin():
        clip = _take(session, board, 2, "motion", status="PAID", on_disk=tmp_path / "k.mp4")
        append_event(
            session,
            CLIP_QC_EVENT,
            "scene_take",
            clip,
            1,
            {
                "storyboard_id": board,
                "scene_number": 2,
                "take_id": clip,
                "verdict": "PASSED",
                "passed": True,
                "accepted_by": fix_check.DIRECTOR_LOOK_APPROVER,
                "accepted_under_cap": True,
            },
            "c",
        )
    with Session(engine) as session:
        assert clip_qc_of(session, clip)["verdict"] == "PASSED"
        assert fix_check._passing_clip_after(session, board, 2, "2000-01-01T00:00:00")
