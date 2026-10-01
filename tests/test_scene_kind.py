"""Scene kinds, per scene (SCENE_KINDS, 2026-09-27).

The Nepal film (storyboard 1d530880) was one storyboard-wide ``MOTION_GRAPHIC`` copied onto
every scene, and every scene went to a photographic image model. Scene 5 asked for "two
vertical bars side by side" (100 vs 83 billion dollars) and got a woman beside two abstract
bars; scene 6 asked for "a black screen" and got a woman in a landscape. Both were paid for.

Now every scene carries its own kind - LIVE, DATA_CARD, TITLE_CARD or BLACK:

- the writer declares it, and a DATA_CARD carries its card: bars whose value and unit come
  from a SUPPORTED claim, each bar naming that claim;
- a deterministic classifier backs the writer up: chart or bar wording forces DATA_CARD, a
  black screen or a fade to black forces BLACK, even when the writer said LIVE;
- a card value or unit that no SUPPORTED claim carries fails the gate, at the writer and again
  when the storyboard is built; nothing is stored;
- the storyboard stores the kind and the card per scene and copies no style onto its scenes,
  and the daily stage no longer names a style at all.

Every model here is scripted; nothing leaves the machine.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.factual.agent_pipeline import ScriptRejected, _write_instructions, agent_write_script
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.factual.services import FactualGateError
from app.media.models import Storyboard, StoryboardScene
from app.media.services import (
    card_problems,
    classify_scene_kind,
    generate_storyboard_from_script,
    get_storyboard,
)
from app.models import DomainEvent, OwnerPolicy
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

FIXTURE = Path(__file__).parent / "fixtures" / "nepal_1d530880" / "script.json"
PROMISED = "c4a0e6c8-c71f-48d4-93c3-089148a27790"
DELIVERED = "d3561aea-dcaa-4f19-aa4a-23b80a1c52ef"
EMISSIONS = "701883c4-24e8-4295-976e-6c04c5ceceee"


def nepal() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def nepal_claims() -> dict[str, tuple[str, str]]:
    return {c["id"]: (c["claim_text"], c["status"]) for c in nepal()["claims"]}


@pytest.fixture
def nepal_topic(engine) -> str:
    """The Nepal topic with its six SUPPORTED claims, under their real identifiers."""
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    data = nepal()
    topic_id = data["topic_id"]
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        event = append_event(
            session, "factual.topic_proposed", "topic_idea", topic_id, 1, {}, str(uuid4())
        )
        session.add(
            TopicIdea(
                id=topic_id,
                title="Nepal's climate bill",
                topic="climate",
                angle="A bill it cannot pay",
                status="SELECTED",
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        for claim in data["claims"]:
            session.add(
                FactualClaim(
                    id=claim["id"],
                    topic_id=topic_id,
                    claim_text=claim["claim_text"],
                    claim_type=claim["claim_type"],
                    importance=claim["importance"],
                    status=claim["status"],
                    confidence=0.9,
                    evidence_text=claim["claim_text"],
                    created_at=utc_now(),
                )
            )
    return topic_id


def scripted_writer(monkeypatch, *answers: str) -> list[str]:
    """The writer answers from a script; returns the prompts it was given."""
    from app.factual import agent_pipeline

    prompts: list[str] = []
    queue = list(answers)

    def fake_run(_engine, _registry, _agent_id, _task, prompt, *args, **kwargs):
        prompts.append(prompt)
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return {"id": str(uuid4()), "status": "SUCCEEDED", "output_text": text}

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    monkeypatch.setattr(agent_pipeline, "_announce", lambda *a, **k: None)
    return prompts


def write(engine, topic_id: str) -> dict[str, Any]:
    return agent_write_script(engine, object(), topic_id, str(uuid4()), target_duration_seconds=30)


def approve(engine, script_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.get(ScriptDraft, script_id).status = "APPROVED"


def a_script(engine, topic_id: str, scenes: list[dict]) -> str:
    """An APPROVED script stored as given, for the storyboard's own gate."""
    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=nepal()["title"],
                target_duration_seconds=30,
                voiceover_full_text=" ".join(s["narration"] for s in scenes),
                scenes_json=scenes,
                status="APPROVED",
                claim_ids_json=sorted({c for s in scenes for c in s["claim_ids"]}),
                unverified_claim_ids_json=[],
                story_json=nepal()["story"],
                created_at=utc_now(),
            )
        )
    return script_id


def scene_rows(engine, storyboard_id: str) -> list[StoryboardScene]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(StoryboardScene)
                .where(StoryboardScene.storyboard_id == storyboard_id)
                .order_by(StoryboardScene.scene_index)
            )
        )


def answer_with_card(card: dict | None) -> str:
    answer = copy.deepcopy(nepal()["writer_answer"])
    answer["scenes"][4]["card"] = card
    return json.dumps(answer, ensure_ascii=False)


def nepal_card(**bar_changes: Any) -> dict:
    card = copy.deepcopy(nepal()["writer_answer"]["scenes"][4]["card"])
    card["bars"][1].update(bar_changes)
    return card


# ---------------------------------------------------------------------------
# The Nepal script, through the writer and the storyboard
# ---------------------------------------------------------------------------


def test_the_nepal_script_gives_a_data_card_a_black_screen_and_four_live_scenes(
    engine, nepal_topic, monkeypatch
):
    scripted_writer(monkeypatch, json.dumps(nepal()["writer_answer"], ensure_ascii=False))
    written = write(engine, nepal_topic)

    stored = written["script"]["scenes_json"]
    assert [s["scene_kind"] for s in stored] == ["LIVE"] * 4 + ["DATA_CARD", "BLACK"]
    # The writer said LIVE for "A black screen"; the classifier says why it overruled him.
    assert "black screen" in stored[5]["kind_forced_by"].lower()
    assert stored[4].get("kind_forced_by") is None  # the writer already said DATA_CARD

    approve(engine, written["script"]["id"])
    board = generate_storyboard_from_script(engine, written["script"]["id"], None, "9:16", "c")
    rows = scene_rows(engine, board["id"])
    assert [r.scene_kind for r in rows] == ["LIVE"] * 4 + ["DATA_CARD", "BLACK"]

    card = rows[4].card_json
    assert [bar["value"] for bar in card["bars"]] == [100, 83]
    assert [bar["claim_id"] for bar in card["bars"]] == [PROMISED, DELIVERED]
    assert {bar["unit"] for bar in card["bars"]} == {"mld. USD"}
    # Every claim a bar rests on is a claim the scene cites.
    assert {PROMISED, DELIVERED} <= set(rows[4].claim_ids_json)
    assert all(r.card_json is None for r in rows[:4])

    # The API view carries the kind and the card too.
    view = get_storyboard(engine, board["id"])
    assert [s["scene_kind"] for s in view["scenes"]] == [r.scene_kind for r in rows]
    assert view["scenes"][4]["card_json"]["bars"][1]["value"] == 83


def test_the_stored_nepal_script_is_read_the_same_way_without_the_writers_kinds(
    engine, nepal_topic
):
    """The script as the old writer stored it has no kinds at all: the words decide."""
    script_id = a_script(engine, nepal_topic, nepal()["stored_scenes"])

    board = generate_storyboard_from_script(engine, script_id, None, "9:16", "c")
    rows = scene_rows(engine, board["id"])

    assert [r.scene_kind for r in rows] == ["LIVE"] * 4 + ["DATA_CARD", "BLACK"]
    # No card was ever written for the chart: it is recorded as missing, never invented,
    # and the scene can no longer be bought from a photographic model as LIVE.
    assert rows[4].card_json is None
    with Session(engine) as session:
        payload = session.scalar(
            select(DomainEvent.payload).where(
                DomainEvent.event_type == "media.storyboard_created",
                DomainEvent.aggregate_id == board["id"],
            )
        )
    assert payload["scene_kinds"] == ["LIVE"] * 4 + ["DATA_CARD", "BLACK"]
    assert payload["cards_missing"] == [5]
    assert payload["kinds_forced"] == {"5": "vertical bars", "6": "black screen"}


# ---------------------------------------------------------------------------
# The classifier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("visual", "kind"),
    [
        ("Two vertical bars side by side: the first fills to the top.", "DATA_CARD"),
        ("A bar chart of the money promised and the money delivered.", "DATA_CARD"),
        ("A simple chart rising from left to right.", "DATA_CARD"),
        ("A black screen, silent and still.", "BLACK"),
        ("The valley at dusk, then the picture fades to black.", "BLACK"),
        ("Fade to black.", "BLACK"),
        ("The film's title card over the mountains.", "TITLE_CARD"),
        ("Aerial view of Himalayan mountains with dark storm clouds.", "LIVE"),
        ("A browser bar with the address typed into it.", "LIVE"),
    ],
)
def test_the_classifier_forces_the_kind_even_when_the_writer_said_live(visual, kind):
    decided, evidence = classify_scene_kind("LIVE", visual)
    assert decided == kind
    assert (evidence is None) == (kind == "LIVE")
    # With no declaration at all the words decide just the same.
    assert classify_scene_kind(None, visual)[0] == kind


def test_the_earliest_phrase_wins_and_a_declared_card_is_kept():
    # Nepal scene 5 asks for bars first and a fade to black after: it is a chart.
    visual = nepal()["stored_scenes"][4]["visual_description"]
    assert classify_scene_kind("LIVE", visual) == ("DATA_CARD", "vertical bars")
    # A writer who chose a card is never turned back into a paid LIVE shot by his words.
    assert classify_scene_kind("TITLE_CARD", "The mountains at dawn.") == ("TITLE_CARD", None)
    assert classify_scene_kind("BLACK", "Silence.") == ("BLACK", None)
    # A kind nobody knows is read as LIVE, then judged by its words like any other.
    assert classify_scene_kind("CHART", "A black screen.") == ("BLACK", "black screen")
    assert classify_scene_kind("lIvE", "Rain on a roof.") == ("LIVE", None)


def test_two_comparable_numbers_from_the_scenes_claims_make_a_chart():
    claims = [nepal_claims()[EMISSIONS][0]]  # "95% ... with 77% from the forestry sector"
    said = "95% of Nepal's emissions come from farms and forests, 77% from forests alone."
    assert classify_scene_kind("LIVE", "A terraced field.", said, claims)[0] == "DATA_CARD"
    # The same two numbers with nothing behind them in the claims decide nothing.
    assert classify_scene_kind("LIVE", "A terraced field.", said, ["No numbers."])[0] == "LIVE"
    # Numbers of different kinds do not compare: a year is not an amount.
    flood = "In 2018 floods cost Nepal US$600 million."
    flood_claim = [nepal_claims()["3ab56ae3-1d30-458c-9a66-b0edb953a838"][0]]
    assert classify_scene_kind("LIVE", "Mudslides.", flood, flood_claim)[0] == "LIVE"
    # The Nepal narration says its numbers in words: its kind comes from the picture asked.
    scene4 = nepal()["stored_scenes"][3]
    assert (
        classify_scene_kind(None, scene4["visual_description"], scene4["narration"], claims)[0]
        == "LIVE"
    )


# ---------------------------------------------------------------------------
# A card value or unit must be one a SUPPORTED claim carries
# ---------------------------------------------------------------------------


def test_the_nepal_card_matches_its_claims():
    card = nepal()["writer_answer"]["scenes"][4]["card"]
    assert card_problems(5, "DATA_CARD", card, nepal_claims()) == []
    # 83.3 exactly, the same unit written the long way, and in dollars instead of billions.
    assert card_problems(5, "DATA_CARD", nepal_card(value=83.3), nepal_claims()) == []
    long_unit = copy.deepcopy(card)
    for bar in long_unit["bars"]:
        bar["unit"] = "miliarde de dolari"
    assert card_problems(5, "DATA_CARD", long_unit, nepal_claims()) == []


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"value": 95}, "95"),  # a number the claim never states
        ({"value": 89}, "89"),  # 89.6 rounds to 90, never to 89
        ({"value": 84}, "84"),  # 83.3 does not round to 84
        ({"value": 8.3}, "8,3"),  # right digits, wrong magnitude
        ({"unit": "%"}, "%"),  # right number, wrong unit
        ({"unit": "mld. EUR"}, "EUR"),  # right number, wrong currency
        ({"unit": "milioane USD"}, "milioane"),  # right number, wrong scale
    ],
)
def test_a_card_value_or_unit_no_claim_carries_is_named(change, words):
    card = copy.deepcopy(nepal()["writer_answer"]["scenes"][4]["card"])
    for bar in card["bars"]:
        if "unit" in change:
            bar["unit"] = change["unit"]
    if "value" in change:
        card["bars"][1]["value"] = change["value"]
    problems = card_problems(5, "DATA_CARD", card, nepal_claims())
    assert problems, change
    assert all(p.startswith("Scena 5") for p in problems)
    assert any(words in p for p in problems)


def test_a_card_resting_on_an_unsupported_or_unknown_claim_is_refused():
    claims = dict(nepal_claims())
    claims[DELIVERED] = (claims[DELIVERED][0], "UNCERTAIN")
    problems = card_problems(5, "DATA_CARD", nepal_card(), claims)
    assert any("SUSȚINUTĂ" in p for p in problems)

    unknown = card_problems(5, "DATA_CARD", nepal_card(claim_id="nope"), nepal_claims())
    assert any("nope" in p for p in unknown)


def test_a_chart_without_its_numbers_and_a_broken_card_are_named():
    assert "cifrele" in card_problems(5, "DATA_CARD", None, nepal_claims())[0]
    broken = card_problems(5, "DATA_CARD", {"bars": []}, nepal_claims())
    assert broken and "bară" in broken[0]
    # A title card needs its title; a black screen needs nothing.
    assert card_problems(6, "TITLE_CARD", None, nepal_claims())
    assert card_problems(6, "BLACK", None, nepal_claims()) == []
    assert card_problems(1, "LIVE", None, nepal_claims()) == []
    # Words on a card may not carry a number the claims never state.
    assert card_problems(6, "BLACK", {"cta": "Doar 41 de miliarde au sosit."}, nepal_claims())
    assert card_problems(6, "BLACK", {"cta": "Promis: 100 de miliarde."}, nepal_claims()) == []


def test_a_false_card_fails_the_writer_after_one_re_ask_and_nothing_is_stored(
    engine, nepal_topic, monkeypatch
):
    prompts = scripted_writer(monkeypatch, answer_with_card(nepal_card(value=95)))
    with pytest.raises(ScriptRejected, match="Scena 5"):
        write(engine, nepal_topic)
    assert len(prompts) == 2
    assert "95" in prompts[1] and "Scena 5" in prompts[1]
    with Session(engine) as session:
        assert session.scalars(select(ScriptDraft)).all() == []


def test_a_writer_who_corrects_his_card_on_the_re_ask_is_stored(engine, nepal_topic, monkeypatch):
    prompts = scripted_writer(
        monkeypatch,
        answer_with_card(nepal_card(unit="%")),
        answer_with_card(nepal_card()),
    )
    written = write(engine, nepal_topic)
    assert len(prompts) == 2
    assert written["script"]["scenes_json"][4]["card"]["bars"][1]["unit"] == "mld. USD"


def test_a_writer_chart_with_no_card_is_asked_for_its_numbers(engine, nepal_topic, monkeypatch):
    prompts = scripted_writer(monkeypatch, answer_with_card(None))
    with pytest.raises(ScriptRejected, match="cifrele"):
        write(engine, nepal_topic)
    assert len(prompts) == 2


def test_a_false_card_fails_the_storyboards_gate_and_nothing_is_stored(engine, nepal_topic):
    scenes = copy.deepcopy(nepal()["stored_scenes"])
    scenes[4]["scene_kind"] = "DATA_CARD"
    scenes[4]["card"] = nepal_card(value=95)
    script_id = a_script(engine, nepal_topic, scenes)

    with pytest.raises(FactualGateError, match="Scena 5"):
        generate_storyboard_from_script(engine, script_id, None, "9:16", "c")
    with Session(engine) as session:
        assert session.scalars(select(Storyboard)).all() == []

    # A card resting on a claim that is no longer SUPPORTED is refused the same way.
    scenes[4]["card"] = nepal_card()
    with Session(engine) as session, session.begin():
        session.get(FactualClaim, DELIVERED).status = "REFUTED"
    script_id = a_script(engine, nepal_topic, scenes)
    with pytest.raises(FactualGateError, match="SUSȚINUTĂ"):
        generate_storyboard_from_script(engine, script_id, None, "9:16", "c")


# ---------------------------------------------------------------------------
# The brief, the storyboard's style and the daily stage
# ---------------------------------------------------------------------------


def test_the_writers_brief_shows_people_from_afar_and_asks_for_each_scenes_kind():
    brief = _write_instructions(30)
    assert "reacția unui om" not in brief
    assert "văzuți de departe sau din spate" in brief
    for kind in ("LIVE", "DATA_CARD", "TITLE_CARD", "BLACK"):
        assert kind in brief
    assert '"card"' in brief and '"claim_id"' in brief


def test_the_storyboard_stores_each_scenes_kind_and_copies_no_style(engine, nepal_topic):
    scenes = copy.deepcopy(nepal()["stored_scenes"])
    scenes[4]["scene_kind"] = "DATA_CARD"
    scenes[4]["card"] = nepal_card()
    script_id = a_script(engine, nepal_topic, scenes)

    # A caller that still names a style keeps it on the board as his word, and no scene
    # inherits it: each scene's type is its own kind.
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    rows = scene_rows(engine, board["id"])
    assert [r.visual_type for r in rows] == [r.scene_kind for r in rows]
    assert "MOTION_GRAPHIC" not in {r.visual_type for r in rows}

    # Without one, the board says its style is decided scene by scene.
    other = a_script(engine, nepal_topic, scenes)
    board = generate_storyboard_from_script(engine, other, None, "9:16", "c")
    with Session(engine) as session:
        assert session.get(Storyboard, board["id"]).visual_style == "PER_SCENE"


def test_the_daily_stage_no_longer_hard_codes_a_style():
    from app.runbook import stages

    source = Path(stages.__file__).read_text(encoding="utf-8")
    assert "MOTION_GRAPHIC" not in source
