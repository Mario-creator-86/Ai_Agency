"""What the renders cap kept never trains the studio's model (the dishonest-code audit of
2026-10-16, SAFE-004).

A still the gate refused that stands as the scene's picture because nothing more may be bought
is APPROVED by the cap (`assembler.CAP_APPROVER`), and the LTX training set collected every
APPROVED take as one «the gates let through»: a LoRA would learn the faults the gates refused.
Now a take kept under the cap is not written, and an old manifest row of one is not counted
towards the milestone. Nothing is trained or bought.
"""

from __future__ import annotations

from app.agents.services import seed_initial_workforce
from app.media.assembler import CAP_APPROVER
from app.workflows.passes import WatchdogContext
from app.workflows.passes import training_set as training
from test_training_set import a_film, a_take, manifest


def test_a_still_approved_under_the_cap_is_not_a_training_sample(engine, settings, tmp_path):
    seed_initial_workforce(engine)
    film = a_film(engine, tmp_path, serial=True)
    gated = a_take(engine, tmp_path, film["board"], 1, "still")
    a_take(engine, tmp_path, film["board"], 2, "still", approved_by=CAP_APPROVER)
    a_take(engine, tmp_path, film["board"], 2, "motion", approved_by=CAP_APPROVER)

    added = dict(training.collect_training_samples(WatchdogContext(engine, settings, "wd")))

    assert added["added"] == 1
    assert [row["take_id"] for row in manifest(settings)] == [gated]
    # A row the cap kept that an older pass wrote is not counted towards the milestone.
    path = training.manifest_path(settings)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            '{"take_id": "old", "kind": "motion", "serial": true, "approved_by": "director_cap"}\n'
        )
    again = dict(training.collect_training_samples(WatchdogContext(engine, settings, "wd")))
    assert again["clips"] == 0
