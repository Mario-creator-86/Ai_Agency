"""The day's headline counts the film a legacy run published.

The runbook recounts a stored run from its artefacts (`app.runbook.services._summarised`). The
publish stage has returned its films under a nested ``published`` list since Phase B/C; a run
recorded before that carries the one publication flat, as ``publication_id`` and
``publication_status``. The 12.09 run of the Owner's studio is one of those: its publication
86fe911d is PUBLISHED on YouTube, yet the headline read «Niciun film publicat azi», because only
the nested key was counted. A legacy publish artefact is now read by the keys it has.
"""

from __future__ import annotations

from typing import Any

from app.runbook.services import _summarised, produced_by, run_summary


def _publish(artefacts: dict[str, Any], status: str = "COMPLETED") -> dict[str, Any]:
    return {"stage": "publish", "status": status, "artefacts": artefacts}


LEGACY_PUBLISHED = {
    "publication_id": "86fe911d-11ce-4243-9cc2-70809577517e",
    "publication_status": "PUBLISHED",
    "title": "How ATLAS Caught the Higgs Boson in Real Time",
}


def test_a_legacy_publish_artefact_counts_its_one_publication() -> None:
    assert produced_by(_publish(LEGACY_PUBLISHED)) == 1


def test_a_legacy_scheduled_or_confirmed_film_is_on_the_channel_and_counts() -> None:
    for status in ("REMOTE_CONFIRMED", "SCHEDULED"):
        assert produced_by(_publish({**LEGACY_PUBLISHED, "publication_status": status})) == 1


def test_a_legacy_publication_that_did_not_go_out_counts_nothing() -> None:
    for status in ("PUBLISHED_SIMULATED", "FAILED", "BLOCKED", "VALIDATED", "", None):
        artefacts = {**LEGACY_PUBLISHED, "publication_status": status}
        assert produced_by(_publish(artefacts)) == 0, status
    # a status with no publication behind it is not a film either
    assert produced_by(_publish({"publication_status": "PUBLISHED"})) == 0


def test_the_nested_list_of_a_current_run_is_counted_as_before_and_not_twice() -> None:
    two = [
        {"publication_id": "a", "publication_status": "PUBLISHED"},
        {"publication_id": "b", "publication_status": "SCHEDULED"},
    ]
    # the current stage also repeats the first film flat beside the list
    current = {"published": two, "publication_id": "a", "publication_status": "PUBLISHED"}
    assert produced_by(_publish(current)) == 2
    assert produced_by(_publish({"published": []})) == 0


def test_a_day_that_published_nothing_still_says_so() -> None:
    refused = {"not_published": [{"asset_id": "x", "status": "COMPLETED"}]}
    assert produced_by(_publish(refused)) == 0
    summary, _ = run_summary([{**_publish(refused), "produced": 0}])
    assert summary.endswith("Niciun film publicat azi.")


def test_the_stored_12_09_run_now_reads_true() -> None:
    """The captured newest run, as `/runbook/runs` recounts it (no stored counts)."""
    stages = [
        {"stage": "preflight", "status": "COMPLETED", "artefacts": {"status": "READY"}},
        {"stage": "idea_generation", "status": "COMPLETED", "artefacts": {"pool": 6}},
        {"stage": "media", "status": "COMPLETED", "artefacts": {"assets": ["ed53bac1"]}},
        _publish(LEGACY_PUBLISHED),
    ]
    summary, productive = _summarised(stages)
    assert "Filme publicate: 1." in summary
    assert "Niciun film publicat azi." not in summary
    assert "«publish»" not in summary
    assert productive == 2
