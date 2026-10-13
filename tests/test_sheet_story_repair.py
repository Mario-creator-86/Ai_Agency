"""A legacy film must be reviewed before the editor is sent to its blocked tool."""

from app.factual.models import StoryReview
from app.media import sheet_story_repair as story
from app.media.models import Storyboard
from sqlalchemy.orm import Session
from test_sheet_blocker_repair import film  # noqa: F401


def test_missing_review_is_done_by_director_before_editor(
    engine,
    film,  # noqa: F811
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(story, "story_gate", lambda *a: (bool(calls), "Missing review"))
    monkeypatch.setattr(story, "latest_review", lambda *a: None)
    monkeypatch.setattr(
        story,
        "review_story",
        lambda *a, **k: (
            calls.append("Director") or {"verdict": "PASS", "notes": [], "model_used": True}
        ),
    )
    result = story.repair_story(engine, object(), film, "test", "report", [])
    assert calls == ["Director"]
    assert result is None


def test_failed_review_returns_writer_cause_without_calling_editor(
    engine,
    film,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(story, "story_gate", lambda *a: (False, "Missing ending"))
    monkeypatch.setattr(
        story,
        "latest_review",
        lambda *a: StoryReview(verdict="REVISE", notes_json={"notes": ["Add an ending"]}),
    )
    monkeypatch.setattr(
        story,
        "agent_write_script",
        lambda *a, **k: (_ for _ in ()).throw(
            story.ScriptRejected("Writer returned no usable script")
        ),
    )
    result = story.repair_story(engine, object(), film, "test", "report", [])
    assert result["status"] == "UNRESOLVED"
    assert result["responsible_role"] == "ScriptWriter"
    assert "Writer returned no usable script" in result["reason"]


def test_existing_approved_story_needs_no_new_review(
    engine,
    film,  # noqa: F811
    monkeypatch,
):
    monkeypatch.setattr(story, "story_gate", lambda *a: (True, ""))
    monkeypatch.setattr(
        story,
        "review_story",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("already passed")),
    )
    assert story.repair_story(engine, object(), film, "test", "report", []) is None
    with Session(engine) as session:
        assert session.get(Storyboard, film)
