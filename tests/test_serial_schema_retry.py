"""Offline regression: invalid future thread ids do not waste a real serial audit."""

import pytest

from app.story.services import (
    DraftRefused,
    _INSTRUCTIONS,
    _NextEpisode,
    _next_episode_plan,
    _read_with_one_repair,
)


def _plan(thread: str) -> _NextEpisode:
    return _NextEpisode(
        premise="Marcus has to confess the lie to Sarah.",
        cold_open_line="Sarah, I need to tell you something.",
        open_question="Will Sarah forgive Marcus?",
        threads_to_pay_off=[thread],
    )


def test_next_chapter_rejects_fabricated_thread_ids_but_accepts_new_conflict_in_words():
    with pytest.raises(DraftRefused, match="T3"):
        _next_episode_plan(_plan("T3"), ["T2"], [], "original-answer")
    accepted = _next_episode_plan(
        _plan("Marcus must confess the secret he invented today"),
        ["T2"], [], "revised-answer"
    )
    assert accepted["threads_to_pay_off"] == [
        "Marcus must confess the secret he invented today"
    ]
    assert _next_episode_plan(_plan("T2"), ["T2"], [], "original-answer")[
        "threads_to_pay_off"
    ] == ["T2"]


def test_writer_is_told_not_to_invent_thread_ids_for_new_romance_arcs():
    assert "For threads_to_pay_off, use an EXISTING T-number" in _INSTRUCTIONS
    assert "new IDs are assigned only after an episode is approved" in _INSTRUCTIONS


def test_invalid_first_draft_receives_one_targeted_rewrite_with_same_canon():
    answers = iter(["T3", "Marcus must confess the secret he invented today"])
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"output_text": next(answers)}

    def read(raw):
        return _next_episode_plan(_plan(raw), ["T2"], [], raw)

    result, draft, attempts, refusal = _read_with_one_repair(
        ask, read, lambda text: text, ""
    )
    assert len(prompts) == attempts == 2
    assert refusal and "T3" in refusal
    assert "YOUR PREVIOUS ANSWER WAS REFUSED" in prompts[1]
    assert "T3" in prompts[1]
    assert result["output_text"] == draft["threads_to_pay_off"][0]


def test_two_schema_refusals_stop_after_two_calls_not_an_unbounded_loop():
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"output_text": "T3"}

    def read(raw):
        return _next_episode_plan(_plan(raw), ["T2"], [], raw)

    with pytest.raises(DraftRefused, match="T3") as exc:
        _read_with_one_repair(ask, read, lambda text: text, "")
    assert len(prompts) == 2
    assert exc.value.answer == "T3"


def test_valid_first_draft_does_not_spend_on_rewrite():
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"output_text": "T2"}

    def read(raw):
        return _next_episode_plan(_plan(raw), ["T2"], [], raw)

    result, draft, attempts, refusal = _read_with_one_repair(
        ask, read, lambda text: text, ""
    )
    assert len(prompts) == attempts == 1
    assert refusal is None
    assert draft["threads_to_pay_off"] == ["T2"]
