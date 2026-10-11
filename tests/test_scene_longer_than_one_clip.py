"""A scene longer than one clip of its model (film 6fe6a577, 2026-10-10).

«How NASA Keeps a Space Telescope Alive With Frozen Fuel»: scenes 3 and 4 carried words
estimated at 11.1 s and 12.5 s of clip, and LTX-2.5's clips end at 10 s. The sheet held both
scenes for the Owner («nu ține 11,1 s într-un singur cadru») while its steps would buy the
stills, the test shot and the other scenes' clips (about 1.8 USD), after which the assembly
refused the two scenes and the film stood until the Director retired it. The studio already
slows a short clip locally by up to 25% (the Owner's «Încetinește local»), so:

- (1) a scene up to 25% over the model's longest clip is planned, priced and bought at that
  clip, and the assembly slows it (0 USD); the sheet says so in his words;
- (2) a scene longer even than that blocks the film's sheet before anything is bought, and the
  sheet's issue scan hands it to the Director's repair, which rewrites the story with the scene
  split: never a question to the Owner, never a still for a film that cannot be finished;
- (3) the Director's story review refuses such a scene with its exact seconds, so the writer
  splits it before a board exists.

Every provider is faked; no socket is opened and no credit is spent.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.story_review import review_story
from app.media import blocker_repair
from app.media import sheet_story_repair as story
from app.media.assembler import SLOWDOWN_ALLOWANCE, motion_plan
from app.media.cost_plan import price_shot
from app.media.models import SceneTake
from app.media.production_policy import ModelCapability
from app.media.shooting_sheet import SheetStepRefused, build_sheet, run_sheet_step
from app.media.toolchain import find_ffmpeg
from app.models import OwnerPolicy
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from test_clip_fits_narration import a_board
from test_editorial_quality import GOOD_SCENES, a_script, a_topic, studio  # noqa: F401
from test_film_costing import Account, Models, SpyVideo, approved, by_scene, hero_approved
from test_runpod_pipeline import connect
from test_sheet_blocker_repair import film  # noqa: F401

#: The profile the Owner selected, as the NASA film's sheet read it: one cloud model whose clips
#: end at 10 s, taken unasked by quality («Totul pe RunPod oricum»). seedance2_5 lends it a
#: published price; its own contract (4-30 s) is replaced by the 10 s maximum.
PROFILE = ModelCapability(
    model_id="seedance2_5",
    quality=0.5,
    seconds={"min": 1, "max": 10},
    ratios=("1080:1920", "720:1280"),
    tasks=("image_to_video",),
    selected_default=True,
)


def words(count: int) -> str:
    return " ".join(["word"] * count)


#: 28 spoken words: 11.2 s estimated, + 0.12 s breath + 10% margin = 12.458 s of clip (the
#: NASA film's scene 4), 24.6% over a 10 s clip. 30 words: 13.333 s, 33% over.
FITS_SLOWED = words(28)
TOO_LONG = words(30)


def shot_takes(engine: Engine, storyboard_id: str) -> list[SceneTake]:
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == storyboard_id,
                    SceneTake.kind.in_(("test_shot", "motion")),
                )
            )
        )
        session.expunge_all()
        return rows


# ------------------------------------------------- (1) bought at the model's longest clip


def test_a_scene_up_to_a_quarter_over_the_longest_clip_is_planned_at_that_clip(
    engine: Engine, tmp_path: Path
) -> None:
    assert SLOWDOWN_ALLOWANCE == 0.25
    storyboard_id = a_board(engine, tmp_path, ["Scene one.", FITS_SLOWED, "Scene three."])

    plan = motion_plan(engine, storyboard_id, capabilities=[PROFILE])
    scene = by_scene(plan)[2]
    assert scene["seconds"] == 12.458
    assert scene["status"] == "PLANNED", scene["reason_ro"]
    # The clip actually bought, at its price: 10 s, never the 13 s the words alone would ask.
    assert scene["billed_seconds"] == 10
    assert scene["credits"] == price_shot("seedance2_5", "1080p", 10)
    assert 2 in plan["steps"]["motion"]["to_buy"]

    sheet = build_sheet(engine, storyboard_id, capabilities=[PROFILE], read_live=False)
    motion = sheet["scenes"][1]["motion"]
    assert motion["status"] == "PLANNED" and motion["billed_seconds"] == 10
    assert motion["slowed"] == {"clip_seconds": 10, "needed_seconds": 12.458, "percent": 25}
    assert (
        "Scena cere 12,5 s, peste cele 10 s pe care seedance2_5 le filmează într-un cadru: "
        "clipul de 10 s se încetinește local la asamblare (cu până la 25%), 0 USD."
    ) in motion["reason_ro"]
    assert not sheet["lint_blocked"]
    assert "Așteaptă Proprietarul" not in str(sheet["footer"]["summary_ro"])


@pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")
def test_the_test_shot_and_the_motion_step_buy_and_price_the_longest_clip(
    engine: Engine, tmp_path: Path
) -> None:
    storyboard_id = a_board(engine, tmp_path, [FITS_SLOWED, FITS_SLOWED])
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    spy = models.spies["seedance2_5"]

    hero_approved(engine, storyboard_id, tmp_path, models, account, capabilities=[PROFILE])
    assert [ask["seconds"] for ask in spy.asked] == [10]
    result = approved(
        engine, storyboard_id, tmp_path, "motion", models, account, capabilities=[PROFILE]
    )
    assert by_scene(result)[2]["status"] == "PAID"
    assert [ask["seconds"] for ask in spy.asked] == [10, 10]
    # What the fake account lost is what the plan priced: two 10 s clips.
    assert account.balance == 10_000 - 2 * price_shot("seedance2_5", "1080p", 10)


# ------------------------------------------ (2) longer even slowed: blocked, never bought


def test_a_scene_no_clip_carries_even_slowed_blocks_the_film_before_anything_is_bought(
    engine: Engine, tmp_path: Path
) -> None:
    storyboard_id = a_board(engine, tmp_path, ["Scene one.", TOO_LONG, "Scene three."])
    sheet = build_sheet(engine, storyboard_id, capabilities=[PROFILE], read_live=False)

    motion = sheet["scenes"][1]["motion"]
    assert motion["status"] == "NEEDS_OWNER"
    assert motion["too_long"] == {
        "model_id": "seedance2_5",
        "seconds": 13.333,
        "longest_seconds": 10,
        "limit_seconds": 12.5,
        "reason_ro": (
            "Scena 2 cere un cadru de 13,3 s; seedance2_5 filmează cel mult 10 s într-un "
            "cadru, iar studioul îl încetinește local cu cel mult 25% (12,5 s). Nu se cumpără "
            "nimic pentru film: Directorul rescrie povestea cu scena împărțită în scene mai "
            "scurte."
        ),
    }
    assert sheet["lint_blocked"]
    assert [(b["code"], b["scene"]) for b in sheet["blocks"]] == [("SCENE_TOO_LONG", 2)]
    # The sheet's issue scan hands it to the Director, as every block.
    issues = blocker_repair.sheet_issues(sheet)
    assert any(i["code"] == "SCENE_TOO_LONG" and i["scene_index"] == 2 for i in issues)

    # Neither the day's staircase nor his own press buys the test shot of such a film.
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    for unasked in (True, False):
        with pytest.raises(SheetStepRefused) as refused:
            run_sheet_step(
                engine,
                storyboard_id,
                "test_shot",
                sheet["sheet_hash"],
                correlation_id=str(uuid4()),
                capabilities=[PROFILE],
                adapter_for_model=models,
                account=account,
                storage_root=tmp_path / "media",
                unasked=unasked,
            )
        assert refused.value.status == "LINT_BLOCKED"
    assert models.posts() == 0 and account.reads == 0
    assert shot_takes(engine, storyboard_id) == []


def test_the_scan_reports_the_scene_to_the_director_not_to_the_owner(
    engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.models import AgentMessage
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        assert policy is not None
        policy.autonomy_stopped = False
    storyboard_id = a_board(engine, tmp_path, ["Scene one.", TOO_LONG, "Scene three."])

    found = blocker_repair.scan_sheet_issues(engine, capabilities=[PROFILE])
    assert storyboard_id in found["reported"]
    with Session(engine) as session:
        letters = list(session.scalars(select(AgentMessage)))
    report = next(
        m for m in letters if (m.body_json or {}).get("kind") == blocker_repair.REPORT_KIND
    )
    assert report.to_agent_id is not None and report.body_json.get("to") != "Owner"
    assert not any((m.body_json or {}).get("to") == "Owner" for m in letters)
    assert any(
        i["code"] == "SCENE_TOO_LONG" and i["scene_index"] == 2 for i in report.body_json["issues"]
    )


def test_the_directors_repair_rewrites_the_story_with_the_scene_split(
    engine: Engine,
    film: str,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The story passed its review; only the length of one scene sends it back to the writer.
    monkeypatch.setattr(story, "story_gate", lambda *a: (True, ""))
    asked: list[list[str]] = []

    def writer(*_args: object, notes: list[str], **_kwargs: object) -> dict:
        asked.append(list(notes))
        raise story.ScriptRejected("Writer returned no usable script")

    monkeypatch.setattr(story, "agent_write_script", writer)
    detail = (
        "Scena 2 cere un cadru de 13,3 s; LTX-2.5 filmează cel mult 10 s într-un cadru, iar "
        "studioul îl încetinește local cu cel mult 25% (12,5 s)."
    )
    result = story.repair_story(
        engine,
        object(),
        film,
        "test",
        "report",
        [{"kind": "PROMPT", "code": "SCENE_TOO_LONG", "scene_index": 2, "detail": detail}],
    )
    assert result is not None and result["status"] == "UNRESOLVED"
    assert result["responsible_role"] == "ScriptWriter"
    assert len(asked) == 1
    assert detail in asked[0]
    assert any("split it into two scenes" in note for note in asked[0])


# ------------------------------------------------ (3) the story review says it first


def test_the_story_review_refuses_a_scene_one_clip_cannot_carry_with_its_seconds(
    engine: Engine,
    studio: dict,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The studio's motion profile: LTX-2.5 on RunPod (its offline catalogue: clips up to 5 s,
    # so a scene's clip may be at most 6.25 s once slowed).
    connect(engine, tmp_path, monkeypatch)
    topic_id = a_topic(engine)
    fitting = a_script(engine, topic_id)
    assert review_story(engine, None, fitting, str(uuid4()), target_seconds=20)["verdict"] == (
        "PASS"
    )

    long_scene = (
        "That is because the address was set aside before the web grew up, long before "
        "any company could ever even ask for it."
    )
    scenes = [
        {**scene, "narration": long_scene} if scene["scene_number"] == 3 else dict(scene)
        for scene in GOOD_SCENES
    ]
    refused = review_story(
        engine, None, a_script(engine, topic_id, scenes=scenes), str(uuid4()), target_seconds=20
    )
    assert refused["verdict"] == "REVISE"
    assert refused["failed"] == ["every_scene_fits_one_clip"]
    # 23 spoken words: 9.2 s + 0.12 s breath + 10% margin, on whole frames: 10.25 s.
    assert (
        "Scena 3 cere un cadru de 10,25 s (23 de cuvinte rostite); LTX-2.5 filmează cel mult "
        "5 s într-un cadru, iar studioul îl încetinește local cu cel mult 25% (6,25 s). "
        "Împarte scena în două scene, fiecare cu imaginea ei, sau scurtează-i narațiunea."
    ) in refused["notes"]
