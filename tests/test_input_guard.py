"""Never buy again an input identical to one that was refused (the Owner, 2026-10-12, 22:00:
«DE CE NU SE SCHIMBĂ PROMPTUL!»; a new seed alone is not a change; a new still before another
clip).

The cyclotron film (aa170155), scene 1, as the record has it: 8 clips of still 4be4364e were asked
for (6 paid) from the same first frame (JPEG sha 1948d8e9…) with the same motion words (08a2f75d,
and the clip-QC retry's 2da0db70 = the same words plus one sentence), only the seed moving from
580970442 to 580970451; clip QC refused every paid clip for faces in its frames. Here
the same history is written on a test database (the journal row and the take of each purchase,
the clip-QC report on the take) and `input_guard.refused_before` is asked about the next
purchase. Nothing is bought: no vendor, no model, no network, 0 credits.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from app import wording
from app.media import input_guard as guard
from app.media.models import SceneTake
from app.models import DomainEvent
from app.providers.runpod.batch import BatchRequest, journal_payload
from app.providers.runpod.jobs import GenerationJob, digest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_phase5_media import _seeded_storyboard

LTX = "LTX-2.5"
QWEN = "Qwen-Image-2512"
#: The first frame `assembler._first_frame` sent for still 4be4364e, and one of a new still.
FIRST_FRAME = b"\xff\xd8\xff\xe0" + b"4be4364e: four people at a table behind the device " * 8
NEW_FIRST_FRAME = b"\xff\xd8\xff\xe0" + b"a new still: the brass chamber on the desk alone " * 8
#: The motion words of all seven paid clips (job c584fcac's text, as the compiler garbled it).
WORDS = (
    "Slow push-in from the wide view toward the subject. A slow drift of dust motes floats "
    "through the lamp beam and a faint. Over the 7. Starting on the wide tabletop view and "
    "ending closer on the brass chamber. Faces stay turned away from the camera."
)
#: Clip QC's retry: the same words plus one sentence (2da0db70).
RETRY_WORDS = WORDS + " The camera's push-in stays smooth and moderate."
#: New motion words, written after a refusal.
NEW_WORDS = (
    "Slow push-in across the desk toward the small brass cyclotron. A slow drift of dust motes "
    "floats through the green lamp beam. Over the 7.6 seconds the chamber fills the frame."
)
STILL_WORDS = (
    "A flat brass cylinder with a finger's-width gap between two thick round discs of dark "
    "iron, on a 1930s laboratory desk. Any people appear only as small distant figures seen "
    "from behind, faces turned away."
)
FACES_BLOCK = (
    "Scena 1: YuNet a găsit fețe în cadrul first (1), last (2), deși biblia vizuală interzice "
    "fețele"
)
LOOK_BLOCK = (
    "Scena 1: privit la 1080 px: se vede o față, deși biblia vizuală interzice fețele; nu arată "
    "ce cere planul; încalcă biblia vizuală: Faces are visible in the last frame (a man with "
    "glasses and a blonde woman, both facing camera), violating the rule that people appear "
    "only as small distant figures seen from behind with faces turned away."
)
#: Exactly the sentence the register reads for the second purchase of 12:57 UTC. The face was
#: in the first frame, so the still is at fault: new words alone would be refused (SAME_STILL),
#: and the sentence says what the Owner ordered at 22:00 — a new still before another clip.
SECOND_PURCHASE_RO = (
    "Nu cumpăr din nou: scena 1 a mai fost cumpărată exact așa (aceeași imagine, aceleași "
    "cuvinte) și a fost respinsă: YuNet a găsit fețe în cadrul first (1), last (2), deși biblia "
    "vizuală interzice fețele; greșeala este în imagine, deci trebuie mai întâi o imagine nouă."
)
#: The task's sentence, word for word, for a clip refused for its movement (the still is clean).
MOTION_REFUSED_RO = (
    "Nu cumpăr din nou: scena 1 a mai fost cumpărată exact așa (aceeași imagine, aceleași "
    "cuvinte) și a fost respinsă: YDIF mediu 0,05 la 540 px, sub pragul de 0,17 pentru "
    "«push-in»; trebuie schimbată imaginea sau cuvintele."
)
#: The stills gate's words on a refused candidate, as the live record keeps them (f06808c9
#: scene 3, 2026-10-12): the reasons in Romanian, the judge's own words quoted in English, its
#: verdict in its code, and the note that the look did not run.
PANELS_DETAIL = (
    "Modelul de vedere nu vede o singură fotografie (panouri, colaj, ecran împărțit sau o bandă "
    "goală) «The frame is split into three horizontal panels stacked one above another, not one "
    "continuous picture.»; Imaginea nu arată ce cere planul scenei «The frame is split into three "
    "horizontal panels stacked one above another, not one continuous picture.»; Verdictul "
    "modelului de vedere: regenerate_still «The frame is split into three horizontal panels"
)
GATE_FACES_DETAIL = (
    "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele; Imaginea nu a fost "
    "privită: verificările locale au oprit-o deja (faces)"
)
#: The clip look's block when it is the only one: the bible's rule quoted after its head.
BIBLE_BLOCK = (
    "Scena 4: privit la 1080 px: are deformări sau artefacte; încalcă biblia vizuală: The "
    "cyclotron device is not identical across frames: the brass rings warp, multiply and melt "
    "between frames. («One continuous warm shot of the brass device, but the rings smear.»)"
)


def at(hour: int, minute: int = 0, second: int = 0) -> str:
    """A UTC moment of 2026-10-12, as the record writes it."""
    return (
        datetime(2026, 10, 12, tzinfo=UTC) + timedelta(hours=hour, minutes=minute, seconds=second)
    ).isoformat()


def clip(
    storyboard_id: str,
    *,
    words: str = WORDS,
    seed: int = 580970442,
    first_frame: bytes | None = FIRST_FRAME,
    model: str = LTX,
    seconds: float = 8.0,
    negative: str | None = None,
    scene: int = 1,
    attempt: int = 1,
) -> BatchRequest:
    """A clip as `assembler._ShotRounds._request` asks RunPod for it."""
    return BatchRequest(
        operation="video",
        project_id=storyboard_id,
        scene_id=str(scene),
        candidate_index=0,
        attempt_number=attempt,
        model=model,
        prompt=words,
        negative_prompt=negative,
        seed=seed,
        width=1080,
        height=1920,
        duration=seconds,
        fps=24,
        references=(),
        source_image=first_frame,
        price_usd=Decimal("0.72"),
    )


def still(
    storyboard_id: str,
    *,
    words: str = STILL_WORDS,
    seed: int = 4287185114,
    candidate: int = 0,
    negative: str | None = "visible faces, portrait",
    references: tuple[bytes, ...] = (),
    scene: int = 1,
) -> BatchRequest:
    """A still candidate as `stills_stage._StillRounds._requests` asks RunPod for it."""
    return BatchRequest(
        operation="image",
        project_id=storyboard_id,
        scene_id=str(scene),
        candidate_index=candidate,
        attempt_number=1,
        model=QWEN,
        prompt=words,
        negative_prompt=negative,
        seed=seed,
        width=1530,
        height=2720,
        duration=None,
        fps=None,
        references=references,
        source_image=None,
        price_usd=Decimal("0.08"),
    )


def bought(
    engine,
    request: BatchRequest,
    *,
    status: str,
    when: str,
    code: str | None = None,
    detail: str | None = None,
    report: dict | None = None,
    judged: str | None = None,
    credits: float | None = 22.0,
    kind: str | None = None,
    batch: str | None = None,
    job_status: str | None = None,
) -> str:
    """One purchase as the studio records it: the journal row RunPod's item was reserved
    under, its take (``remote_task_id`` = the row's ``remote_job_id``), and the clip-QC report
    on the take written at ``judged``."""
    take_id = str(uuid4())
    batch = batch or f"{uuid4()}-e1"
    remote = f"{batch}:{request.candidate_index}"
    payload = journal_payload(request)
    delivered = status in ("PAID", "APPROVED", "REJECTED")
    job_status = job_status or ("COMPLETED" if delivered else "FAILED")
    with Session(engine) as session, session.begin():
        session.add(
            GenerationJob(
                id=str(uuid4()),
                idempotency_key=uuid4().hex,
                payload_hash=digest(payload),
                request_digest=digest(payload),
                integration_id=None,
                provider="RUNPOD_MOCK",
                target="test",
                project_id=request.project_id,
                scene_id=request.scene_id,
                attempt=request.attempt_number,
                operation=request.operation,
                model=request.model,
                gpu="MOCK_CPU",
                hourly_rate="0",
                remote_job_id=remote,
                batch_remote_id=batch,
                batch_index=request.candidate_index,
                status=job_status,
                request=payload,
                output={},
                created_at=when,
                poll_count=0,
                accepted=(status in ("PAID", "APPROVED")) if delivered else None,
                quality_result=detail if status == "REJECTED" else None,
            )
        )
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=request.project_id,
                scene_number=int(request.scene_id),
                kind=kind or ("still" if request.operation == "image" else "motion"),
                # The scene's identity, the same on every take of the scene (b2a94fcd…).
                prompt_hash="b2a94fcd" * 8,
                model_id=request.model,
                resolution="1080:1920" if request.operation == "video" else "1530:2720",
                seconds=request.duration,
                seed=request.seed,
                credits_quoted=credits,
                status=status,
                failure_code=code,
                failure_detail=detail,
                sha256=uuid4().hex if delivered else None,
                remote_task_id=remote,
                created_at=when,
                updated_at=judged or when,
            )
        )
        if report is not None:
            # Written at the moment clip QC spoke (the record is immutable once written).
            session.add(
                DomainEvent(
                    event_id=str(uuid4()),
                    event_type=guard.CLIP_QC_EVENT,
                    timestamp=judged or when,
                    aggregate_type="scene_take",
                    aggregate_id=take_id,
                    aggregate_version=1,
                    correlation_id=str(uuid4()),
                    causation_id=None,
                    schema_version=1,
                    visibility="OWNER",
                    payload={"take_id": take_id, "scene_number": int(request.scene_id), **report},
                )
            )
    return take_id


def faces_report(first: int = 1, last: int = 2) -> dict:
    """Clip QC's report on a clip with faces (d87a3b24's, 12:56:46 UTC)."""
    return {
        "verdict": "FAILED",
        "passed": False,
        "blocks_ro": [FACES_BLOCK, LOOK_BLOCK],
        "checks": [
            {"code": "motion", "status": "PASSED", "blocking": False},
            {"code": "faces", "status": "FAILED", "blocking": True},
            {"code": "picture", "status": "FAILED", "blocking": True},
        ],
        "measured": {
            "faces": {
                "frames": [
                    {"at": "first", "status": "MEASURED", "faces": first},
                    {"at": "middle", "status": "MEASURED", "faces": 0},
                    {"at": "last", "status": "MEASURED", "faces": last},
                ]
            },
            "picture": {"status": "MEASURED", "verdict": {"one_picture": True}},
        },
    }


def motion_report() -> dict:
    """Clip QC's report on a clip whose camera did not move: the still is not at fault."""
    return {
        "verdict": "FAILED",
        "passed": False,
        "blocks_ro": ["Scena 1: YDIF mediu 0,05 la 540 px, sub pragul de 0,17 pentru «push-in»"],
        "checks": [
            {"code": "motion", "status": "FAILED", "blocking": True},
            {"code": "faces", "status": "PASSED", "blocking": False},
        ],
        "measured": {
            "faces": {"frames": [{"at": "first", "faces": 0}, {"at": "last", "faces": 0}]},
        },
    }


def ask(engine, request: BatchRequest, **kwargs):
    with Session(engine) as session:
        return guard.refused_before(session, guard.identity_of_request(request), **kwargs)


@pytest.fixture
def film(engine, tmp_path) -> str:
    storyboard_id, _claim = _seeded_storyboard(engine, tmp_path, scenes=2)
    return storyboard_id


# ------------------------------------------------------------------------------ identity


def test_words_are_compared_as_words_and_a_seed_is_no_change():
    assert guard.words_hash("Over the 7.6 seconds") == guard.words_hash("  over THE 7.6 seconds, ")
    assert guard.words_hash("Over the 7.6 seconds") != guard.words_hash("Over the 7.")
    assert guard.words_hash("a faint.") != guard.words_hash("a faint shimmer.")
    assert guard.words_hash(None) is None and guard.words_hash(" ... ") is None

    first = guard.identity_of_request(clip("f", seed=580970442, attempt=3))
    later = guard.identity_of_request(clip("f", seed=580970451, attempt=9))
    assert first == later and first.key == later.key
    for changed in (
        clip("f", words=NEW_WORDS),
        clip("f", first_frame=NEW_FIRST_FRAME),
        clip("f", model="Wan-2.2"),
        clip("f", seconds=9.0),
        clip("f", scene=2),
    ):
        assert guard.identity_of_request(changed) != first
    # The seed `batch.reserve_item` sends instead of a used one (``seed_asked``) is no change.
    fresh = replace(clip("f", seed=1417485348), seed_asked=580970442)
    assert guard.identity_of_request(fresh) == first
    assert first.kind == guard.MOTION and first.still_sha and first.seconds == 8.0
    # A still pair is one input: the candidates differ only by their seed and index.
    pair = [
        guard.identity_of_request(still("f", seed=s, candidate=c)) for c, s in enumerate((1, 2))
    ]
    assert pair[0] == pair[1]
    assert pair[0].kind == guard.STILL and pair[0].still_sha is None and pair[0].seconds is None


def test_a_purchase_and_its_journal_row_have_one_identity(engine, film):
    asked = clip(film, seed=580970446, attempt=6)
    take_id = bought(engine, asked, status="REJECTED", when=at(18, 7, 29), code="QC.CLIP")
    with Session(engine) as session:
        take = session.get(SceneTake, take_id)
        assert guard.identity_of_take(session, take) == guard.identity_of_request(asked)
        # The take's own prompt_hash is the scene's identity, not the words: never used.
        assert take.prompt_hash.startswith("b2a94fcd")
        # A take with no journal row (a purchase before the journal) has no known input.
        take.remote_task_id = None
        assert guard.identity_of_take(session, take) is None
    reference = b"\x89PNG\r\n\x1a\n" + b"Lawrence, figure one" * 4
    drawn = still(film, references=(reference,))
    still_id = bought(engine, drawn, status="REJECTED", when=at(10, 37), code="LOCAL.STILL_GATE")
    with Session(engine) as session:
        known = guard.identity_of_take(session, session.get(SceneTake, still_id))
    assert known == guard.identity_of_request(drawn)
    assert known.references_sha and known != guard.identity_of_request(still(film))


# --------------------------------------------------------------------------- the incident


def test_the_cyclotron_scene_is_bought_once_and_then_never_the_same_again(engine, film):
    # 10:45 UTC: the step stopped before this clip was sent; nothing was made or paid.
    bought(
        engine,
        clip(film, attempt=2),
        status="REFUSED",
        when=at(10, 45, 44),
        code=guard.CANCELLED_CODE,
        detail="Nu s-a cumpărat: pasul s-a oprit înainte de acest cadru.",
        credits=None,
    )
    assert ask(engine, clip(film, attempt=3)) is None  # the first paid clip is bought
    # 12:23 UTC: d87a3b24, judged at 12:56:46, faces in its first and last frames.
    first = bought(
        engine,
        clip(film, attempt=3),
        status="REJECTED",
        when=at(12, 23, 32),
        code="QC.CLIP",
        detail="Controlul clipului: " + FACES_BLOCK + "; " + LOOK_BLOCK,
        report=faces_report(),
        judged=at(12, 56, 46),
    )

    # 12:57 UTC: the same words from the same still, seed + 2 — not bought.
    again = ask(engine, clip(film, seed=580970444, attempt=4))
    assert again is not None
    assert again.match == guard.SAME_INPUT and again.code == "SAME_INPUT_FAILED"
    assert again.take_id == first and again.times == 1 and again.seed == 580970442
    assert again.layer == guard.STILL  # the faces are in the still the clip started from
    assert again.reason_ro == SECOND_PURCHASE_RO

    # 18:17 UTC: the retry's words (the same words plus a sentence) on the same still — the
    # face is in the still, so no words can remove it: a new still first.
    retry = ask(engine, clip(film, words=RETRY_WORDS, seed=580970447, attempt=7))
    assert retry is not None and retry.match == guard.SAME_STILL and retry.layer == guard.STILL
    assert retry.reason_ro.startswith(
        "Nu cumpăr din nou: scena 1 a mai fost filmată din aceeași imagine și a fost respinsă "
        "pentru o greșeală a imaginii: YuNet a găsit fețe"
    )
    assert retry.reason_ro.endswith(
        "trebuie mai întâi o imagine nouă, nu încă un clip din aceeași imagine."
    )
    # Even well-rewritten words: the same still is refused.
    assert ask(engine, clip(film, words=NEW_WORDS)).match == guard.SAME_STILL
    # A new still: nothing against it here (the gate judges it first).
    assert ask(engine, clip(film, first_frame=NEW_FIRST_FRAME)) is None
    assert ask(engine, clip(film, words=NEW_WORDS, first_frame=NEW_FIRST_FRAME)) is None

    # More refusals of the same input are counted and said.
    bought(
        engine,
        clip(film, seed=580970444, attempt=4),
        status="REJECTED",
        when=at(12, 57, 16),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(13, 8),
    )
    third = ask(engine, clip(film, seed=580970446, attempt=6))
    assert third.times == 2 and len(third.take_ids) == 2 and third.take_ids[0] == first
    assert "a mai fost cumpărată exact așa de 2 ori" in third.reason_ro
    assert "a fost respinsă de fiecare dată:" in third.reason_ro


def test_a_clip_refused_for_its_motion_needs_new_words_not_a_new_seed(engine, film):
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(12),
        code="QC.CLIP",
        report=motion_report(),
        judged=at(12, 5),
    )
    again = ask(engine, clip(film, seed=580970443))
    assert again is not None and again.match == guard.SAME_INPUT
    assert again.layer == guard.MOTION  # the still's first frame measured clean
    assert "YDIF mediu 0,05" in again.words and "Scena 1:" not in again.words
    assert again.reason_ro == MOTION_REFUSED_RO
    # New words on the same still are a change; another model is too.
    assert ask(engine, clip(film, words=RETRY_WORDS)) is None
    assert ask(engine, clip(film, model="Wan-2.2")) is None


def test_a_technical_failure_may_be_bought_once_more_never_a_third_time(engine, film):
    # Stopped before sending, three times: nothing was bought, nothing counts.
    for minute in (1, 2, 3):
        bought(
            engine,
            clip(film),
            status="REFUSED",
            when=at(9, minute),
            code=guard.CANCELLED_CODE,
            credits=None,
        )
    assert ask(engine, clip(film)) is None
    # 16:55 UTC (279fb3f4): delivered nothing before RunPod dropped the result.
    bought(
        engine,
        clip(film),
        status="REFUSED",
        when=at(16, 55, 38),
        code="RUNPOD.EXPIRED_UNDELIVERED",
    )
    assert ask(engine, clip(film, seed=580970447)) is None  # once more is allowed
    bought(
        engine,
        clip(film, seed=580970447),
        status="LOST",
        when=at(17, 30),
        code="VENDOR.NOT_COLLECTED",
    )
    twice = ask(engine, clip(film, seed=580970448))
    assert twice is not None and twice.match == guard.TECHNICAL_TWICE
    assert twice.layer is None and twice.times == 2
    assert "a eșuat tehnic" in twice.reason_ro
    assert "rezultatul nu a fost ridicat la timp de la furnizor" in twice.reason_ro


def test_a_still_refused_for_what_it_shows_is_never_drawn_again_on_the_same_words(engine, film):
    pair = f"{uuid4()}-e2"
    faces = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
    bought(
        engine,
        still(film, seed=2807491978, candidate=1),
        status="REJECTED",
        when=at(10, 43, 25),
        code="LOCAL.STILL_GATE",
        detail=faces,
        credits=7.0,
        batch=pair,
    )
    again = ask(engine, still(film, seed=111))
    assert again is not None and again.match == guard.SAME_INPUT and again.layer == guard.STILL
    assert again.reason_ro == (
        "Nu cumpăr din nou: imaginea scenei 1 a mai fost cumpărată exact așa (aceleași cuvinte) "
        "și a fost respinsă: YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele; "
        "trebuie schimbate cuvintele."
    )
    # The gate's re-roll appends its words: a new input.
    assert ask(engine, still(film, words=STILL_WORDS + " Only the objects named.")) is None


def test_a_technical_gate_refusal_allows_one_more_pair_on_the_same_words(engine, film):
    blur = "Imaginea e neclară: 138 sub pragul de 250 (la 1080 px)"
    pair = f"{uuid4()}-e1"
    for candidate in (0, 1):  # both candidates of one round: one round
        bought(
            engine,
            still(film, candidate=candidate, seed=10 + candidate),
            status="REJECTED",
            when=at(9),
            code="LOCAL.STILL_GATE",
            detail=blur,
            credits=7.0,
            batch=pair,
        )
    assert ask(engine, still(film, seed=20)) is None
    bought(
        engine,
        still(film, seed=20),
        status="REJECTED",
        when=at(9, 30),
        code="LOCAL.STILL_GATE",
        detail=blur,
        credits=7.0,
    )
    twice = ask(engine, still(film, seed=30))
    assert twice is not None and twice.match == guard.TECHNICAL_TWICE
    assert "Imaginea e neclară" in twice.reason_ro


def test_a_still_clip_qc_sent_back_is_refused_for_what_it_shows(engine, film):
    bought(
        engine,
        still(film),
        status="REJECTED",
        when=at(10, 43),
        code="LOCAL.STILL_GATE",
        detail=(
            "Controlul clipului a găsit greșeala în imagine; imaginea se întoarce la poarta "
            "imaginilor și nu se mai animă. Clipul arată două fețe."
        ),
        credits=7.0,
    )
    assert ask(engine, still(film, seed=5)).match == guard.SAME_INPUT


def test_only_this_scene_of_this_film_is_compared(engine, film, tmp_path):
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(12),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(12, 30),
    )
    other_film, _claim = _seeded_storyboard(engine, tmp_path / "other", scenes=2)
    assert ask(engine, clip(other_film)) is None
    assert ask(engine, clip(film, scene=2)) is None
    # A still is never compared with a clip.
    assert ask(engine, still(film)) is None


def test_the_directors_and_the_owners_refusals_count_a_duplicate_file_does_not(engine, film):
    retired = bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(8, 45),
        code="REDO.OWNER",
        detail="Controlul calității a picat scena; refacere hotărâtă de Directoare.",
        report={"verdict": "PASSED", "passed": True, "blocks_ro": [], "checks": []},
        judged=at(8, 50),
    )
    again = ask(engine, clip(film, seed=7))
    assert again.match == guard.SAME_INPUT and again.layer == guard.MOTION
    assert again.take_id == retired
    assert "refacere hotărâtă de Directoare" in again.reason_ro
    with Session(engine) as session:
        take = session.get(SceneTake, retired)
        take.failure_code = "VENDOR.DUPLICATE_FILE"
        session.commit()
    assert ask(engine, clip(film, seed=7)) is None


@pytest.mark.parametrize(
    ("status", "code", "credits", "expected", "at_fault"),
    [
        ("REJECTED", "QC.CLIP", 22.0, guard.CONTENT, False),
        ("REJECTED", "REDO.OWNER", 22.0, guard.CONTENT, False),
        ("REJECTED", "OWNER.REJECTED", 22.0, guard.CONTENT, False),
        ("REJECTED", "REDO.STILL_REPLACED", 22.0, guard.CONTENT, True),
        ("REJECTED", None, 22.0, guard.CONTENT, False),
        ("REJECTED", "VENDOR.DUPLICATE_FILE", 22.0, guard.NOT_JUDGED, False),
        ("REJECTED", "LOCAL.DEGENERATE_STILL", 7.0, guard.TECHNICAL, False),
        ("REFUSED", "SAFETY.INPUT.IMAGE", 22.0, guard.CONTENT, True),
        ("REFUSED", "RUNPOD.CANCELLED", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "RUNPOD.CANCELLED", 22.0, guard.TECHNICAL, False),
        ("REFUSED", "RUNPOD.NOT_QUEUED", None, guard.NOT_BOUGHT, False),
        # The studio's own stop (`BatchRun.cancel`), the worker's time guard, never sent.
        ("REFUSED", "RUNPOD.CANCELLED_BY_STUDIO", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "RUNPOD.SKIPPED_TIME", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "RUNPOD.UNSENT", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "RUNPOD.TIMED_OUT", None, guard.TECHNICAL, False),
        ("REFUSED", "VENDOR.NO_OUTPUT", None, guard.TECHNICAL, False),
        ("REFUSED", "HTTP_400", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "HTTP_503", 22.0, guard.TECHNICAL, False),
        ("REFUSED", "LOCAL_CONNECTION", None, guard.NOT_BOUGHT, False),
        ("REFUSED", "VENDOR.UNANSWERED", 22.0, guard.TECHNICAL, False),
        ("REFUSED", "RUNPOD.EXPIRED_UNDELIVERED", None, guard.TECHNICAL, False),
        ("LOST", "VENDOR.NOT_COLLECTED", 22.0, guard.TECHNICAL, False),
        ("PAID", None, 22.0, None, False),
        ("APPROVED", None, 22.0, None, False),
    ],
)
def test_what_each_ended_take_says_about_its_input(status, code, credits, expected, at_fault):
    take = SceneTake(
        id="t",
        storyboard_id="s",
        scene_number=1,
        kind="motion",
        prompt_hash="h",
        model_id=LTX,
        resolution="1080:1920",
        status=status,
        failure_code=code,
        credits_quoted=credits,
    )
    assert guard.refusal_class(take) == expected
    assert guard.still_at_fault(take, None) is at_fault


def test_the_still_is_at_fault_only_for_what_its_first_frame_shows():
    take = SceneTake(id="t", kind="motion", status="REJECTED", failure_code="QC.CLIP")
    assert guard.still_at_fault(take, faces_report(first=1))
    # adeff9cf: faces only in the last frame — the move found them, not the still.
    assert not guard.still_at_fault(take, faces_report(first=0, last=2))
    assert not guard.still_at_fault(take, motion_report())
    split = {
        "measured": {"panels": {"frames": [{"at": "first", "splits_the_picture": True}]}},
    }
    assert guard.still_at_fault(take, split)
    collage = {"measured": {"picture": {"verdict": {"one_picture": False}}}}
    assert guard.still_at_fault(take, collage)
    assert guard.still_at_fault(take, {"back_to_still": True})


def test_a_redo_never_buys_the_input_of_the_take_it_replaces(engine, film):
    # 13:29 UTC, 1c038a99 scene 5: the Director's motion redo bought the clip it was replacing
    # again, 3 s after retiring it, with only the seed moved. While the old clip still stands
    # (it is retired only once the new one is approved), the redo itself is the refusal.
    standing = bought(
        engine,
        clip(film),
        status="PAID",
        when=at(8, 45, 9),
        report={"verdict": "PASSED", "passed": True, "blocks_ro": [], "checks": []},
        judged=at(8, 49, 53),
    )
    assert ask(engine, clip(film, seed=1417485348)) is None
    replaced = ask(
        engine,
        clip(film, seed=1417485348),
        replacing=[standing],
        replacing_why="Controlul filmului: lampa de birou nu este verde",
    )
    assert replaced is not None and replaced.match == guard.SAME_INPUT
    assert replaced.take_id == standing and replaced.layer == guard.MOTION
    assert "a fost respinsă: Controlul filmului: lampa de birou nu este verde;" in (
        replaced.reason_ro
    )
    without_words = ask(engine, clip(film, seed=3), replacing=[standing])
    assert guard.REPLACED_WORDS in without_words.reason_ro
    assert ask(engine, clip(film, words=NEW_WORDS), replacing=[standing]) is None


def test_the_rule_replays_the_record_as_it_stood_at_a_moment(engine, film):
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(12, 23, 32),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(12, 56, 46),
    )
    # Asked before clip QC had spoken (12:40), the clip was still being made: nothing refused.
    assert ask(engine, clip(film, seed=9), before=at(12, 40)) is None
    assert ask(engine, clip(film, seed=9), before=at(12, 57)).match == guard.SAME_INPUT
    # Before it was even bought: nothing.
    assert ask(engine, clip(film, seed=9), before=at(12)) is None


def test_the_codes_are_the_ones_the_studio_writes():
    from app.media import assembler, scene_rewrite, stills_stage

    assert guard.CLIP_QC_CODE == assembler.CLIP_QC_FAILURE_CODE
    assert guard.CLIP_QC_EVENT == assembler.CLIP_QC_EVENT
    assert guard.STILL_GATE_CODE == stills_stage.GATE_FAILURE_CODE == scene_rewrite.STILL_GATE_CODE
    assert guard.STILL_REPLACED_CODE == assembler.REDO_STILL_REPLACED
    assert guard.DUPLICATE_FILE_CODE == assembler.DUPLICATE_FILE_CODE
    assert guard.DEGENERATE_CODE == assembler.DEGENERATE_FAILURE_CODE
    assert guard.CANCELLED_CODE == assembler.CANCELLED_FAILURE_CODE
    assert guard.NOT_QUEUED_CODE == assembler.NOT_QUEUED_FAILURE_CODE
    assert "VENDOR.NOT_COLLECTED" == assembler.LOST_FAILURE_CODE
    assert "VENDOR.UNANSWERED" == assembler.UNANSWERED_FAILURE_CODE
    assert assembler.CANCELLED_DETAIL.startswith("Nu s-a cumpărat")
    # The still sent back by clip QC opens with these words (`_send_still_back_for_clip`).
    import inspect

    assert guard.SENT_BACK_WORDS in inspect.getsource(assembler._send_still_back_for_clip)


def test_the_refusal_is_written_for_the_register_in_the_owners_words(engine, film):
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(12, 23, 32),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(12, 56, 46),
    )
    identity = guard.identity_of_request(clip(film, seed=580970444))
    with Session(engine) as session, session.begin():
        attempt = guard.refused_before(session, identity)
        event_id = guard.record_refusal(
            session, identity, attempt, correlation_id=str(uuid4()), step="motion"
        )
    with Session(engine) as session:
        event = session.scalar(select(DomainEvent).where(DomainEvent.event_id == event_id))
        payload = dict(event.payload)
    assert event.event_type == guard.REFUSED_EVENT and event.aggregate_id == film
    assert payload["reason_ro"] == SECOND_PURCHASE_RO
    assert payload["scene_index"] == 1 and payload["match"] == guard.SAME_INPUT
    assert payload["layer"] == guard.STILL and payload["code"] == guard.REFUSAL_CODE
    assert payload["identity"]["key"] == identity.key and payload["step"] == "motion"
    # The Owner's sentence names no code, hash or seed.
    for sentence in (attempt.reason_ro, payload["reason_ro"]):
        assert not re.search(r"\b[A-Z]{2,}[._][A-Z]", sentence)
        assert "SAME_" not in sentence and "580970" not in sentence
        assert identity.still_sha[:8] not in sentence


# ------------------------------------------------------------------- what review broke


def test_stopped_and_skipped_rounds_never_count_against_the_input(engine, film):
    # The Owner's «Oprește GPU acum» cancels a still round (CANCELLED_BY_STUDIO, cost 0), and
    # the worker's time guard skips a clip it never started (SKIPPED_TIME, cost 0): nothing was
    # made, twice. The input was never tried, so it is not refused (it was TECHNICAL_TWICE).
    for minute in (1, 2):
        pair = f"{uuid4()}-e1"
        for candidate in (0, 1):
            bought(
                engine,
                still(film, candidate=candidate, seed=minute * 10 + candidate),
                status="REFUSED",
                when=at(9, minute),
                code="RUNPOD.CANCELLED_BY_STUDIO",
                detail="Nu s-a cumpărat: pasul s-a oprit înainte de această imagine.",
                credits=None,
                batch=pair,
                job_status="CANCELLED",
            )
        bought(
            engine,
            clip(film, seed=580970440 + minute),
            status="REFUSED",
            when=at(9, minute, 30),
            code="RUNPOD.SKIPPED_TIME",
            credits=None,
        )
    assert ask(engine, still(film, seed=99)) is None
    assert ask(engine, clip(film, seed=580970449)) is None


def test_a_crash_resend_of_a_purchase_in_flight_is_never_refused(engine, film):
    # A clip sent and not yet answered when the studio stopped: on the restart the step asks for
    # it again, and `batch.reserve_item` answers RESEND or TRACK on its key with the seed it was
    # sent with. Nothing about that input was refused: the guard lets it through, and the fresh
    # seed the journal sent instead of the asked one (``seed_asked``) is the same input.
    asked = clip(film, seed=580970442, attempt=3)
    sent = replace(asked, seed=1417485348, seed_asked=asked.seed)
    bought(
        engine,
        sent,
        status="SUBMITTED",
        when=at(12, 23, 32),
        credits=22.0,
        job_status="QUEUED",
    )
    assert ask(engine, asked) is None
    assert ask(engine, sent) is None
    # Lost once (not collected in time): one more round of the same input is allowed.
    bought(engine, sent, status="LOST", when=at(12, 30), code="VENDOR.NOT_COLLECTED")
    assert ask(engine, asked) is None


def test_two_technical_failures_say_both_reasons_once(engine, film):
    bought(
        engine,
        clip(film, seed=1),
        status="REFUSED",
        when=at(16, 55, 38),
        code="RUNPOD.EXPIRED_UNDELIVERED",
        credits=None,
    )
    bought(engine, clip(film, seed=2), status="LOST", when=at(17, 30), code="VENDOR.NOT_COLLECTED")
    twice = ask(engine, clip(film, seed=3))
    assert twice.match == guard.TECHNICAL_TWICE and twice.times == 2
    assert twice.reason_ro == (
        "Nu cumpăr din nou: scena 1 a fost cerută exact așa de 2 ori și de fiecare dată a eșuat "
        "tehnic (rezultatul a expirat la RunPod înainte să fie ridicat; rezultatul nu a fost "
        "ridicat la timp de la furnizor); aceeași cerere nu se mai trimite până nu se află de ce."
    )


def test_a_still_pair_refused_together_was_bought_once(engine, film):
    pair = f"{uuid4()}-e1"
    for candidate in (0, 1):
        bought(
            engine,
            still(film, candidate=candidate, seed=10 + candidate),
            status="REJECTED",
            when=at(10, 43),
            code="LOCAL.STILL_GATE",
            detail=GATE_FACES_DETAIL,
            credits=7.0,
            batch=pair,
        )
    again = ask(engine, still(film, seed=12))
    assert again.match == guard.SAME_INPUT and again.times == 1
    assert len(again.take_ids) == 2
    assert again.reason_ro == (
        "Nu cumpăr din nou: imaginea scenei 1 a mai fost cumpărată exact așa (aceleași cuvinte) "
        "și a fost respinsă: YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele; "
        "trebuie schimbate cuvintele."
    )


def test_a_negative_counts_only_where_the_model_uses_it():
    # LTX-2.5 samples at CFG 1.0: the cyclotron's clips went with no negative, and sending one
    # now with the same words from the same still is the same clip, not a new input.
    bare = guard.identity_of_request(clip("f"))
    assert guard.identity_of_request(clip("f", negative="people, faces, figures")) == bare
    assert bare.negative_hash is None
    # Qwen-Image-2512 samples at CFG 4: a still whose negative now names people is a new input.
    drawn = guard.identity_of_request(still("f", negative="visible faces, portrait"))
    widened = guard.identity_of_request(still("f", negative="visible faces, portrait, people"))
    assert drawn != widened and drawn.negative_hash is not None
    # Qwen-Image-Edit-2511 (CFG 1.0) draws from a character's picture: its negative is unused.
    figure = b"\x89PNG\r\n\x1a\n" + b"Nadia, the locked character" * 4
    edited = [
        guard.identity_of_request(
            replace(still("f", negative=n, references=(figure,)), model="Qwen-Image-Edit-2511")
        )
        for n in ("visible faces", "visible faces, people")
    ]
    assert edited[0] == edited[1] and edited[0].model == "Qwen-Image-Edit-2511"
    # Without a picture `batch.route_references` gives the item to Qwen-Image-2512, which uses
    # the negative: the model that really draws decides.
    routed = [
        guard.identity_of_request(replace(still("f", negative=n), model="Qwen-Image-Edit-2511"))
        for n in ("visible faces", "visible faces, people")
    ]
    assert routed[0] != routed[1] and routed[0].model == QWEN


def test_the_models_whose_negative_is_unused_sample_at_cfg_one():
    from runpod_worker.contract import WORKFLOWS

    workflows = Path(__file__).resolve().parents[1] / "backend" / "runpod_worker" / "workflows"

    def cfgs(value) -> list[float]:
        found: list[float] = []
        if isinstance(value, dict):
            for key, item in value.items():
                if "cfg" in str(key).lower() and isinstance(item, int | float):
                    found.append(float(item))
                found += cfgs(item)
        elif isinstance(value, list):
            for item in value:
                found += cfgs(item)
        return found

    assert guard.NEGATIVE_UNUSED_MODELS <= set(WORKFLOWS)
    for model, (_operation, name) in WORKFLOWS.items():
        graph = json.loads((workflows / f"{name}.json").read_text(encoding="utf-8"))["graph"]
        sampled = cfgs(graph)
        assert sampled, model
        if model in guard.NEGATIVE_UNUSED_MODELS:
            assert all(value == 1.0 for value in sampled), model
        else:
            assert any(value > 1.0 for value in sampled), model


def test_the_owner_reads_the_studios_words_never_the_judges_english_or_a_code(engine, film):
    bought(
        engine,
        still(film, seed=1),
        status="REJECTED",
        when=at(9),
        code="LOCAL.STILL_GATE",
        detail=PANELS_DETAIL,
        credits=7.0,
    )
    panels = ask(engine, still(film, seed=2))
    assert panels.reason_ro == (
        "Nu cumpăr din nou: imaginea scenei 1 a mai fost cumpărată exact așa (aceleași cuvinte) "
        "și a fost respinsă: Modelul de vedere nu vede o singură fotografie (panouri, colaj, "
        "ecran împărțit sau o bandă goală); trebuie schimbate cuvintele."
    )
    bought(
        engine,
        clip(film, scene=2),
        status="REJECTED",
        when=at(9),
        code="QC.CLIP",
        detail="Controlul clipului: " + BIBLE_BLOCK,
        report={
            "verdict": "FAILED",
            "blocks_ro": [BIBLE_BLOCK],
            "checks": [{"code": "picture", "status": "FAILED", "blocking": True}],
            "measured": {"picture": {"verdict": {"one_picture": True}}},
        },
        judged=at(9, 5),
    )
    bible = ask(engine, clip(film, scene=2, seed=7))
    assert bible.words == "privit la 1080 px: are deformări sau artefacte; încalcă biblia vizuală"
    # The Director's finding, when it is in English, is not quoted: the redo's own words are.
    standing = bought(engine, clip(film, scene=2, words=NEW_WORDS), status="PAID", when=at(10))
    redo = ask(
        engine,
        clip(film, scene=2, words=NEW_WORDS, seed=8),
        replacing=[standing],
        replacing_why="The lamp is beige and stands at the right, not green at the left.",
    )
    assert redo.words == guard.REPLACED_WORDS
    check = getattr(wording, "owner_text_problems", None)
    for sentence in (panels.reason_ro, bible.reason_ro, redo.reason_ro):
        assert "«" not in sentence and "regenerate_still" not in sentence
        assert "The " not in sentence and "(faces)" not in sentence
        if check is not None:  # the Owner's own reading rules, where the worktree has them
            assert check(sentence) == [], sentence


def test_the_same_refusal_is_said_once_in_the_register(engine, film):
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(12, 23, 32),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(12, 56, 46),
    )
    identity = guard.identity_of_request(clip(film, seed=580970444))

    def say() -> str:
        with Session(engine) as session, session.begin():
            attempt = guard.refused_before(session, identity)
            return guard.record_refusal(session, identity, attempt, correlation_id=str(uuid4()))

    def said() -> int:
        with Session(engine) as session:
            events = session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == guard.REFUSED_EVENT)
            )
            return len(events.all())

    once = say()
    # The Director's walk comes back an hour later and asks for the same clip: said once.
    assert say() == once and said() == 1
    # Something new happened (another identical clip refused): the register hears it.
    bought(
        engine,
        clip(film, seed=580970444),
        status="REJECTED",
        when=at(12, 57, 16),
        code="QC.CLIP",
        report=faces_report(),
        judged=at(13, 8),
    )
    assert say() != once and said() == 2


def test_the_looks_verdict_alone_is_said_in_words_never_in_its_code(engine, film):
    # A gate refusal with no content phrase is technical (`scene_rewrite.refusal_kind`): one
    # more round, then held; the sentence says the verdict in words.
    for seed in (1, 2):
        bought(
            engine,
            still(film, seed=seed),
            status="REJECTED",
            when=at(9, seed),
            code="LOCAL.STILL_GATE",
            detail="Verdictul modelului de vedere: regenerate_still «The still could be sharper.»",
            credits=7.0,
        )
    alone = ask(engine, still(film, seed=3))
    assert alone.match == guard.TECHNICAL_TWICE
    assert alone.words == "modelul de vedere cere o imagine nouă"
    block = "Scena 1: privit la 1080 px: modelul cere back_to_still («The still must change.»)"
    bought(
        engine,
        clip(film),
        status="REJECTED",
        when=at(9),
        code="QC.CLIP",
        report={"verdict": "FAILED", "blocks_ro": [block], "checks": [], "measured": {}},
        judged=at(9, 5),
    )
    clip_verdict = ask(engine, clip(film, seed=3))
    assert clip_verdict.words == "privit la 1080 px: modelul de vedere cere o imagine nouă"
    for sentence in (alone.reason_ro, clip_verdict.reason_ro):
        assert "_still" not in sentence and "«" not in sentence


def test_a_face_the_movement_brought_in_is_the_motions_fault_not_the_stills(engine, film):
    # adeff9cf, 18:17 UTC: faces only in the LAST frame, its first frame (the still) measured
    # clean. The clean still is not blamed: new motion words on it may be bought, the same
    # words may not, and the sentence says the image or the words must change.
    bought(
        engine,
        clip(film, words=RETRY_WORDS),
        status="REJECTED",
        when=at(18, 17, 28),
        code="QC.CLIP",
        report=faces_report(first=0, last=2),
        judged=at(18, 20),
    )
    again = ask(engine, clip(film, words=RETRY_WORDS, seed=580970451))
    assert again.match == guard.SAME_INPUT and again.layer == guard.MOTION
    assert again.reason_ro.endswith("; trebuie schimbată imaginea sau cuvintele.")
    assert ask(engine, clip(film, words=NEW_WORDS)) is None
