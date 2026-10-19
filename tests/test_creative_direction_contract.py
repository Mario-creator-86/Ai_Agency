"""Offline contracts for Sarah's direction and Kael's story-first visual briefs.

Only inspect built-in instruction strings; no vendor, database or media calls.
"""
from app.agents.editorial_judgement import SERIAL_EPISODE, _KIND_NOTES
from app.media.prompt_agent import (
    _EDITOR_FINAL_INSTRUCTIONS,
    _SERIAL_SHOTS_INSTRUCTIONS,
    _SHOTS_INSTRUCTIONS,
)
from app.media.scene_rewrite import (
    _BRIEF_INSTRUCTIONS,
    _REVIEW_INSTRUCTIONS,
    _REWRITE_INSTRUCTIONS,
)
from app.story.review import _INSTRUCTIONS as SARAH_STORY_REVIEW
from app.story.services import _INSTRUCTIONS as MARCUS_WRITER_BRIEF


def test_sarah_can_approve_stories_without_romance_or_forced_jokes():
    assert "not a compulsory romance" in SARAH_STORY_REVIEW
    assert "Do not demand a kiss" in SARAH_STORY_REVIEW
    assert "Genre and audience" in SARAH_STORY_REVIEW
    assert "Romance is OPTIONAL" in MARCUS_WRITER_BRIEF
    assert "Romance is optional" in _KIND_NOTES[SERIAL_EPISODE]


def test_sarah_requires_scene_causes_and_specific_rewrite_guidance():
    assert "BUT or THEREFORE" in SARAH_STORY_REVIEW
    assert "not evidence of a real hook" in SARAH_STORY_REVIEW
    assert "KEEP, CHANGE and AVOID" in SARAH_STORY_REVIEW
    assert "permanent character arcs" in SARAH_STORY_REVIEW
    assert "fictional plot events" in SARAH_STORY_REVIEW
    assert '"button": 1-5' in SARAH_STORY_REVIEW


def test_kael_directs_from_character_reactions_not_camera_quotas():
    assert "what must change emotionally or causally" in _SERIAL_SHOTS_INSTRUCTIONS
    assert "reaction close-up" in _SERIAL_SHOTS_INSTRUCTIONS
    assert "Repeating static" in _SERIAL_SHOTS_INSTRUCTIONS
    assert "never the same move twice in a row" not in _SERIAL_SHOTS_INSTRUCTIONS
    assert "never the same one three scenes" not in _SHOTS_INSTRUCTIONS
    assert "Do not add props" in _EDITOR_FINAL_INSTRUCTIONS
    assert "Still camera is appropriate" in _EDITOR_FINAL_INSTRUCTIONS


def test_sarah_and_kael_repair_exact_prompts_without_new_paid_mistakes():
    assert "approved emotional beat" in _BRIEF_INSTRUCTIONS
    assert "Before any new purchase" in _REVIEW_INSTRUCTIONS
    assert "Do not create new blocking findings" in _REVIEW_INSTRUCTIONS
    assert "quality-control findings supplied" in _REVIEW_INSTRUCTIONS
    assert "Static is valid" in _REWRITE_INSTRUCTIONS
    assert "not for arbitrary variety" in _REWRITE_INSTRUCTIONS
    assert "the still kept on a motion rewrite" in _REVIEW_INSTRUCTIONS
