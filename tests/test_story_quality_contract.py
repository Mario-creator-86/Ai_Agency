"""Offline regression checks for the shared Marcus / Sarah narrative contract."""
from app.story.quality_contract import KEYS, QualityAnswer, writer_instructions, director_instructions, quality_issues
from app.story.review import EpisodeVerdict, _held_to_her_rubric

RUBRIC = {key: 4 for key in ("hook", "situation", "turn", "payoff", "voices", "button")}


def answers(failed=None):
    return [
        QualityAnswer(
            question_id=key, passed=key != failed,
            evidence=f"Beat {n}, concrete dialogue",
            reason="The character changes course." if key != failed else "The central promise is abandoned.",
        )
        for n, key in enumerate(KEYS, 1)
    ]


def test_shared_questions_and_same_call():
    assert len(KEYS) == len(set(KEYS)) == 8
    for key in KEYS:
        assert writer_instructions().count(key + ":") == 1
        assert director_instructions().count(key + ":") == 1
    assert "SAME write_episode CALL" in writer_instructions()
    assert "SAME episode_review CALL" in director_instructions()


def test_fully_evidenced_answers():
    assert quality_issues(answers()) == []


def test_director_cannot_pass_an_explicitly_weak_story():
    verdict = EpisodeVerdict(verdict="PASS", scores=RUBRIC, quality=answers("Q6_CENTRAL_PROMISE"))
    checked = _held_to_her_rubric(verdict, "Sarah")
    assert checked.verdict == "FAIL"
    assert "Q6_CENTRAL_PROMISE" in " ".join(checked.reasons)
    assert "Q6_CENTRAL_PROMISE" in checked.notes


def test_incomplete_answer_and_unsubstantiated_yes():
    rows = answers()[:7]
    rows[0] = rows[0].model_copy(update={"evidence": ""})
    issues = quality_issues(rows)
    assert any("Q1_HOOK" in x for x in issues)
    assert any("Q8_FRESH_AND_CLEAR" in x for x in issues)


def test_legacy_verdict_without_quality_remains_readable():
    assert _held_to_her_rubric(EpisodeVerdict(verdict="PASS", scores=RUBRIC), "Sarah").verdict == "PASS"
