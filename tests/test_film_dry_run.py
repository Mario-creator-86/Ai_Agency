"""The whole money staircase, end to end, in TEST, with every vendor faked (DRY_RUN_E2E).

The Nepal film (2026-09-26) cost over 1,000 credits: two whole films bought from a button
that showed no price, asked nothing, and was judged only after everything was paid. This
module walks one film up the staircase the way the Owner's page does, through the studio's
own HTTP routes, and proves what each stair buys:

  plan   the Nepal shot plan (the model's own answer, tests/fixtures/nepal_1d530880/
         shot_pack.txt) is parsed and compiled into a still prompt and a motion prompt per
         filmed scene; the chart and the black screen get no paid prompt at all;
  lint   the compiled prompts carry no BLOCK;
  sheet  GET .../shooting-sheet prices every scene before a credit is spent;
  stills POST .../steps/stills: 202 (his question), his yes, 200 (4 LIVE scenes x 2 candidates;
         every local check and the real YuNet run, only the paid vision judge is faked);
  hero   POST .../steps/test_shot: 202, yes, 200 (ONE shot); he looks at it and approves it;
  motion POST .../steps/motion: 202, yes, 200 (the three other filmed scenes);
  film   assembled from the takes alone (no adapter asked), cards composed locally;
  QC     the new quality control passes it, and qc_summary_ro reports the credits the
         account's balance says were spent, never the vendor's quotes.

At every stair, a stale hash, a spent yes or a balance under the step's cap buys nothing.

No socket is opened (counted here on top of conftest's guard), no credit is spent, no real
run is started, data/studio.db is never opened.
"""

from __future__ import annotations

import functools
import json
import socket
import subprocess
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.media import shooting_sheet
from app.media.assembler import assemble_from_takes
from app.media.cost_plan import price_shot
from app.media.models import SceneTake, Storyboard, StoryboardScene
from app.media.prompt_agent import compile_film_prompts, parse_shot_plan
from app.media.prompt_lint import LintScene, has_block, lint_film
from app.media.qc import evaluate_media_qc
from app.media.qc_report import qc_summary_ro, ro_count, ro_number
from app.media.toolchain import find_ffmpeg
from app.models import ApprovalRequest, DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE, VEO_FAST, Account, Models, SpyVideo
from test_phase5_media import AlignedVoice
from test_scene_takes import nepal_like
from test_stills_stage import SpyJudge, SpyStills

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
SHOT_PACK = FIXTURES / "shot_pack.txt"
PROMPTS = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))

#: Each filmed scene is planned at 4.6 s; with the 0.4 s overlap its shot is 5.0 s, which
#: seedance2_5 bills as 5 s (340 credits at 1080p) and veo3.1_fast as 6 s (60 credits).
PLANNED_SECONDS = 4.6
#: What the fake account is billed below each quote, so the balance (measured) and the
#: vendor's estimate (quoted) visibly differ. The report must name the first, never the second.
REBATE = 2
#: The narration, one line per scene (the chart and the black screen speak too).
NARRATION = {
    1: "Nepal is being handed a climate bill it cannot pay.",
    2: "Floods now arrive earlier and stay longer in the valleys.",
    3: "Terraced fields that fed families for generations are washed away.",
    4: "Farmers walk the ruined edges of land they still owe on.",
    5: "Rich countries promised one hundred billion a year, and delivered less.",
    6: "Who pays for the damage that is already done?",
}
LIVE_SCENES = (1, 2, 3, 4)


# ------------------------------------------------------------------------------ the fakes


class RunwayAccount(Account):
    """The one Runway account both the image and the video model draw on, faked: the balance
    read (a free GET /v1/organization) sees what was charged, ``REBATE`` below each quote."""

    def charge(self, credits: float) -> None:
        super().charge(credits - REBATE)


class Stills(SpyStills):
    """The image vendor, faked: two candidates per request, charged to the shared account."""

    def __init__(self, account: RunwayAccount, pictures: tuple[Path, Path]):
        super().__init__(pictures=lambda prompt, call: list(pictures))
        self.account = account

    async def credit_balance(self):
        return await self.account.credit_balance()

    async def generate_candidates(self, prompt, *, ratio, count=2, references=(), seed=None):
        results = await super().generate_candidates(
            prompt, ratio=ratio, count=count, references=references, seed=seed
        )
        self.account.charge(float(self.last_estimated_credits or 0))
        return results


class CountingVoice(AlignedVoice):
    """The narrator, faked (real WAV audio and ElevenLabs-shaped alignment); counts lines."""

    def __init__(self):
        super().__init__(aligned=True)
        self.said: list[str] = []

    async def synthesize(self, text, **kwargs):
        self.said.append(text)
        return await super().synthesize(text, **kwargs)


def _ffmpeg(*args: str, target: Path) -> Path:
    subprocess.run(  # noqa: S603 - the local encoder, arguments built here
        [str(find_ffmpeg()), "-nostdin", "-v", "error", *args, "-y", str(target)],
        check=True,
        capture_output=True,
        timeout=120,
    )
    return target


def detailed_stills(folder: Path) -> tuple[Path, Path]:
    """Two detailed 1080x1920 pictures with nobody in them: the stills gate's real local
    checks (a real picture, sharpness, motion blur, YuNet) read them as good stills."""
    made = []
    for seed in (1, 2):
        made.append(
            _ffmpeg(
                "-f",
                "lavfi",
                "-i",
                f"color=c=gray:s=1080x1920,noise=alls=40:allf=t:all_seed={seed}",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                target=folder / f"still_{seed}.jpg",
            )
        )
    return made[0], made[1]


def moving_clip(folder: Path) -> bytes:
    """What a vendor delivers: 6 s at 24 fps whose every frame differs (no frozen frames),
    long enough for its 5 s shot, so nothing is held."""
    return _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "color=c=gray:s=540x960:r=24:d=6,noise=alls=25:allf=t+u",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-crf",
        "28",
        target=folder / "vendor_clip.mp4",
    ).read_bytes()


@pytest.fixture
def sockets(monkeypatch, no_network):
    """Every connect and every name lookup, loopback included, counted on top of conftest's
    guard: the dry run must need none.

    One kind is set apart, not hidden: on Windows ``socket.socketpair()`` is built from a
    loopback listener and a connect to it, and every asyncio event loop makes one for its
    own wake-up pipe (each faked ``async`` vendor call runs in a fresh loop). Those connects
    are counted under ``socketpair``; they never leave the process.
    """
    seen: list[tuple[str, Any]] = []
    internal: list[Any] = []
    pairing = {"depth": 0}
    connect, connect_ex, lookup, pair = (
        socket.socket.connect,
        socket.socket.connect_ex,
        socket.getaddrinfo,
        socket.socketpair,
    )

    def counted_connect(self, address):
        if pairing["depth"]:
            internal.append(address)
        else:
            seen.append(("connect", address))
        return connect(self, address)

    def counted_connect_ex(self, address):
        seen.append(("connect_ex", address))
        return connect_ex(self, address)

    def counted_lookup(host, *args, **kwargs):
        seen.append(("getaddrinfo", host))
        return lookup(host, *args, **kwargs)

    def counted_pair(*args, **kwargs):
        pairing["depth"] += 1
        try:
            return pair(*args, **kwargs)
        finally:
            pairing["depth"] -= 1

    monkeypatch.setattr(socket.socket, "connect", counted_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", counted_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", counted_lookup)
    monkeypatch.setattr(socket, "socketpair", counted_pair)
    return {"seen": seen, "socketpair": internal, "refused": no_network.refused}


# ------------------------------------------------------------------------------ the film


def planned_film(engine, tmp_path: Path) -> str:
    """plan: the Nepal storyboard's six scenes (four LIVE, the 100/83 DATA_CARD, the BLACK
    end), its visual bible, and the model's own shot plan compiled into prompts."""
    storyboard_id = nepal_like(engine, tmp_path)
    plan = parse_shot_plan(SHOT_PACK.read_text(encoding="utf-8"))
    assert sorted(plan.shots) == [1, 2, 3, 4, 5, 6], plan.error
    bible = dict(PROMPTS["visual_bible"])
    with Session(engine) as session, session.begin():
        session.get(Storyboard, storyboard_id).visual_bible_json = bible
        rows = list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )
        packages = [
            {**plan.shots[row.scene_index].model_dump(), "scene_index": row.scene_index}
            | {"scene_kind": row.scene_kind}
            for row in rows
        ]
        compiled = compile_film_prompts(packages, bible, {"model_id": "seedance2_5"})
        for row, package, words in zip(rows, packages, compiled, strict=True):
            row.voiceover_segment = NARRATION[row.scene_index]
            row.duration_seconds = PLANNED_SECONDS
            row.prompt_json = {**package, **words, "source": "model"}
            if row.scene_kind == "LIVE":
                row.visual_prompt = words["still_prompt"]
    return storyboard_id


def lint_of(engine, storyboard_id: str) -> list:
    with Session(engine) as session:
        bible = session.get(Storyboard, storyboard_id).visual_bible_json
        rows = session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == storyboard_id)
            .order_by(StoryboardScene.scene_index)
        ).all()
        scenes = [
            LintScene(
                scene=row.scene_index,
                kind=row.scene_kind,
                still_prompt=str(row.prompt_json.get("still_prompt") or ""),
                motion_prompt=str(row.prompt_json.get("motion_prompt") or ""),
                model_id="seedance2_5",
            )
            for row in rows
        ]
    return lint_film(scenes, bible=bible)


def studio(client, tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """The vendors, faked, as the routes take them from ``app.state``; the vision judge of
    the stills gate is the only check faked (it is a paid agent run)."""
    account = RunwayAccount(10_000)
    images = Stills(account, detailed_stills(tmp_path))
    clip = moving_clip(tmp_path)
    models = Models(
        SpyVideo("seedance2_5", account, clip=clip), SpyVideo("veo3.1_fast", account, clip=clip)
    )
    judge = SpyJudge()
    monkeypatch.setattr(
        shooting_sheet,
        "run_stills_stage",
        functools.partial(shooting_sheet.run_stills_stage, judge=judge),
    )
    state = client.app.app.state
    state.media_storage_root = tmp_path / "media"
    state.scene_model_capabilities = [SEEDANCE, VEO_FAST]
    state.image_adapter = images
    state.runway_account = account
    state.video_adapter_for_model = models
    return {"account": account, "images": images, "models": models, "judge": judge}


def sheet(client, headers, storyboard_id: str) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


def step(client, headers, storyboard_id: str, name: str, plan_hash: str):
    return client.post(
        f"/api/v1/media/storyboards/{storyboard_id}/steps/{name}",
        headers=headers,
        json={"plan_hash": plan_hash},
    )


def owner_says_yes(client, headers, approval_id: str, note: str) -> None:
    """His "Aprobă" on the page: the decision route, as the Owner, with his note."""
    response = client.post(
        "/api/v1/owner/approvals/decision",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "approval_id": approval_id,
            "decision": "APPROVED",
            "note": note,
        },
    )
    assert response.status_code == 200, response.text


def climb(client, headers, storyboard_id: str, name: str, note: str) -> dict[str, Any]:
    """One stair: the sheet, his question (202, nothing bought), his yes, the purchase (200)."""
    plan_hash = sheet(client, headers, storyboard_id)["sheet_hash"]
    asked = step(client, headers, storyboard_id, name, plan_hash)
    assert asked.status_code == 202, asked.text
    owner_says_yes(client, headers, asked.json()["approval_id"], note)
    bought = step(client, headers, storyboard_id, name, plan_hash)
    assert bought.status_code == 200, bought.text
    return {"plan_hash": plan_hash, "approval_id": asked.json()["approval_id"], **bought.json()}


def hero_take(engine, storyboard_id: str) -> SceneTake:
    with Session(engine) as session:
        (take,) = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == storyboard_id, SceneTake.kind == "test_shot"
            )
        ).all()
        session.expunge(take)
        return take


def owner_approves_take(client, headers, take_id: str) -> None:
    response = client.post(
        f"/api/v1/media/takes/{take_id}/decision",
        headers=headers,
        json={"decision": "APPROVED", "note": "Cadrul de probă e bun."},
    )
    assert response.status_code == 200, response.text


def calls(world: dict[str, Any]) -> tuple[int, int, int]:
    """(image requests, seedance POSTs, veo POSTs) so far."""
    spies = world["models"].spies
    return (
        len(world["images"].asked),
        len(spies["seedance2_5"].asked),
        len(spies["veo3.1_fast"].asked),
    )


def approvals(engine) -> list[ApprovalRequest]:
    with Session(engine) as session:
        rows = list(session.scalars(select(ApprovalRequest).order_by(ApprovalRequest.created_at)))
        session.expunge_all()
        return rows


def takes(engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake)
                .where(SceneTake.storyboard_id == storyboard_id)
                .order_by(SceneTake.scene_number, SceneTake.created_at)
            )
        )
        session.expunge_all()
        return rows


def walk_the_staircase(client, headers, engine, storyboard_id: str, world) -> dict[str, Any]:
    """plan -> lint -> sheet -> stills -> hero (looked at) -> motion, as the Owner's page."""
    assert not has_block(lint_of(engine, storyboard_id))
    stills = climb(client, headers, storyboard_id, "stills", "Da, imaginile.")
    hero = climb(client, headers, storyboard_id, "test_shot", "Da, cadrul de probă.")
    owner_approves_take(client, headers, hero_take(engine, storyboard_id).id)
    motion = climb(client, headers, storyboard_id, "motion", "Da, restul mișcării.")
    return {"stills": stills, "test_shot": hero, "motion": motion}


# ------------------------------------- 1. exact calls per stair; the cards cost nothing


def test_each_stair_buys_exactly_its_own_calls_and_no_socket_is_opened(
    client, engine, headers, tmp_path, monkeypatch, sockets
):
    storyboard_id = planned_film(engine, tmp_path)
    world = studio(client, tmp_path, monkeypatch)

    # plan -> lint: the model's shot plan, compiled, carries no BLOCK; the cards no prompt.
    findings = lint_of(engine, storyboard_id)
    assert not has_block(findings), [f.as_dict() for f in findings if f.severity == "BLOCK"]
    first = sheet(client, headers, storyboard_id)
    assert first["lint_blocked"] is False and first["shot_plan_gaps"] == []
    kinds = {s["scene_index"]: s["kind"] for s in first["scenes"]}
    assert kinds == {1: "LIVE", 2: "LIVE", 3: "LIVE", 4: "LIVE", 5: "DATA_CARD", 6: "BLACK"}
    for n in (5, 6):
        card = first["scenes"][n - 1]
        assert card["still_prompt"] == "" and card["motion_prompt"] == ""
        assert card["motion"]["credits"] == 0 and card["still_credits"] == 0
    # Chosen per scene (the Owner, 2026-09-27): the hook on the premium model, the rest on
    # the cheapest capable one.
    models = {s["scene_index"]: s["motion"]["model_id"] for s in first["scenes"]}
    assert models[1] == "seedance2_5"
    assert {models[n] for n in (2, 3, 4)} == {"veo3.1_fast"}
    assert calls(world) == (0, 0, 0), "reading the sheet bought something"

    stills = climb(client, headers, storyboard_id, "stills", "Da, imaginile.")
    # 4 LIVE scenes x 1 request of 2 candidates; the chart and the black never asked for.
    assert calls(world) == (4, 0, 0)
    assert [r["count"] for r in world["images"].asked] == [2, 2, 2, 2]
    assert stills["bought_images"] == 8
    for n, request in zip(LIVE_SCENES, world["images"].asked, strict=True):
        assert request["prompt"].startswith(first["scenes"][n - 1]["still_prompt"][:60])
    assert len(world["judge"].looked_at) == 8
    by_scene = {s["scene_index"]: s for s in stills["scenes"]}
    assert all(by_scene[n]["status"] == "APPROVED" for n in LIVE_SCENES)
    assert by_scene[5]["status"] == by_scene[6]["status"] == "composed"

    hero = climb(client, headers, storyboard_id, "test_shot", "Da, cadrul de probă.")
    assert calls(world) == (4, 1, 0), "the hero step bought more than one shot"
    assert hero["bought_shots"] == 1
    # Nothing is animated until he has looked at the hero.
    waiting = step(
        client,
        headers,
        storyboard_id,
        "motion",
        sheet(client, headers, storyboard_id)["sheet_hash"],
    )
    assert waiting.status_code == 409 and waiting.json()["detail"]["status"] == "HERO_NOT_APPROVED"
    owner_approves_take(client, headers, hero_take(engine, storyboard_id).id)

    motion = climb(client, headers, storyboard_id, "motion", "Da, restul mișcării.")
    assert calls(world) == (4, 1, 3), "the motion step bought other than the three scenes"
    assert motion["bought_shots"] == 3

    # Every paid take, per scene and kind; nothing for scenes 5 and 6.
    rows = takes(engine, storyboard_id)
    assert {t.scene_number for t in rows} == set(LIVE_SCENES)
    assert [(t.scene_number, t.status) for t in rows if t.kind == "test_shot"] == [(1, "APPROVED")]
    assert sorted(t.scene_number for t in rows if t.kind == "motion") == [2, 3, 4]
    assert sum(1 for t in rows if t.kind == "still") == 8
    # Three questions, three yeses, each spent exactly once.
    asked = approvals(engine)
    assert [a.action for a in asked] == [
        "media.stills_purchase",
        "media.test_shot",
        "media.motion_purchase",
    ]
    assert all(a.result == "APPROVED" and a.consumed_at is not None for a in asked)
    with Session(engine) as session:
        consumed = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "governance.approval_consumed")
        ).all()
    assert len(consumed) == 3

    # No socket and no lookup, not even to loopback, outside the event loops' own wake-up
    # pairs (which stay on 127.0.0.1); nothing refused by the guard either.
    assert sockets["seen"] == [] and sockets["refused"] == []
    assert all(address[0] == "127.0.0.1" for address in sockets["socketpair"])


# ------------------------- 2. a stale hash, a spent yes or a short balance buys nothing


def refused(response, status: str) -> str:
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["status"] == status, detail
    return str(detail["message"])


def current_hash(client, headers, storyboard_id: str) -> str:
    return str(sheet(client, headers, storyboard_id)["sheet_hash"])


def test_at_every_stair_a_stale_hash_a_spent_yes_or_a_short_balance_buys_nothing(
    client, engine, headers, tmp_path, monkeypatch, sockets
):
    storyboard_id = planned_film(engine, tmp_path)
    world = studio(client, tmp_path, monkeypatch)
    account = world["account"]
    foreign = "0" * 64

    # ---- stills
    plan_hash = current_hash(client, headers, storyboard_id)
    refused(step(client, headers, storyboard_id, "stills", foreign), "STALE_PLAN")
    account.balance = 200  # the stills cap is 216 credits; with the 15% margin, 249
    message = refused(step(client, headers, storyboard_id, "stills", plan_hash), "LOW_BALANCE")
    assert "Sold Runway insuficient" in message and "216" in message
    assert approvals(engine) == [], "a short balance still asked the Owner"
    account.balance = 10_000
    asked = step(client, headers, storyboard_id, "stills", plan_hash)
    assert asked.status_code == 202, asked.text
    owner_says_yes(client, headers, asked.json()["approval_id"], "Da, imaginile.")
    # His yes is in hand, but the balance fell under the cap: still nothing is bought, and
    # the yes is not spent on a purchase that did not happen.
    account.balance = 200
    refused(step(client, headers, storyboard_id, "stills", plan_hash), "LOW_BALANCE")
    (yes,) = approvals(engine)
    assert yes.result == "APPROVED" and yes.consumed_at is None
    assert calls(world) == (0, 0, 0)
    account.balance = 10_000
    bought = step(client, headers, storyboard_id, "stills", plan_hash)
    assert bought.status_code == 200, bought.text
    assert calls(world) == (4, 0, 0)
    # The spent yes buys nothing again: its sheet is gone, and the new one has nothing left
    # on this stair.
    refused(step(client, headers, storyboard_id, "stills", plan_hash), "STALE_PLAN")
    now = current_hash(client, headers, storyboard_id)
    refused(step(client, headers, storyboard_id, "stills", now), "NOTHING_TO_BUY")
    assert calls(world) == (4, 0, 0)

    # ---- the hero test shot
    plan_hash = current_hash(client, headers, storyboard_id)
    account.balance = 700  # the hero's cap is 680 credits; with the margin, 782
    refused(step(client, headers, storyboard_id, "test_shot", plan_hash), "LOW_BALANCE")
    account.balance = 10_000
    asked = step(client, headers, storyboard_id, "test_shot", plan_hash)
    assert asked.status_code == 202, asked.text
    owner_says_yes(client, headers, asked.json()["approval_id"], "Da, cadrul de probă.")
    # After his yes he changes scene 3's model on the sheet: the sheet he said yes to is no
    # longer the sheet, so his yes buys nothing and stays unspent.
    changed = client.put(
        f"/api/v1/media/storyboards/{storyboard_id}/shooting-sheet/scenes/3/model",
        headers=headers,
        json={"model_id": "seedance2_5"},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["previous_sheet_hash"] == plan_hash != changed.json()["sheet_hash"]
    refused(step(client, headers, storyboard_id, "test_shot", plan_hash), "STALE_PLAN")
    stale_yes = next(a for a in approvals(engine) if a.action == "media.test_shot")
    assert stale_yes.consumed_at is None
    assert calls(world) == (4, 0, 0)
    hero = climb(client, headers, storyboard_id, "test_shot", "Da, pe foaia nouă.")
    assert calls(world) == (4, 1, 0)
    assert hero["approval_id"] != stale_yes.id
    refused(step(client, headers, storyboard_id, "test_shot", hero["plan_hash"]), "STALE_PLAN")
    now = current_hash(client, headers, storyboard_id)
    refused(step(client, headers, storyboard_id, "test_shot", now), "NOTHING_TO_BUY")
    assert calls(world) == (4, 1, 0)

    # ---- the rest of the motion
    before_look = current_hash(client, headers, storyboard_id)
    refused(step(client, headers, storyboard_id, "motion", before_look), "HERO_NOT_APPROVED")
    owner_approves_take(client, headers, hero_take(engine, storyboard_id).id)
    # His look at the hero is part of the sheet: a hash from before it is stale.
    refused(step(client, headers, storyboard_id, "motion", before_look), "STALE_PLAN")
    current = sheet(client, headers, storyboard_id)
    plan_hash = current["sheet_hash"]
    cap = current["steps"]["motion"]["cap_credits"]
    account.balance = cap  # the cap itself, without the 15% margin
    refused(step(client, headers, storyboard_id, "motion", plan_hash), "LOW_BALANCE")
    assert not any(a.action == "media.motion_purchase" for a in approvals(engine))
    account.balance = 10_000
    refused(step(client, headers, storyboard_id, "motion", foreign), "STALE_PLAN")
    motion = climb(client, headers, storyboard_id, "motion", "Da, restul mișcării.")
    # Scene 3 on the model he chose; scenes 2 and 4 on the cheapest capable one.
    assert calls(world) == (4, 2, 2)
    assert motion["bought_shots"] == 3
    refused(step(client, headers, storyboard_id, "motion", plan_hash), "STALE_PLAN")
    now = current_hash(client, headers, storyboard_id)
    refused(step(client, headers, storyboard_id, "motion", now), "NOTHING_TO_BUY")
    assert calls(world) == (4, 2, 2)
    clips = {t.scene_number: t.model_id for t in takes(engine, storyboard_id) if t.kind == "motion"}
    assert clips == {2: "veo3.1_fast", 3: "seedance2_5", 4: "veo3.1_fast"}

    # Exactly one yes spent per purchase; the yes the changed sheet made stale never was.
    spent = [a for a in approvals(engine) if a.consumed_at is not None]
    assert sorted(a.action for a in spent) == [
        "media.motion_purchase",
        "media.stills_purchase",
        "media.test_shot",
    ]
    assert stale_yes.id not in {a.id for a in spent}
    assert sockets["seen"] == [] and sockets["refused"] == []


# ------------------------------------- 3. the film passes the new QC; the report tells truth


def measured_spend(engine, storyboard_id: str) -> dict[str, dict[str, Any]]:
    """What the account's balance moved by on each stair, as each step recorded it in its
    own event, in the shape credit_spend writes (``production['credits_measured']``)."""
    spend: dict[str, dict[str, Any]] = {}
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent)
            .where(
                DomainEvent.event_type.in_(
                    ("media.stills_step_finished", "media.motion_step_finished")
                ),
                DomainEvent.aggregate_id == storyboard_id,
            )
            .order_by(DomainEvent.sequence)
        ).all()
        for event in events:
            data = event.payload
            label = str(data.get("step") or "stills")
            before, after = float(data["balance_before"]), float(data["balance_after"])
            spend[label] = {
                "kind": "runway",
                "unit": "credits",
                "before": before,
                "after": after,
                "spent": before - after,
                "usd": round((before - after) * 0.01, 4),
            }
    return spend


def test_the_film_assembled_from_its_takes_passes_qc_and_the_report_names_measured_credits(
    client, engine, headers, tmp_path, monkeypatch, settings, sockets
):
    storyboard_id = planned_film(engine, tmp_path)
    world = studio(client, tmp_path, monkeypatch)
    walk_the_staircase(client, headers, engine, storyboard_id, world)
    assert calls(world) == (4, 1, 3)
    voice = CountingVoice()

    film = assemble_from_takes(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        tts_adapter=voice,
        environment="TEST",
        settings=settings,
    )

    # Assembling bought nothing: every still and shot is a take, the cards are composed.
    assert calls(world) == (4, 1, 3), "assembling the film bought a still or a shot"
    assert voice.said == [NARRATION[n] for n in range(1, 7)]
    production = film["production"]
    scenes = {entry["scene_index"]: entry for entry in production["scenes"]}
    hero = hero_take(engine, storyboard_id)
    assert scenes[1]["motion"]["take_id"] == hero.id and scenes[1]["motion"]["reused_take"]
    for n in (2, 3, 4):
        assert scenes[n]["motion"]["reused_take"] is True
        assert scenes[n]["still_take"]["status"] == "APPROVED"
    for n, kind in ((5, "DATA_CARD"), (6, "BLACK")):
        card = scenes[n]["card"]
        assert card["kind"] == kind and card["provenance"] == "composed"
        assert card["credits"] == 0
    assert production["motion"]["fallback_scenes"] == 0
    assert production["timeline"]["fps"] == 24

    report = evaluate_media_qc(engine, film["output_asset_id"], str(uuid4()), settings=settings)

    assert report["status"] == "PASSED", report["failure_reasons_json"]
    assert report["score"] >= 0.90
    checks = report["checks_json"]
    assert checks["technical_qc"]["passed"] is True
    assert checks["audio_qc"]["passed"] is True

    # The money: what the vendor quoted and what the account's balance actually moved.
    rows = [t for t in takes(engine, storyboard_id) if t.status != "REJECTED"]
    quoted = sum(float(t.credits_quoted or 0) for t in rows)
    measured = sum(float(t.credits_measured or 0) for t in rows)
    stills_quote = 4 * 18
    hero_quote = price_shot("seedance2_5", "1080p", 5)
    rest_quote = 3 * price_shot("veo3.1_fast", "1080p", 6)
    assert quoted == pytest.approx(stills_quote + hero_quote + rest_quote)  # 72 + 340 + 180
    requests = 4 + 1 + 3
    assert measured == pytest.approx(quoted - REBATE * requests)  # 592 - 16 = 576
    spend = measured_spend(engine, storyboard_id)
    assert set(spend) == {"stills", "test_shot", "motion"}
    assert sum(item["spent"] for item in spend.values()) == pytest.approx(measured)

    summary = qc_summary_ro(report, spend)

    assert summary.startswith("Controlul calității: TRECUT")
    assert "Ce a picat: nimic din ce s-a măsurat." in summary
    usd = ro_number(measured * 0.01, 2)
    assert f"Credite măsurate: Runway {ro_count(measured, 'credite')} ({usd} USD)." in summary
    # The vendor's own quotes never stand in for what was charged.
    assert ro_number(quoted) not in summary
    assert "De plătit: 0 credite" in summary
    # Nothing was measured, nothing is reported as spent.
    assert "necunoscut" in qc_summary_ro(report, None)
    assert sockets["seen"] == [] and sockets["refused"] == []


# ------------------------- 4. under his MODE rule clip QC accepts the hero; the sheet says so


def passing_clip_qc(monkeypatch) -> None:
    """qc.check_clip, faked: every shot reads as passed (the real check is tested on its own)."""
    from app.media import qc as clip_qc

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


def test_under_mode_the_sheet_names_clip_qc_acceptance_and_the_motion_needs_no_look(
    client, engine, headers, tmp_path, monkeypatch, sockets
):
    from app.models import OwnerPolicy

    storyboard_id = planned_film(engine, tmp_path)
    world = studio(client, tmp_path, monkeypatch)
    passing_clip_qc(monkeypatch)

    # His default rule, EVERY_PAID_STEP: the sheet says he looks at the hero himself.
    every = sheet(client, headers, storyboard_id)["steps"]["motion"]
    assert every["hero"]["rule_accepts"] is False
    assert "Proprietarul" in every["waiting_ro"]
    assert "controlul clipului" not in every["waiting_ro"]

    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_mode = "AUTONOMOUS_CEO"
        policy.autonomy_stopped = False
        policy.paid_media_approval = "MODE"

    first = sheet(client, headers, storyboard_id)["steps"]["motion"]
    assert first["hero"]["rule_accepts"] is True, first["hero"]
    assert "controlul clipului" in first["waiting_ro"]
    assert "regula ta" in first["waiting_ro"]

    for name in ("stills", "test_shot"):
        bought = step(
            client, headers, storyboard_id, name, current_hash(client, headers, storyboard_id)
        )
        assert bought.status_code == 200, bought.text
    assert calls(world) == (4, 1, 0)
    before = sheet(client, headers, storyboard_id)["steps"]["motion"]["hero"]
    assert before["status"] == "ACCEPTS" and before["clip_verdict"] == "PASSED"
    assert "a trecut controlul clipului" in before["reason_ro"]

    motion = step(
        client, headers, storyboard_id, "motion", current_hash(client, headers, storyboard_id)
    )

    assert motion.status_code == 200, motion.text
    assert calls(world) == (4, 1, 3)
    assert motion.json()["hero_accepted"]["approved_by"] == "clip_qc"
    after = sheet(client, headers, storyboard_id)
    assert after["steps"]["motion"]["hero"]["status"] == "ACCEPTED"
    (shot,) = after["scenes"][0]["shots"]
    assert shot["status"] == "PAID" and shot["accepted_by"] == "clip_qc"
    assert shot["accepted_ro"] == "acceptat de controlul clipului"
    assert after["scenes"][0]["motion"]["accepted_by"] == "clip_qc"
    assert approvals(engine) == [], "the Owner was asked under his MODE rule"
    assert sockets["seen"] == [] and sockets["refused"] == []
