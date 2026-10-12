"""A structured answer is fitted to its schema before it is refused, and a refused one is asked
again the way its failure asks (2026-10-11).

Film aa170155 (cyclotron) failed the finished-film QC at 14:49 UTC. The Director's decision was
asked five times; every first answer was a complete, sensible REPAIR that the schema refused for
one thing only: a repair reason longer than 400 characters (773, 652, 902...). Every second
attempt, with her own thinking on, spent its 6,000 tokens on reasoning and answered nothing, so
the film waited for her hourly, ~17k tokens an hour, for a character limit. Her scene brief went
the same way at 14:20:57 (a diagnosis of ~1000 characters where 800 were allowed). What holds now,
every provider faked, 0 credits:

- `parse_structured` fits the object to its schema the way `prompt_agent._coerce` fits the shot
  plan: a string longer than its max_length is cut at a word boundary (the opening kept, never
  mid-word), a list longer than its max_length is truncated, nested models and lists of models
  are fitted the same way, a Literal, an Enum or a code-word pattern is matched whatever its case
  and spacing; only then is it validated, and what still fails is refused as before, with its
  reasons (`read_structured`). Her QC decision, her brief, her look and the serial's verdict all
  go through it.
- `structured_run`: a failure of shape alone never reaches a second attempt; an object the schema
  refused for its content is asked again without native thinking, in JSON mode, the refusal
  quoted in plain words at the end of the prompt; no object at all still gets the thinking retry
  (glm-5.3 narrated when thinking was off). Two attempts at most, and a refused run carries the
  refusal, so the caller's waiting note names it instead of «răspuns fără forma cerută».
"""

from __future__ import annotations

import enum
import json
from typing import Any, Literal
from uuid import uuid4

import pytest
from app.agents.identity import cut_at_word, fit_to_schema, parse_structured, read_structured
from app.agents.memory import agent_for_role
from app.agents.models import AgentRun, ModelRecord
from app.agents.reviews import DirectorLook, decision_schema, look_schema
from app.agents.services import seed_initial_workforce
from app.agents.structured import structured_run
from app.media.scene_rewrite import brief_schema
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.story.review import EpisodeVerdict
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

WORDS = "the still shows a face turned to the camera and the clip keeps it in frame "


def words(length: int) -> str:
    """``length`` characters of plain words, as a reason of hers reads."""
    text = (WORDS * (length // len(WORDS) + 2))[:length]
    assert len(text) == length
    return text


# ------------------------------------------------------------------- fitted before refused


def test_a_repair_reason_of_773_characters_validates_after_fitting_cut_at_a_word():
    """One of today's refused shapes replayed: a complete REPAIR, one reason too long."""
    reason = words(773)
    answer = {
        "verdicts": [
            {
                "finding": 1,
                "verdict": "REAL",
                "reason": "a face in profile, which the bible forbids",
                "severity": "serious",
                "cause": "the still prompt asked for a person at the desk",
                "lesson": "Show people only from behind or as hands at work.",
            },
            {"finding": 2, "verdict": "FALSE", "reason": "our own subtitles, read as text"},
        ],
        "decision": "REPAIR",
        "repairs": [{"scene_index": 5, "redo": "still", "reason": reason}],
        "summary": "Refacem imaginea scenei 5; restul rămâne.",
    }
    schema = decision_schema(
        {1, 2}, {4, 5}, {"scenes": [{"scene_index": 5, "kind": "LIVE", "paid_redos_left": 1}]}
    )
    # The shape alone is what refused it today.
    with pytest.raises(ValidationError):
        schema.model_validate(answer)

    decided = parse_structured(json.dumps(answer), schema)

    assert decided is not None, "a sensible REPAIR was refused for a character limit"
    assert decided.decision == "REPAIR" and len(decided.verdicts) == 2
    (repair,) = decided.repairs
    assert len(repair.reason) <= 400
    # Cut at a word: the opening of what she wrote, ending where a word ends.
    assert reason.startswith(repair.reason) and reason[len(repair.reason)] == " "
    assert repair.reason == repair.reason.strip() and repair.scene_index == 5


def test_a_scene_brief_with_a_thousand_character_diagnosis_is_a_brief():
    brief = {
        "diagnosis": words(1000),
        "layer": " Still",
        "avoid": ["a face that can turn to the camera"],
        "keep": [],
        "change": ["hands and the pencil only, in close-up"],
        "summary_ro": "Refac imaginea: mâinile și creionul, fără chip.",
    }
    parsed = parse_structured(json.dumps(brief), brief_schema(("motion", "still")))
    assert parsed is not None
    assert len(parsed.diagnosis) <= 800 and parsed.layer == "still"
    assert brief["diagnosis"].startswith(parsed.diagnosis)

    # A layer this scene cannot take is still refused, and the refusal says so.
    refused, why = read_structured(json.dumps(brief), brief_schema(("motion",)))
    assert refused is None
    assert why is not None and "layer still is not open" in why


def test_her_look_and_the_serial_verdict_are_fitted_too():
    look = {"decision": "choose", "candidate": 2, "reason": words(700)}
    chosen = parse_structured(json.dumps(look), look_schema(3))
    assert isinstance(chosen, DirectorLook)
    assert chosen.decision == "CHOOSE" and chosen.candidate == 2 and len(chosen.reason) <= 600

    verdict = {"verdict": "pass", "reasons": [f"reason {n}" for n in range(12)], "story": "x"}
    judged = parse_structured(json.dumps(verdict), EpisodeVerdict)
    assert isinstance(judged, EpisodeVerdict)
    assert judged.verdict == "PASS" and len(judged.reasons) == 8


def test_nested_models_lists_and_code_words_are_fitted_and_the_answer_is_not_changed():
    class Colour(enum.Enum):
        RED = "red"
        BLUE = "blue"

    class Item(BaseModel):
        model_config = ConfigDict(extra="ignore")
        kind: Literal["still", "motion"]
        note: str = Field(max_length=12)

    class Plan(BaseModel):
        model_config = ConfigDict(extra="ignore")
        items: list[Item] = Field(max_length=2)
        colour: Colour
        verdict: Literal["OWNER_CHOICE", "REAL"]
        tags: list[str] | None = Field(default=None, max_length=1)
        count: int | None = None

    item = {"kind": " Motion", "note": "one two three four"}
    answer: dict[str, Any] = {
        "items": [dict(item), dict(item), dict(item)],
        "colour": "Red",
        "verdict": "owner choice",
        "tags": ["a", "b"],
        "count": 3,
    }

    fitted = fit_to_schema(answer, Plan)

    assert fitted["items"] == [{"kind": "motion", "note": "one two"}] * 2
    assert fitted["colour"] == "red" and fitted["verdict"] == "OWNER_CHOICE"
    assert fitted["tags"] == ["a"] and fitted["count"] == 3
    plan = parse_structured(json.dumps(answer), Plan)
    assert isinstance(plan, Plan) and plan.colour is Colour.RED and len(plan.items) == 2
    # What the model said is left as it was: the fit is a copy.
    assert answer["items"][0]["note"] == "one two three four" and answer["tags"] == ["a", "b"]


def test_what_still_fails_is_refused_with_its_reasons_and_no_object_says_nothing():
    schema = decision_schema({1, 2}, set())
    text = (
        'Checking {"finding": 1} first.\n'
        '{"verdicts": [{"finding": 1, "verdict": "REAL", "reason": "a face"}], '
        '"decision": "ACCEPT", "repairs": [], "summary": "Gata."}'
    )

    refused, why = read_structured(text, schema)

    assert refused is None and why is not None
    # The candidate closest to the schema is the one quoted, not the stray dict before it
    # (whose refusal would be three fields missing): REAL and ACCEPT at once is the first rule
    # the decision breaks (`DirectorQcDecision._consistent`, before the report's own).
    assert why == "the answer: a film with a REAL finding is not accepted as it is"
    assert read_structured("Let me think: {a}, {b}, and then", schema) == (None, None)
    assert parse_structured("", schema) is None
    assert parse_structured(text, schema) is None


def test_cut_at_word_keeps_the_opening_and_never_cuts_a_word_in_two():
    assert cut_at_word("one two three", 8) == "one two"
    assert cut_at_word("one two three", 7) == "one two"
    assert cut_at_word("one, two three", 9) == "one, two"
    assert cut_at_word("one two, three", 8) == "one two"
    assert cut_at_word("short", 10) == "short"
    # One word longer than the limit: nothing shorter of it can be kept, so it is cut.
    assert cut_at_word("x" * 50, 10) == "x" * 10


# ----------------------------------------------------------------- asked again as needed


class Scripted:
    """The Director's model, scripted: one answer per call (the last one repeats)."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append({"prompt": prompt, "extra": kwargs.get("extra")})
        text = self.answers[min(len(self.calls), len(self.answers)) - 1]
        return GenerateResult(text, 10, 40, None)


class Judgement(BaseModel):
    model_config = ConfigDict(extra="ignore")
    findings: list[int] = Field(min_length=1)
    verdict: Literal["REAL", "FALSE"]
    reason: str = Field(min_length=1, max_length=40)


def judgement_of(findings: set[int]) -> type[Judgement]:
    """The answer bound to the findings put before her: every one judged, none invented."""

    class Bound(Judgement):
        @model_validator(mode="after")
        def _every_finding(self) -> Bound:
            if set(self.findings) != findings:
                raise ValueError(f"findings not judged {sorted(findings - set(self.findings))}")
            return self

    return Bound


PARTIAL = json.dumps({"findings": [1], "verdict": "REAL", "reason": "a face in profile"})
WHOLE = json.dumps({"findings": [1, 2], "verdict": "REAL", "reason": "a face in profile"})
NARRATED = "Let me think about the findings. {not the object} Finding 1 is real, finding 2 too."


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        assert director is not None
        return {"director_id": director.id, "provider_id": director.provider_id}


def ask(engine, studio, adapter: Scripted):
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], adapter)
    return structured_run(
        engine,
        registry,
        studio["director_id"],
        "director_scene_brief",
        "Judge the findings 1 and 2.",
        "judge-v1",
        str(uuid4()),
        judgement_of({1, 2}),
        "",
        summary="Judec constatările.",
        max_tokens=500,
    )


def runs(engine) -> list[AgentRun]:
    with Session(engine) as session:
        rows = session.scalars(select(AgentRun).order_by(AgentRun.started_at)).all()
        session.expunge_all()
        return list(rows)


def test_a_failure_of_shape_alone_is_fitted_and_never_reaches_a_second_attempt(engine, studio):
    adapter = Scripted(json.dumps({"findings": [1, 2], "verdict": "real", "reason": words(120)}))

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is not None and parsed.verdict == "REAL" and len(parsed.reason) <= 40
    assert second is None and len(adapter.calls) == 1
    assert adapter.calls[0]["extra"] == {"format": "json"}
    assert "refusal" not in first and first["error_detail"] is None


def test_an_object_refused_for_its_content_is_asked_again_without_thinking_with_the_refusal(
    engine, studio
):
    adapter = Scripted(PARTIAL, WHOLE)

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is not None and parsed.findings == [1, 2]
    assert [call["extra"] for call in adapter.calls] == [{"format": "json"}, {"format": "json"}]
    again = adapter.calls[1]["prompt"]
    assert again.startswith(adapter.calls[0]["prompt"])
    assert "Your previous answer was refused: " in again
    assert "findings not judged [2]" in again
    assert again.rstrip().endswith("Answer again, same content, within these rules.")
    # The refused run says why, for the caller's note; the second, which validated, does not.
    assert "findings not judged [2]" in first["refusal"]
    assert first["error_detail"].endswith(first["refusal"])
    assert second is not None and "refusal" not in second and second["error_detail"] is None
    recorded = runs(engine)
    assert [run.prompt_template_version for run in recorded] == ["judge-v1", "judge-v1+again"]
    assert "a doua încercare, cu motivele refuzului" in recorded[1].context_json["task_summary"]


def test_a_second_refusal_ends_it_and_names_the_errors_for_the_callers_note(engine, studio):
    adapter = Scripted(PARTIAL)

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is None and len(adapter.calls) == 2
    assert second is not None and second["status"] == "SUCCEEDED"
    assert "findings not judged [2]" in second["error_detail"]
    assert second["refusal"] == first["refusal"]


def test_no_object_at_all_still_gets_the_thinking_retry(engine, studio):
    adapter = Scripted(NARRATED, WHOLE)

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is not None
    assert [call["extra"] for call in adapter.calls] == [{"format": "json"}, {"think": True}]
    assert adapter.calls[0]["prompt"] == adapter.calls[1]["prompt"]
    assert "refusal" not in first and first["error_detail"] is None
    assert [run.prompt_template_version for run in runs(engine)] == ["judge-v1", "judge-v1+think"]


def test_no_object_then_a_refused_object_carries_the_refusal_on_the_second_run(engine, studio):
    adapter = Scripted(NARRATED, PARTIAL)

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is None and len(adapter.calls) == 2
    assert "refusal" not in first
    assert second is not None and "findings not judged [2]" in second["refusal"]
    assert "findings not judged [2]" in second["error_detail"]


def test_a_refused_object_then_narration_still_names_the_refusal(engine, studio):
    """Review of 2026-10-11: callers read the last run; when the retry narrated instead of
    answering, the waiting note lost the first answer's refusal."""
    adapter = Scripted(PARTIAL, NARRATED)

    parsed, first, second = ask(engine, studio, adapter)

    assert parsed is None and len(adapter.calls) == 2
    assert "findings not judged [2]" in first["refusal"]
    assert second is not None and second["refusal"] == first["refusal"]
    assert "findings not judged [2]" in second["error_detail"]
