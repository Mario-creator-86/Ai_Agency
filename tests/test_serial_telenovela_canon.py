"""Offline tests for serialized fictional relationships, without model or media calls."""
from types import SimpleNamespace

from app.story.quality_contract import SATIRE_POLICY, director_instructions, writer_instructions
from app.story.services import (
    CHARACTER_ARC_PREFIX,
    SHOW_TONE,
    _INSTRUCTIONS,
    _canon_caps,
    _canon_step,
    _previously,
)


def _episode(number: int, changes: list[dict], recurring: list[str] | None = None):
    return SimpleNamespace(
        id=f"fiction-{number}",
        title=f"Chapter {number}",
        continuity_json={
            "business_date": f"2026-10-{number % 28 + 1:02d}",
            "summary": f"Chapter {number} advances a relationship.",
            "character_updates": changes,
            "recurring": recurring or [],
            "threads_opened": [],
            "threads_closed": [],
        },
    )


def test_evolving_relationship_survives_thirty_episodes():
    number, threads, recurring, summaries = 0, [], [], []
    for index in range(1, 31):
        changes = []
        if index == 1:
            changes = [{"key": "Marcus & Sarah", "state": "Marcus secretly loves Sarah; she does not know."}]
        if index == 10:
            changes = [{"key": "Marcus & Sarah", "state": "They went on a first date; Sarah is cautious."}]
        if index == 19:
            changes = [{"key": "Marcus & Sarah", "state": "They married; Vera knows a secret about Marcus."}]
        if index == 25:
            changes = [{"key": "Marcus & Sarah", "state": "Separated after a betrayal; Sarah is still hurt."}]
        number, threads, recurring, summaries = _canon_step(
            number, threads, recurring, summaries, _episode(index, changes)
        )
        threads, recurring, summaries = _canon_caps(threads, recurring, summaries)

    arcs = [x for x in recurring if x.startswith(CHARACTER_ARC_PREFIX)]
    assert number == 30
    assert len(arcs) == 1
    assert "Separated after a betrayal" in arcs[0]
    assert "They married" not in arcs[0]
    assert len(summaries) == 3
    memory = SimpleNamespace(summaries_json=summaries, threads_json=threads, recurring_json=recurring)
    shown = _previously(memory, 31)
    assert "PERMANENT CHARACTER CANON" in shown
    assert "Sarah is still hurt" in shown
    assert "Marcus & Sarah" in shown


def test_long_term_relationships_are_not_evicted_by_running_gags():
    number, threads, recurring, summaries = 0, [], [], []
    for index in range(1, 22):
        updates = (
            [{"key": "Kael & Lyra", "state": "Kael feels guilty after betraying Lyra's trust."}]
            if index == 1 else []
        )
        number, threads, recurring, summaries = _canon_step(
            number, threads, recurring, summaries,
            _episode(index, updates, [f"joke number {index}"]),
        )
        threads, recurring, summaries = _canon_caps(threads, recurring, summaries)
    assert len([x for x in recurring if x.startswith(CHARACTER_ARC_PREFIX)]) == 1
    assert any("Kael feels guilty" in x for x in recurring)
    assert len([x for x in recurring if not x.startswith(CHARACTER_ARC_PREFIX)]) == 12


def test_writer_and_reviewers_receive_varied_character_drama_not_work_log():
    assert "continuing ensemble dramedy" in SHOW_TONE
    assert "Romance is OPTIONAL" in SHOW_TONE
    assert "comedy, mystery, friendship" in SHOW_TONE
    assert "event_ids" in _INSTRUCTIONS
    assert "character_updates" in _INSTRUCTIONS
    assert "PREVIOUSLY is the binding fictional canon" in _INSTRUCTIONS
    assert "Production meetings, ledgers and model tests must NEVER" in _INSTRUCTIONS
    assert "silently consider" in _INSTRUCTIONS
    assert "BUT or THEREFORE" in _INSTRUCTIONS
    assert "Romance is OPTIONAL" in _INSTRUCTIONS
    for prompt in (writer_instructions(), director_instructions()):
        assert SATIRE_POLICY in prompt
        assert "relationship" in prompt.lower()
        assert "Romance is OPTIONAL" in prompt
        assert "BUT/THEREFORE" in prompt


def test_no_genre_quota_and_both_reviewer_layers_apply_scene_causality():
    from app.agents.editorial_judgement import _KIND_NOTES, SERIAL_EPISODE
    from app.story.quality_contract import QUESTIONS

    editorial = _KIND_NOTES[SERIAL_EPISODE]
    assert "Romance is optional" in editorial
    assert "never reward or demand it" in editorial
    assert "BUT or THEREFORE" in editorial
    assert "Do NOT reject an episode for lacking romance" in director_instructions()
    assert any(key == "Q3_CAUSAL_PROGRESS" and "scene" in question
               for key, question in QUESTIONS)

