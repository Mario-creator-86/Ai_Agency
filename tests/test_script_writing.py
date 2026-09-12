"""The script writer may only put verified facts into a voiceover.

A factual channel's script is the last artefact before a video is spoken aloud, and the factual
gate downstream can only check the claim ids a draft cites. So the attribution has to be real:
a scene citing an identifier that was never supplied means the narration around it came from
somewhere other than the evidence, and there is no way to tell which sentence.

These tests cover what the writer refuses to produce as closely as what it produces.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.factual.agent_pipeline import NoVerifiedClaims, ScriptRejected, agent_write_script
from app.factual.models import ScriptDraft
from app.factual.schemas import ExtractClaimItem
from app.factual.services import (
    extract_claims,
    ingest_source_snapshot,
    propose_topic_idea,
    verify_claim,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

SOURCE_TEXT = (
    "The Hubble Space Telescope was launched in 1990. It orbits about 540 kilometres above "
    "Earth and has made more than one and a half million observations."
)
CLAIMS = [
    "The Hubble Space Telescope was launched in 1990.",
    "Hubble orbits about 540 kilometres above Earth.",
]


@pytest.fixture
def topic_with_claims(engine):
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    topic = propose_topic_idea(
        engine, "Hubble", "Hubble telescope", "Discovery", "general", str(uuid4())
    )
    source = ingest_source_snapshot(
        engine,
        "https://example.org/hubble",
        "Hubble",
        "example.org",
        None,
        SOURCE_TEXT,
        0,
        str(uuid4()),
        topic_id=topic["id"],
    )
    claims = extract_claims(
        engine,
        source["id"],
        [ExtractClaimItem(claim_text=text, confidence=0.9) for text in CLAIMS],
        str(uuid4()),
        topic_id=topic["id"],
    )
    return {"topic_id": topic["id"], "claim_ids": [c["id"] for c in claims]}


def support(engine, claim_id: str, quote: str) -> None:
    verify_claim(engine, claim_id, "SUPPORTED", 0.95, "Sursa o afirmă.", quote, str(uuid4()))


def script_answer(scenes: list[dict], title: str = "Hubble la 540 de kilometri") -> str:
    return json.dumps({"title": title, "scenes": scenes})


def run(engine, topic_id, answer, monkeypatch):
    from app.factual import agent_pipeline

    def fake_run(_engine, _registry, agent_id, *args, **kwargs):
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answer,
            "error_detail": None,
        }

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    monkeypatch.setattr(agent_pipeline, "_announce", lambda *a, **k: None)
    return agent_write_script(engine, object(), topic_id, str(uuid4()))


def drafts(engine) -> list[ScriptDraft]:
    with Session(engine) as session:
        return list(session.scalars(select(ScriptDraft)))


# ---------------------------------------------------------------------------
# Nothing to write from
# ---------------------------------------------------------------------------


def test_a_topic_with_no_supported_claim_produces_no_script(engine, topic_with_claims, monkeypatch):
    """Every claim is UNVERIFIED, so there is no verified fact to build a script on."""
    with pytest.raises(NoVerifiedClaims):
        run(
            engine,
            topic_with_claims["topic_id"],
            script_answer([{"narration": "Anything at all.", "claim_ids": ["x"]}]),
            monkeypatch,
        )

    assert drafts(engine) == []


def test_a_refuted_claim_is_not_offered_to_the_writer(engine, topic_with_claims, monkeypatch):
    verify_claim(
        engine, topic_with_claims["claim_ids"][0], "REFUTED", 0.9, "Contrazis.", None, str(uuid4())
    )

    with pytest.raises(NoVerifiedClaims):
        run(engine, topic_with_claims["topic_id"], script_answer([]), monkeypatch)


# ---------------------------------------------------------------------------
# Attribution
# ---------------------------------------------------------------------------


def test_a_scene_citing_a_claim_that_was_never_supplied_rejects_the_draft(
    engine, topic_with_claims, monkeypatch
):
    """The failure this mechanism exists for: fluent narration under an invented citation."""
    support(engine, topic_with_claims["claim_ids"][0], "launched in 1990")

    answer = script_answer(
        [
            {
                "narration": "Hubble was launched in 1990.",
                "claim_ids": [topic_with_claims["claim_ids"][0]],
            },
            {"narration": "It cost 4.7 billion dollars.", "claim_ids": [str(uuid4())]},
        ]
    )

    with pytest.raises(ScriptRejected) as excinfo:
        run(engine, topic_with_claims["topic_id"], answer, monkeypatch)

    assert "scena 2" in str(excinfo.value)
    assert drafts(engine) == [], "a rejected draft is not stored, not even partially"


def test_a_claim_verified_but_belonging_to_another_topic_is_not_citable(
    engine, topic_with_claims, monkeypatch
):
    other_topic = propose_topic_idea(engine, "Voyager", "Voyager", "Angle", "general", str(uuid4()))
    other_source = ingest_source_snapshot(
        engine,
        "https://example.org/voyager",
        "Voyager",
        "example.org",
        None,
        "Voyager 1 left the heliosphere in 2012.",
        0,
        str(uuid4()),
        topic_id=other_topic["id"],
    )
    other_claim = extract_claims(
        engine,
        other_source["id"],
        [ExtractClaimItem(claim_text="Voyager 1 left the heliosphere in 2012.", confidence=0.9)],
        str(uuid4()),
        topic_id=other_topic["id"],
    )[0]
    support(engine, other_claim["id"], "left the heliosphere in 2012")
    support(engine, topic_with_claims["claim_ids"][0], "launched in 1990")

    answer = script_answer(
        [{"narration": "Voyager 1 left the heliosphere in 2012.", "claim_ids": [other_claim["id"]]}]
    )

    with pytest.raises(ScriptRejected):
        run(engine, topic_with_claims["topic_id"], answer, monkeypatch)


def test_a_scene_resting_on_no_claim_is_refused(engine, topic_with_claims, monkeypatch):
    support(engine, topic_with_claims["claim_ids"][0], "launched in 1990")

    answer = script_answer([{"narration": "Space is fascinating, isn't it?", "claim_ids": []}])

    with pytest.raises(ScriptRejected):
        run(engine, topic_with_claims["topic_id"], answer, monkeypatch)


# ---------------------------------------------------------------------------
# A usable draft
# ---------------------------------------------------------------------------


def test_a_properly_attributed_draft_is_stored_and_passes_the_gate(
    engine, topic_with_claims, monkeypatch
):
    first, second = topic_with_claims["claim_ids"]
    support(engine, first, "launched in 1990")
    support(engine, second, "orbits about 540 kilometres above Earth")

    answer = script_answer(
        [
            {
                "narration": "Hubble reached orbit in 1990.",
                "visual": "launch",
                "claim_ids": [first],
            },
            {
                "narration": "It circles roughly 540 kilometres up.",
                "visual": "orbit",
                "claim_ids": [second],
            },
        ]
    )

    result = run(engine, topic_with_claims["topic_id"], answer, monkeypatch)
    script = result["script"]

    assert script["status"] != "BLOCKED_UNVERIFIED_CLAIMS"
    assert script["unverified_claim_ids_json"] == []
    assert sorted(script["claim_ids_json"]) == sorted([first, second])
    # Spoken text and attributed text are the same text.
    assert script["voiceover_full_text"] == (
        "Hubble reached orbit in 1990.\n\nIt circles roughly 540 kilometres up."
    )
    assert [s["scene_number"] for s in script["scenes_json"]] == [1, 2]
    assert all(s["claim_ids"] for s in script["scenes_json"])


def test_the_draft_only_lists_the_claims_it_actually_used(engine, topic_with_claims, monkeypatch):
    """Citing every available claim regardless of use would make attribution meaningless."""
    first, second = topic_with_claims["claim_ids"]
    support(engine, first, "launched in 1990")
    support(engine, second, "orbits about 540 kilometres above Earth")

    answer = script_answer([{"narration": "Hubble reached orbit in 1990.", "claim_ids": [first]}])

    script = run(engine, topic_with_claims["topic_id"], answer, monkeypatch)["script"]

    assert script["claim_ids_json"] == [first]
    assert second not in script["claim_ids_json"]


# ---------------------------------------------------------------------------
# Malformed answers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "Here is a lovely script about Hubble.",
        '{"title": "T", "scenes": []}',
        '{"title": "T", "scenes": [{"narration": "short"}]}',
        '{"scenes": [{"narration": "A long enough narration.", "claim_ids": ["x"]}]}',
        "",
    ],
)
def test_an_answer_that_is_not_a_script_stores_nothing(
    engine, topic_with_claims, monkeypatch, answer
):
    support(engine, topic_with_claims["claim_ids"][0], "launched in 1990")

    with pytest.raises(ScriptRejected):
        run(engine, topic_with_claims["topic_id"], answer, monkeypatch)

    assert drafts(engine) == []


def test_a_draft_with_uncited_scenes_is_rewritten_once_with_those_scenes_named(
    engine, topic_with_claims, monkeypatch
):
    """The fourth clean day: five scenes on dark matter cited their claims, five on the LHC
    upgrade cited nothing, and the whole script was refused. The writer is asked once more,
    told which scenes had no fact behind them; the second draft is the one stored."""
    from app.factual import agent_pipeline

    first = topic_with_claims["claim_ids"][0]
    support(engine, first, "launched in 1990")
    prompts: list[str] = []
    answers = [
        script_answer(
            [
                {"narration": "Hubble reached orbit in 1990.", "claim_ids": [first]},
                {"narration": "The next telescope will change everything.", "claim_ids": []},
            ]
        ),
        script_answer([{"narration": "Hubble reached orbit in 1990.", "claim_ids": [first]}]),
    ]

    def fake_run(_engine, _registry, agent_id, task_type, prompt, version, *args, **kwargs):
        prompts.append(f"{version}::{prompt}")
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answers[len(prompts) - 1],
            "error_detail": None,
        }

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    monkeypatch.setattr(agent_pipeline, "_announce", lambda *a, **k: None)
    result = agent_write_script(engine, object(), topic_with_claims["topic_id"], str(uuid4()))
    script = result["script"]

    assert len(prompts) == 2 and prompts[1].startswith("v1+retry::")
    assert "YOUR FIRST DRAFT WAS REFUSED" in prompts[1]
    assert "The next telescope will change everything." in prompts[1]
    assert len(script["scenes_json"]) == 1 and script["claim_ids_json"] == [first]


def _two_drafts(monkeypatch, answers, prompts):
    from app.factual import agent_pipeline

    def fake_run(_engine, _registry, agent_id, task_type, prompt, version, *args, **kwargs):
        prompts.append(f"{version}::{prompt}")
        return {
            "id": str(uuid4()),
            "status": "SUCCEEDED",
            "output_text": answers[min(len(prompts) - 1, len(answers) - 1)],
            "error_detail": None,
        }

    monkeypatch.setattr(agent_pipeline, "run_agent_task", fake_run)
    monkeypatch.setattr(agent_pipeline, "_announce", lambda *a, **k: None)


def test_a_scene_still_uncited_after_the_rewrite_is_cut_and_the_film_kept(
    engine, topic_with_claims, monkeypatch
):
    """The fifth clean day: after the rewrite one scene of seven — "the LHC is getting
    stronger", which no page read had said — still cited nothing. The scene is cut, the
    six attributed ones are the film."""
    first = topic_with_claims["claim_ids"][0]
    support(engine, first, "launched in 1990")
    prompts: list[str] = []
    same = script_answer(
        [
            {"narration": "Hubble reached orbit in 1990.", "claim_ids": [first]},
            {"narration": "It is getting an upgrade next year.", "claim_ids": []},
            {"narration": "Hubble still orbits today, in 1990's orbit.", "claim_ids": [first]},
        ]
    )
    _two_drafts(monkeypatch, [same, same], prompts)
    result = agent_write_script(engine, object(), topic_with_claims["topic_id"], str(uuid4()))
    assert len(prompts) == 2 and result["cut_scenes"] == ["It is getting an upgrade next year."]
    script = result["script"]
    assert [s["scene_number"] for s in script["scenes_json"]] == [1, 2]
    assert "upgrade" not in script["voiceover_full_text"]


def test_a_rewrite_that_still_rests_mostly_on_nothing_is_refused(
    engine, topic_with_claims, monkeypatch
):
    first = topic_with_claims["claim_ids"][0]
    support(engine, first, "launched in 1990")
    mostly = script_answer(
        [
            {"narration": "Hubble reached orbit in 1990.", "claim_ids": [first]},
            {"narration": "It is getting an upgrade next year.", "claim_ids": []},
            {"narration": "And a new mirror the year after that.", "claim_ids": []},
        ]
    )
    _two_drafts(monkeypatch, [mostly, mostly], [])
    with pytest.raises(ScriptRejected) as excinfo:
        agent_write_script(engine, object(), topic_with_claims["topic_id"], str(uuid4()))
    assert "2 scene din 3" in str(excinfo.value)
    assert drafts(engine) == []
