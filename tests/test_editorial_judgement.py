"""The Director's editorial judgement (2026-10-11, the Owner's card of 23:30).

«The Zero Script Club» passed every check the studio had and was a status meeting; the
ATLAS/Higgs Short passed them and was jargon. These tests hold the loop the Owner asked for,
on stand-ins only (no vendor, no credit; the network is refused by conftest):

- the loop itself, with a scripted judge and writer: a version below the bar gets a brief that
  names the two weakest criteria with her KEEP / CHANGE / AVOID, and the first rewrite that
  passes ships; ten versions that never pass ship the best-scored one; a rewrite that failed
  its structural checks is scored and never ships; the setting bounds the rounds; a Director
  who cannot answer, or a writer who gives nothing, ends the loop with what is in hand;
- the bar (35/50, no criterion under 5) and the fitting of her answer (bare numbers, a brief
  written as a paragraph);
- `judge` through the studio's own run path: the five criteria in her prompt, her scores read,
  no object twice is no judgement;
- the serial stage: the first draft scored below the bar is rewritten on her brief, the
  rewrite ships approved and storyboarded, the first is retired, every version an event, no
  letter; three versions none passing ship the best (not the newest) and write the Owner one
  STATUS letter; a rewrite the review FAILs is scored high and never ships;
- the factual room: the same, through `_script_and_storyboard`; a later version the review
  sent back is marked superseded and owes the room nothing the next day;
- the weekly review reads the shipped version's total for both kinds.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from uuid import uuid4

import pytest
from app.agents.editorial_judgement import (
    CRITERIA,
    CRITERION_KEYS,
    FACTUAL_SHORT,
    JUDGED_EVENT,
    JUDGEMENT_TASK,
    PASS_TOTAL,
    SERIAL_EPISODE,
    STOP_JUDGE_SILENT,
    STOP_PASSED,
    STOP_ROUNDS_SPENT,
    STOP_WRITER_SILENT,
    TEMPLATE_VERSION,
    EditorialAnswer,
    Judgement,
    Version,
    editorial_loop,
    judge,
    passes,
)
from app.agents.models import Agent, AgentMessage, AgentRun, ModelRecord
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, StoryReview
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.services import seed_default_channels
from app.story.models import StoryEpisode
from app.story.review import review_episode
from app.story.serial_stage import run_serial_next_stage, run_serial_stage
from app.story.services import get_continuity, write_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    RUBRIC,
    YESTERDAY_NOON,
    a_day,
    allow_director_approval,
    beats_for,
    episode_answer,
    roster_names,
)

#: Her scores for the status meeting: 25/50, the hook and the punchline weakest.
WEAK = {"hook": 3, "clarity": 7, "moment": 5, "punchline": 4, "follow": 6}
#: Her scores for a version a stranger would watch: 40/50.
GOOD = {"hook": 8, "clarity": 8, "moment": 8, "punchline": 8, "follow": 8}
BRIEF = {
    "keep": "Aris's line about the evidence first.",
    "change": "Open on what Sarah stands to lose if the number is wrong; end on her answer.",
    "avoid": "A greeting or a status line as the first words.",
}


def her_answer(scores: dict[str, int], brief: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        **{
            key: {"score": value, "reason": f"the {key} as written"}
            for key, value in scores.items()
        },
        "weakest": sorted(scores, key=scores.get)[:2],  # type: ignore[arg-type]
        "brief": brief or BRIEF,
    }


def judged(scores: dict[str, int]) -> Judgement:
    return Judgement(EditorialAnswer.model_validate(her_answer(scores)), run_id=str(uuid4()))


def with_total(total: int) -> dict[str, int]:
    """Five scores adding up to ``total``, none passing the bar unless ``total`` allows it."""
    base, extra = divmod(total, 5)
    return {key: base + (1 if index < extra else 0) for index, key in enumerate(CRITERION_KEYS)}


# ---------------------------------------------------------------------------
# The loop, with a scripted judge and writer
# ---------------------------------------------------------------------------


def scripted_loop(
    scores_by_version: dict[str, dict[str, int] | None],
    versions: dict[str, Version],
    *,
    rounds: int = 10,
) -> tuple[Any, list[str]]:
    """Run the loop over ``versions`` ("v1", "v2", ...) scored by ``scores_by_version``."""
    briefs: list[str] = []

    def judge_fn(version: Version, _number: int) -> Judgement | None:
        scores = scores_by_version.get(version.id)
        return judged(scores) if scores is not None else None

    def rewrite(brief: str, number: int) -> Version | None:
        briefs.append(brief)
        return versions.get(f"v{number}")

    outcome = editorial_loop(
        None,
        None,
        kind=SERIAL_EPISODE,
        first=versions["v1"],
        rewrite=rewrite,
        correlation_id="c",
        rounds=rounds,
        judge_fn=judge_fn,
    )
    return outcome, briefs


def test_below_the_bar_the_brief_names_the_two_weakest_and_the_passing_rewrite_ships():
    versions = {
        "v1": Version("v1", "The Zero Script Club", title="The Zero Script Club"),
        "v2": Version("v2", "The number before good morning"),
    }
    outcome, briefs = scripted_loop({"v1": WEAK, "v2": GOOD}, versions)

    assert outcome.shipped.version.id == "v2"
    assert outcome.passed and outcome.stopped == STOP_PASSED
    assert [item.number for item in outcome.rounds] == [1, 2]
    assert outcome.rewrites == 1
    (brief,) = briefs
    # The two weakest by her scores, with her reasons, and her KEEP / CHANGE / AVOID.
    assert "version 1 of at most 10" in brief and "25/50" in brief
    assert "hook (3/10): the hook as written" in brief
    assert "punchline (4/10): the punchline as written" in brief
    assert "clarity (7/10)" not in brief
    assert f"KEEP: {BRIEF['keep']}" in brief
    assert f"CHANGE: {BRIEF['change']}" in brief
    assert f"AVOID: {BRIEF['avoid']}" in brief
    assert outcome.rounds[0].brief == brief and outcome.rounds[1].brief is None
    record = outcome.record()
    assert record["shipped"] == {
        "round": 2,
        "version_id": "v2",
        "judged": True,
        "total": 40,
        "scores": GOOD,
        "weakest": ["hook", "clarity"],
        "reasons": {key: f"the {key} as written" for key in CRITERION_KEYS},
        "passed": True,
    }
    assert record["rounds"][0]["weakest"] == ["hook", "punchline"]
    assert outcome.record_for("v1")["superseded_by"] == "v2"
    assert outcome.record_for("v2")["superseded_by"] is None


def test_ten_versions_that_never_pass_ship_the_best_scored_one():
    totals = {1: 25, 2: 28, 3: 31, 4: 33, 5: 30, 6: 33, 7: 29, 8: 32, 9: 27, 10: 30}
    versions = {f"v{n}": Version(f"v{n}", f"version {n}") for n in totals}
    scores = {f"v{n}": with_total(total) for n, total in totals.items()}
    outcome, briefs = scripted_loop(scores, versions, rounds=10)

    assert len(outcome.rounds) == 10 and len(briefs) == 9
    assert outcome.stopped == STOP_ROUNDS_SPENT
    # 33 twice: the earlier of the tie ships (fewer rewrites between it and the record).
    assert outcome.shipped.version.id == "v4"
    assert outcome.shipped.judgement.total == 33
    assert not outcome.passed and outcome.judged
    assert "version 9 of at most 10" in briefs[-1]


def test_a_rewrite_that_fails_its_checks_is_scored_but_never_ships():
    versions = {
        "v1": Version("v1", "the first"),
        "v2": Version("v2", "two beats only", eligible=False, note="2 beat-uri și 16 secunde"),
        "v3": Version("v3", "the third"),
    }
    brilliant = {"hook": 9, "clarity": 9, "moment": 9, "punchline": 9, "follow": 9}
    outcome, briefs = scripted_loop(
        {"v1": WEAK, "v2": brilliant, "v3": with_total(36)}, versions, rounds=3
    )

    assert outcome.shipped.version.id == "v3"
    assert outcome.passed
    assert outcome.rounds[1].judgement.total == 45
    assert outcome.record()["rounds"][1] == {
        "round": 2,
        "version_id": "v2",
        "title": "",
        "eligible": False,
        "judged": True,
        "total": 45,
        "scores": brilliant,
        "weakest": ["hook", "clarity"],
        "passed": True,
        "brief": briefs[1],
        "run_id": outcome.rounds[1].judgement.run_id,
    }
    # The brief after the refused version carries the checks' reasons first.
    assert "The studio's own checks also refused this version" in briefs[1]
    assert "2 beat-uri și 16 secunde" in briefs[1]
    assert "checks also refused" not in briefs[0]


def test_the_setting_bounds_the_rounds():
    versions = {f"v{n}": Version(f"v{n}", f"v{n}") for n in range(1, 11)}
    scores = {f"v{n}": WEAK for n in range(1, 11)}

    three, briefs = scripted_loop(scores, versions, rounds=3)
    assert len(three.rounds) == 3 and len(briefs) == 2
    assert three.stopped == STOP_ROUNDS_SPENT and three.rounds_allowed == 3
    assert "version 1 of at most 3" in briefs[0]

    one, none = scripted_loop(scores, versions, rounds=1)
    assert len(one.rounds) == 1 and none == []
    assert one.shipped.version.id == "v1"


def test_a_director_who_cannot_answer_ships_the_version_in_hand_unjudged():
    versions = {"v1": Version("v1", "the first"), "v2": Version("v2", "the second")}
    outcome, briefs = scripted_loop({"v1": None}, versions)

    assert outcome.shipped.version.id == "v1"
    assert not outcome.judged and not outcome.passed
    assert outcome.stopped == STOP_JUDGE_SILENT and briefs == []
    assert outcome.record()["shipped"]["total"] is None


def test_a_director_silent_on_a_rewrite_ships_the_best_she_scored():
    versions = {"v1": Version("v1", "the first"), "v2": Version("v2", "the second")}
    outcome, briefs = scripted_loop({"v1": WEAK, "v2": None}, versions)

    assert outcome.shipped.version.id == "v1"
    assert outcome.shipped.judgement.total == 25
    assert outcome.stopped == STOP_JUDGE_SILENT and len(briefs) == 1


def test_a_writer_who_gives_nothing_ends_the_loop_with_the_best_so_far():
    outcome, briefs = scripted_loop({"v1": WEAK}, {"v1": Version("v1", "the first")})

    assert outcome.shipped.version.id == "v1"
    assert outcome.stopped == STOP_WRITER_SILENT and len(briefs) == 1


def test_the_bar_is_thirty_five_with_no_criterion_under_five():
    assert passes(dict.fromkeys(CRITERION_KEYS, 7))
    assert passes({"hook": 5, "clarity": 5, "moment": 10, "punchline": 10, "follow": 5})
    # Brilliant on three and no ending: 36 in all, and not shipped on the total alone.
    assert not passes({"hook": 10, "clarity": 10, "moment": 10, "punchline": 3, "follow": 3})
    assert not passes({"hook": 7, "clarity": 7, "moment": 7, "punchline": 7, "follow": 6})
    assert PASS_TOTAL == 35


def test_her_answer_is_fitted_bare_numbers_and_a_paragraph_brief():
    answer = EditorialAnswer.model_validate(
        {
            "hook": 7,
            "clarity": "8",
            "moment": {"score": 6.0, "reason": "One line about the espresso cup."},
            "punchline": 5.5,
            "follow": 9,
            "weakest": "The punchline at the end, then the moment",
            "brief": "Open on the number Sarah is waiting for.",
        }
    )
    assert answer.scores() == {"hook": 7, "clarity": 8, "moment": 6, "punchline": 5, "follow": 9}
    assert answer.total() == 35
    assert answer.weakest == ["punchline", "moment"]
    assert answer.weakest_two() == ["punchline", "moment"]
    assert answer.brief.change == "Open on the number Sarah is waiting for."
    assert answer.brief.keep == ""
    assert answer.passes()


def test_a_score_outside_the_scale_is_refused():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EditorialAnswer.model_validate(her_answer({**GOOD, "hook": 11}))


# ---------------------------------------------------------------------------
# `judge` through the studio's own run path
# ---------------------------------------------------------------------------


class StandIn:
    """One language model for every employee, answering by the shape each prompt asks for.

    ``on_judgement(prompt)`` answers the Director's editorial judgement; ``on_episode(prompt)``
    the showrunner's brief; ``on_script(prompt)`` the Scriptwriter's; the episode review and
    the story review are passed unless ``story_review(prompt)`` says otherwise. Anything else
    is prose, which every caller treats as an answer it could not read.
    """

    def __init__(
        self,
        on_judgement: Callable[[str], Any],
        *,
        on_episode: Callable[[str], str] | None = None,
        on_script: Callable[[str], str] | None = None,
        story_review: Callable[[str], str] | None = None,
    ) -> None:
        self.on_judgement = on_judgement
        self.on_episode = on_episode
        self.on_script = on_script
        self.story_review = story_review
        self.prompts: list[str] = []

    async def health_check(self) -> HealthResult:
        return HealthResult("HEALTHY")

    async def list_models(self) -> list[dict[str, Any]]:
        return []

    async def generate(self, model: str, prompt: str, **kwargs: Any) -> GenerateResult:
        self.prompts.append(prompt)
        return GenerateResult(self._answer(prompt), 10, 40, None)

    def _answer(self, prompt: str) -> str:
        if '"punchline": {' in prompt:
            answer = self.on_judgement(prompt)
            return answer if isinstance(answer, str) else json.dumps(answer)
        if "ALLOWED_NAMES:" in prompt and self.on_episode is not None:
            return self.on_episode(prompt)
        if '"verdict": "PASS" | "FAIL"' in prompt:
            return json.dumps(
                {
                    "verdict": "PASS",
                    "scores": RUBRIC,
                    "reasons": ["One situation, a turn, a payoff."],
                    "notes": "",
                    "story": "A morning in the office.",
                }
            )
        if "hook_strength" in prompt:
            verdict = self.story_review(prompt) if self.story_review is not None else "PASS"
            return json.dumps(
                {
                    "verdict": verdict,
                    "hook_strength": 80,
                    "clarity": 80,
                    "payoff": 80,
                    "cta_fit": 80,
                    "retention": {"at_0": 100, "at_3": 85, "at_end": 60, "collapse_at": "none"},
                    "notes": ["Tighten the second scene."] if verdict != "PASS" else [],
                }
            )
        if "AFIRMAȚII VERIFICATE" in prompt and self.on_script is not None:
            return self.on_script(prompt)
        return "Nimic de raportat."

    def judgement_prompts(self) -> list[str]:
        return [prompt for prompt in self.prompts if '"punchline": {' in prompt]

    def episode_prompts(self) -> list[str]:
        return [prompt for prompt in self.prompts if "ALLOWED_NAMES:" in prompt]

    def script_prompts(self) -> list[str]:
        return [prompt for prompt in self.prompts if "AFIRMAȚII VERIFICATE" in prompt]


@pytest.fixture
def studio(engine):
    """The seeded workforce, bibles and channels, autonomy on, every model available, the
    Director allowed to approve episodes (his publish-policy command's state)."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    allow_director_approval(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent)).provider_id
    return {"provider_id": provider_id}


def registry_with(studio, model: StandIn) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], model)
    return registry


def test_the_director_is_asked_the_five_criteria_and_her_scores_are_read(engine, studio):
    model = StandIn(lambda prompt: her_answer(WEAK))
    registry = registry_with(studio, model)

    verdict = judge(
        engine,
        registry,
        "The Zero Script Club\n\n[1. HOOK — script_room] Sarah: Right, where are we?",
        SERIAL_EPISODE,
        {"title": "The Zero Script Club", "speakers": ["Sarah", "Aris"]},
    )

    assert verdict is not None
    assert verdict.total == 25 and verdict.weakest == ["hook", "punchline"]
    assert not verdict.passed
    (prompt,) = model.judgement_prompts()
    for key, title, zero, ten in CRITERIA:
        assert f"- {key} — {title}. 0: {zero}. 10: {ten}." in prompt
    assert f"{PASS_TOTAL}/50" in prompt
    assert "Sarah: Right, where are we?" in prompt
    assert "an episode of the studio's own workplace serial" in prompt
    with Session(engine) as session:
        runs = session.scalars(select(AgentRun).where(AgentRun.task_type == JUDGEMENT_TASK)).all()
    assert len(runs) == 1
    assert runs[0].prompt_template_version == TEMPLATE_VERSION
    assert runs[0].id == verdict.run_id


def test_a_factual_short_is_judged_as_one(engine, studio):
    model = StandIn(lambda prompt: her_answer(GOOD))
    verdict = judge(engine, registry_with(studio, model), "text", FACTUAL_SHORT, {"title": "T"})

    assert verdict is not None and verdict.passed
    (prompt,) = model.judgement_prompts()
    assert "This is a factual Short for a general audience" in prompt


def test_no_object_twice_is_no_judgement(engine, studio):
    model = StandIn(lambda prompt: "I would rather describe it in prose.")

    verdict = judge(engine, registry_with(studio, model), "text", SERIAL_EPISODE, {"title": "T"})

    assert verdict is None
    assert len(model.judgement_prompts()) == 2  # asked once more with her thinking on


def test_without_a_language_model_there_is_no_judgement(engine, studio):
    assert judge(engine, ProviderRegistry(), "text", SERIAL_EPISODE, {}) is None
    assert judge(engine, None, "text", SERIAL_EPISODE, {}) is None


# ---------------------------------------------------------------------------
# The serial stage
# ---------------------------------------------------------------------------

STATUS_MEETING = "The Zero Script Club"
WATCHABLE = "The number before good morning"


def _events(engine, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == event_type)
            .order_by(DomainEvent.timestamp)
        ).all()


def _owner_letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            letter
            for letter in session.scalars(select(AgentMessage))
            # Addressed to him, or redirected to the Director by his letters rule
            # (2026-10-12, `messages.directors_matter`): the letter is written either way.
            if (
                (letter.body_json or {}).get("owner_attention")
                or (letter.body_json or {}).get("redirected_from") == "Owner"
            )
            and "Judecata editorială" in letter.subject
        ]


def _episodes(engine) -> dict[str, StoryEpisode]:
    with Session(engine) as session:
        rows = session.scalars(select(StoryEpisode)).all()
        session.expunge_all()
    return {row.title: row for row in rows}


def test_the_serial_episode_below_the_bar_is_rewritten_on_her_brief_and_the_rewrite_ships(
    engine, studio, settings
):
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])

    def showrunner(prompt: str) -> str:
        title = WATCHABLE if "EDITORIAL JUDGEMENT" in prompt else STATUS_MEETING
        return episode_answer(beats_for(ids, names), title=title)

    def director(prompt: str) -> dict[str, Any]:
        return her_answer(WEAK if STATUS_MEETING in prompt else GOOD)

    model = StandIn(director, on_episode=showrunner)
    outcome = run_serial_stage(engine, registry_with(studio, model), settings)

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["approved"] == 1 and artefacts["storyboard_id"]
    editorial = artefacts["editorial"]
    assert editorial["passed"] and editorial["stopped"] == STOP_PASSED
    assert [item["total"] for item in editorial["rounds"]] == [25, 40]
    assert editorial["shipped"]["round"] == 2

    episodes = _episodes(engine)
    first, shipped = episodes[STATUS_MEETING], episodes[WATCHABLE]
    assert shipped.status == "APPROVED" and shipped.reviewed_by == "director"
    assert shipped.storyboard_id == artefacts["storyboard_id"]
    assert shipped.rewrite_of_id == first.id
    assert shipped.review_json["editorial"]["shipped"]["version_id"] == shipped.id
    assert shipped.review_json["editorial"]["shipped"]["total"] == 40
    assert shipped.review_json["approved_by_policy"] is True
    assert shipped.review_json["held_for_judgement"] is False
    # The status meeting: passed her reading, scored 25, retired so nothing waits beside it.
    assert first.status == "REJECTED" and first.reviewed_by == "director"
    assert "Judecata editorială a ales versiunea 2" in first.notes
    assert first.review_json["verdict"] == "PASS"
    assert first.review_json["editorial"]["superseded_by"] == shipped.id
    assert first.review_json["editorial"]["total"] == 25
    assert get_continuity(engine)["canon_episode_number"] == 1

    judged_events = _events(engine, JUDGED_EVENT)
    assert [(e.aggregate_id, e.payload["round"], e.payload["shipped"]) for e in judged_events] == [
        (first.id, 1, False),
        (shipped.id, 2, True),
    ]
    assert judged_events[0].payload["weakest"] == ["hook", "punchline"]
    assert judged_events[0].payload["kind"] == SERIAL_EPISODE
    assert judged_events[0].payload["brief"].startswith("EDITORIAL JUDGEMENT, version 1")
    assert judged_events[1].payload["scores"] == GOOD
    # The rewrite was briefed with the two weakest and told the draft was scored, not refused.
    rewrite_prompt = model.episode_prompts()[-1]
    assert "hook (3/10)" in rewrite_prompt and "punchline (4/10)" in rewrite_prompt
    assert f"KEEP: {BRIEF['keep']}" in rewrite_prompt
    assert "scored it below the studio's bar" in rewrite_prompt
    assert "refused it" not in rewrite_prompt
    assert _owner_letters(engine) == []


def test_three_versions_none_passing_ship_the_best_and_write_the_owner_one_letter(
    engine, studio, settings
):
    settings.editorial_rounds = 3
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    titles = {1: "Version one", 2: "Version two", 3: "Version three"}
    totals = {"Version one": 25, "Version two": 30, "Version three": 27}

    def showrunner(prompt: str) -> str:
        number = next(
            (n for n in (2, 1) if f"version {n} of at most 3" in prompt),
            0,
        )
        return episode_answer(beats_for(ids, names), title=titles[number + 1])

    def director(prompt: str) -> dict[str, Any]:
        title = next(t for t in totals if t in prompt)
        return her_answer(with_total(totals[title]))

    model = StandIn(director, on_episode=showrunner)
    outcome = run_serial_stage(engine, registry_with(studio, model), settings)

    assert outcome["status"] == "COMPLETED", outcome
    editorial = outcome["artefacts"]["editorial"]
    assert [item["total"] for item in editorial["rounds"]] == [25, 30, 27]
    assert editorial["stopped"] == STOP_ROUNDS_SPENT and not editorial["passed"]
    assert editorial["shipped"]["round"] == 2

    episodes = _episodes(engine)
    assert {title: row.status for title, row in episodes.items()} == {
        "Version one": "REJECTED",
        "Version two": "APPROVED",
        "Version three": "REJECTED",
    }
    assert episodes["Version two"].storyboard_id == outcome["artefacts"]["storyboard_id"]
    assert "30/50" in episodes["Version three"].notes
    assert len(model.judgement_prompts()) == 3

    (letter,) = _owner_letters(engine)
    assert letter.intent == "STATUS"
    assert "Version two" in letter.subject and "30/50" in letter.subject
    assert "3 versiuni" in letter.subject
    assert letter.body_json["total"] == 30 and letter.body_json["rounds"] == 3
    assert letter.body_json["stopped"] == STOP_ROUNDS_SPENT
    assert "cârligul" in letter.body_text and "publicăm" in letter.body_text


def test_a_rewrite_the_review_fails_is_scored_and_never_ships(engine, studio, settings):
    settings.editorial_rounds = 3
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])

    def showrunner(prompt: str) -> str:
        if "version 2 of at most 3" in prompt:
            return episode_answer(beats_for(ids, names), title="The third, watchable")
        if "version 1 of at most 3" in prompt:
            # Two beats: 40 spoken words, 16 seconds, under the serial's 45 — the review
            # FAILs it however it scores.
            return episode_answer(beats_for(ids, names, count=2), title="Two beats, brilliant")
        return episode_answer(beats_for(ids, names), title=STATUS_MEETING)

    brilliant = dict.fromkeys(CRITERION_KEYS, 9)

    def director(prompt: str) -> dict[str, Any]:
        if "Two beats, brilliant" in prompt:
            return her_answer(brilliant)
        if "The third, watchable" in prompt:
            return her_answer(with_total(38))
        return her_answer(WEAK)

    model = StandIn(director, on_episode=showrunner)
    outcome = run_serial_stage(engine, registry_with(studio, model), settings)

    assert outcome["status"] == "COMPLETED", outcome
    editorial = outcome["artefacts"]["editorial"]
    assert [(item["total"], item["eligible"]) for item in editorial["rounds"]] == [
        (25, True),
        (45, False),
        (38, True),
    ]
    assert editorial["shipped"]["round"] == 3 and editorial["passed"]

    episodes = _episodes(engine)
    short = episodes["Two beats, brilliant"]
    assert short.status == "REJECTED"
    assert short.review_json["verdict"] == "FAIL"
    # The review's own reason, not the judgement's: two beats miss the structure (the
    # length floor is a recommendation since 2026-10-16).
    assert "lipsesc părțile" in short.notes
    assert short.review_json["editorial"]["superseded_by"] == episodes["The third, watchable"].id
    assert episodes["The third, watchable"].status == "APPROVED"
    assert episodes[STATUS_MEETING].status == "REJECTED"
    # The brief after the refused version named the review's reasons first.
    third_brief = next(p for p in model.episode_prompts() if "version 2 of at most 3" in p)
    assert "The studio's own checks also refused this version" in third_brief
    assert _owner_letters(engine) == []


def test_a_pass_the_policy_does_not_let_her_approve_waits_for_the_owner_after_the_judgement(
    engine, studio, settings
):
    allow_director_approval(engine, False)
    log, ids = a_day(engine, YESTERDAY_NOON())
    names = roster_names(engine, log["id"])
    model = StandIn(
        lambda prompt: her_answer(GOOD),
        on_episode=lambda prompt: episode_answer(beats_for(ids, names), title=WATCHABLE),
    )

    outcome = run_serial_stage(engine, registry_with(studio, model), settings)

    assert outcome["artefacts"]["approved"] == 0 and "aprobarea" in outcome["reason"]
    (episode,) = _episodes(engine).values()
    assert episode.status == "DRAFT" and episode.review_json["verdict"] == "PASS"
    assert episode.review_json["editorial"]["passed"]
    assert episode.review_json["held_for_judgement"] is False
    assert get_continuity(engine)["canon_episode_number"] == 0


def _held_pass(engine, registry, log: dict, ids: list[str]) -> str:
    """A draft the Director passed and the judgement held, as a run that stopped between the
    reading and the approval leaves it: a DRAFT, review PASS, ``held_for_judgement``."""
    names = roster_names(engine, log["id"])
    registry.get(next(iter(registry.registered_ids()))).on_episode = lambda prompt: episode_answer(
        beats_for(ids, names), title=WATCHABLE
    )
    episode_id = write_episode(engine, registry, log["id"], str(uuid4()))["episode"]["id"]
    review = review_episode(engine, registry, episode_id, str(uuid4()), approve=False)
    assert review["verdict"] == "PASS" and review["status"] == "DRAFT"
    return episode_id


def test_a_pass_held_by_a_stopped_run_is_approved_and_readied_by_the_next_morning(
    engine, studio, settings
):
    log, ids = a_day(engine, YESTERDAY_NOON())
    registry = registry_with(studio, StandIn(lambda prompt: her_answer(GOOD)))
    episode_id = _held_pass(engine, registry, log, ids)

    outcome = run_serial_stage(engine, registry, settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert "rulare oprită" in outcome["reason"] and "pregătit de filmare" in outcome["reason"]
    artefacts = outcome["artefacts"]
    assert artefacts["approved"] == 1 and artefacts["written"] == 0
    assert artefacts["episode_id"] == episode_id and artefacts["storyboard_id"]
    (episode,) = _episodes(engine).values()
    assert episode.status == "APPROVED" and episode.reviewed_by == "director"
    assert episode.review_json["held_for_judgement"] is False
    assert episode.review_json["approved_by_policy"] is True
    assert get_continuity(engine)["canon_episode_number"] == 1


def test_a_pass_held_by_a_stopped_run_is_approved_and_readied_by_the_evening_rerun(
    engine, studio, settings
):
    log, ids = a_day(engine)  # today, closed as the daily_log stage closes it
    registry = registry_with(studio, StandIn(lambda prompt: her_answer(GOOD)))
    episode_id = _held_pass(engine, registry, log, ids)

    outcome = run_serial_next_stage(engine, registry, settings)

    assert outcome["status"] == "COMPLETED", outcome
    assert "pregătit de filmare" in outcome["reason"]
    assert outcome["artefacts"]["approved"] == 1 and outcome["artefacts"]["storyboard_id"]
    (episode,) = _episodes(engine).values()
    assert episode.id == episode_id and episode.status == "APPROVED"
    assert episode.storyboard_id == outcome["artefacts"]["storyboard_id"]


def test_without_the_policy_a_held_pass_still_waits_for_the_owner(engine, studio, settings):
    allow_director_approval(engine, False)
    log, ids = a_day(engine, YESTERDAY_NOON())
    registry = registry_with(studio, StandIn(lambda prompt: her_answer(GOOD)))
    _held_pass(engine, registry, log, ids)

    outcome = run_serial_stage(engine, registry, settings)

    assert outcome["artefacts"]["approved"] == 0 and "aprobarea ta" in outcome["reason"]
    (episode,) = _episodes(engine).values()
    assert episode.status == "DRAFT"


# ---------------------------------------------------------------------------
# The factual room
# ---------------------------------------------------------------------------

#: Two titles that keep the narration's promise (the story review's own check), one for
#: experts and one for a stranger; the stand-in Director tells the versions apart by them.
JARGON = "Webb's infrared photometry of the telescope's universe"
PLAIN = "The light your eyes were not built for"
#: The one fact the topic's claim states, in the e2e day's words: the narration must say it.
FACT = "The James Webb telescope observes the universe in infrared light."
_NARRATION = (
    "Most of what the universe is doing happens in light your eyes will never catch, and that "
    "is where this story starts tonight.",
    "The James Webb telescope observes the universe in infrared light, which is the part of "
    "the spectrum that carries heat rather than colour.",
    "So the dust that hides a young star from us is no longer a wall, and the picture "
    "underneath it finally arrives.",
    "Look up tonight and remember that the dark you see is only the part of the sky your eyes "
    "were built for.",
)


def _script(prompt: str, title: str) -> str:
    """The stand-in Scriptwriter's answer: four scenes citing the claims the brief offered."""
    import re

    claim_ids = sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27}", prompt)))
    purposes = ["HOOK", "EVIDENCE", "PAYOFF", "ENDING"]
    visuals = ["a dark sky", "the mirror", "dust clearing", "a person looking up"]
    return json.dumps(
        {
            "title": title,
            "core_message": "Infrared shows what visible light hides.",
            "takeaway": "The sky is not as empty as it looks.",
            "hook": _NARRATION[0],
            "ending": _NARRATION[-1],
            "cta": "Look up tonight and ask what else is hiding.",
            "cta_kind": "CURIOSITY",
            "scenes": [
                {
                    "narration": line,
                    "visual": visual,
                    "purpose": purpose,
                    "claim_ids": claim_ids[:1],
                }
                for line, visual, purpose in zip(_NARRATION, visuals, purposes, strict=True)
            ],
        }
    )


@pytest.fixture
def script_room(engine, studio, monkeypatch):
    """A SELECTED topic with a SUPPORTED claim, and the stage's camera steps faked: the
    storyboard records which script it was built from, the shot plan is empty."""
    from app.factual.models import FactualClaim, TopicIdea
    from app.runbook import stages
    from app.services import utc_now

    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Infrared light and what it shows",
                topic="Astronomy",
                angle="What a telescope sees that eyes cannot",
                target_audience="science_enthusiasts",
                novelty_score=0.92,
                status="SELECTED",
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            FactualClaim(
                id=str(uuid4()),
                topic_id=topic_id,
                claim_text=FACT,
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.95,
                created_at=utc_now(),
            )
        )
    storyboarded: list[str] = []

    def storyboard(engine_, script_id, style, ratio, correlation):
        storyboarded.append(script_id)
        return {"id": str(uuid4()), "script_draft_id": script_id}

    monkeypatch.setattr(stages, "generate_storyboard_from_script", storyboard)
    monkeypatch.setattr(stages, "write_shot_prompts", lambda *a, **k: {"shots": []})
    return {"topic_id": topic_id, "storyboarded": storyboarded}


def _scripts(engine) -> dict[str, ScriptDraft]:
    with Session(engine) as session:
        rows = session.scalars(select(ScriptDraft)).all()
        session.expunge_all()
    return {row.title: row for row in rows}


def test_the_factual_short_below_the_bar_is_rewritten_and_the_rewrite_is_approved(
    engine, studio, settings, script_room
):
    from app.runbook import stages

    def writer(prompt: str) -> str:
        return _script(prompt, PLAIN if "EDITORIAL JUDGEMENT" in prompt else JARGON)

    def director(prompt: str) -> dict[str, Any]:
        return her_answer(WEAK if JARGON in prompt else GOOD)

    model = StandIn(director, on_script=writer)
    outcome = stages._script_and_storyboard(
        engine, registry_with(studio, model), "en", 30, settings=settings
    )

    assert outcome["status"] == "COMPLETED", outcome
    artefacts = outcome["artefacts"]
    assert artefacts["scripts"] == 2 and artefacts["storyboards"] == 1
    assert artefacts["story_reviews"][0]["editorial"]["total"] == 40
    scripts = _scripts(engine)
    jargon, plain = scripts[JARGON], scripts[PLAIN]
    assert plain.status == "APPROVED"
    assert script_room["storyboarded"] == [plain.id]
    assert plain.story_json["editorial"]["shipped"]["total"] == 40
    assert plain.story_json["editorial"]["kind"] == FACTUAL_SHORT
    assert jargon.status == "VERIFIED_PASS"
    assert jargon.story_json["editorial"]["superseded_by"] == plain.id
    assert jargon.story_json["editorial"]["total"] == 25
    events = _events(engine, JUDGED_EVENT)
    assert [(e.aggregate_type, e.aggregate_id, e.payload["shipped"]) for e in events] == [
        ("script_draft", jargon.id, False),
        ("script_draft", plain.id, True),
    ]
    # The rewrite was asked through the writer's own path: the brief among its notes, the
    # previous draft shown, the claims checked again.
    rewrite_prompt = model.script_prompts()[-1]
    assert "CE TREBUIE SCHIMBAT" in rewrite_prompt
    assert "hook (3/10)" in rewrite_prompt and f"CHANGE: {BRIEF['change']}" in rewrite_prompt
    assert JARGON in rewrite_prompt  # the previous draft, as data
    with Session(engine) as session:
        reviews = session.scalars(select(StoryReview)).all()
    assert sorted(r.script_id for r in reviews) == sorted([jargon.id, plain.id])
    assert _owner_letters(engine) == []
    # The next day the room owes this topic nothing and no script waits for the Owner.
    with Session(engine) as session:
        assert stages.script_work(session, [script_room["topic_id"]]) == []
        assert stages._script_awaiting_owner(session) is None


def test_a_later_version_the_review_sent_back_owes_the_room_nothing(
    engine, studio, settings, script_room
):
    """Two versions allowed: the first passes its review at 30, the rewrite scores 45 and the
    story review sends it back on taste. The first ships below the bar (one letter), the newer
    REVISE draft is marked superseded — and `script_work`, which owes a rewrite to a topic
    whose newest draft was sent back, owes this one nothing."""
    from app.runbook import stages

    settings.editorial_rounds = 2

    def writer(prompt: str) -> str:
        return _script(prompt, PLAIN if "EDITORIAL JUDGEMENT" in prompt else JARGON)

    def director(prompt: str) -> dict[str, Any]:
        return her_answer(with_total(30) if JARGON in prompt else dict.fromkeys(CRITERION_KEYS, 9))

    model = StandIn(
        director,
        on_script=writer,
        story_review=lambda prompt: "REVISE" if PLAIN in prompt else "PASS",
    )
    outcome = stages._script_and_storyboard(
        engine, registry_with(studio, model), "en", 30, settings=settings
    )

    assert outcome["status"] == "COMPLETED", outcome
    scripts = _scripts(engine)
    jargon, plain = scripts[JARGON], scripts[PLAIN]
    assert jargon.status == "APPROVED" and script_room["storyboarded"] == [jargon.id]
    assert jargon.story_json["editorial"]["shipped"]["total"] == 30
    assert jargon.story_json["editorial"]["stopped"] == STOP_ROUNDS_SPENT
    assert plain.status == "VERIFIED_PASS"
    assert plain.story_json["editorial"]["superseded_by"] == jargon.id
    assert plain.story_json["editorial"]["eligible"] is False
    assert plain.story_json["editorial"]["total"] == 45
    with Session(engine) as session:
        newest = session.scalars(select(StoryReview).where(StoryReview.script_id == plain.id)).all()
        assert [r.verdict for r in newest] == ["REVISE"]
        assert stages.script_work(session, [script_room["topic_id"]]) == []
        assert stages._script_awaiting_owner(session) is None
    (letter,) = _owner_letters(engine)
    assert letter.body_json["kind"] == FACTUAL_SHORT and "short-ul" in letter.body_text
    assert "30/50" in letter.subject


# ---------------------------------------------------------------------------
# The weekly review
# ---------------------------------------------------------------------------


def test_the_weekly_review_reads_the_shipped_total_for_both_kinds(engine):
    from app.analytics.services import _editorial_total
    from app.factual.models import TopicIdea
    from app.services import utc_now

    now = utc_now()
    topic_id, factual_id, serial_id, episode_id, log_id = (str(uuid4()) for _ in range(5))
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="T",
                topic="t",
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
                id=factual_id,
                topic_id=topic_id,
                title="A short",
                voiceover_full_text="x",
                claim_ids_json=[],
                status="APPROVED",
                story_json={"editorial": {"shipped": {"total": 38}}},
                created_at=now,
            )
        )
        session.add(
            ScriptDraft(
                id=serial_id,
                topic_id=topic_id,
                title="An episode",
                voiceover_full_text="x",
                claim_ids_json=[],
                status="APPROVED",
                story_json={"kind": "office_serial_episode", "episode_id": episode_id},
                created_at=now,
            )
        )
        from app.story.models import DailyStudioLog

        session.add(
            DailyStudioLog(
                id=log_id,
                business_date="2026-10-11",
                timezone="Europe/Bucharest",
                status="CLOSED",
                roster_json=[],
                notable_events_json=[],
                event_counts_json={},
                closed_at=now,
            )
        )
        session.flush()
        session.add(
            StoryEpisode(
                id=episode_id,
                log_id=log_id,
                title="An episode",
                beats_json=[],
                grounded_event_ids_json=[],
                continuity_json={},
                status="APPROVED",
                review_json={"verdict": "PASS", "editorial": {"shipped": {"total": 41}}},
                created_at=now,
            )
        )
    with Session(engine) as session:
        assert _editorial_total(session, session.get(ScriptDraft, factual_id)) == 38
        assert _editorial_total(session, session.get(ScriptDraft, serial_id)) == 41
        unjudged = ScriptDraft(story_json={"kind": "x"})
        assert _editorial_total(session, unjudged) is None
