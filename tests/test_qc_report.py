"""The Owner's quality-control report, written from what was measured and nothing else.

Pure tests on the Nepal film's real report (tests/fixtures/nepal_1d530880/qc_report.json,
copied from the scratchpad copy of the database; the original is never opened). No provider,
no database, no network. What is asserted: the summary names the measured true peak, the two
scenes that failed and the credits the balance actually moved; a spend nobody measured reads
"necunoscut" and an estimate is never shown as a cost; what is fixed for 0 credits (audio,
cards, encode) is kept apart from what needs credits, scene by scene, with the prices of a
shooting sheet; and no proposal is ever a whole-film render.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from app.media.qc_report import (
    FREE_HEADING,
    PAID_HEADING,
    UNKNOWN,
    measured_spend,
    qc_summary_ro,
    redo_proposals,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nepal_1d530880" / "qc_report.json"


@pytest.fixture(scope="module")
def nepal() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _sheet() -> dict:
    """A shooting sheet in `cost_plan.plan_film`'s shape, with its own (fixed) prices."""
    return {
        "credit_usd": 0.01,
        "scenes": [
            {
                "scene_index": 1,
                "kind": "LIVE",
                "model_id": "seedance2_5",
                "resolution": "1080p",
                "credits": 340,
                "still_credits": 18,
                "price_source": "tarif publicat 27.09",
            },
            {
                "scene_index": 2,
                "kind": "LIVE",
                "model_id": "veo3.1_fast",
                "resolution": "1080p",
                "credits": 60,
                "still_credits": 18,
                "price_source": "tarif publicat 27.09",
            },
            {
                "scene_index": 3,
                "kind": "LIVE",
                "model_id": "seedance2",
                "resolution": "1080p",
                "credits": 200,
                "still_credits": 18,
                "price_source": "măsurat",
            },
            {
                "scene_index": 4,
                "kind": "LIVE",
                "model_id": "veo3.1_fast",
                "resolution": "1080p",
                "credits": 60,
                "still_credits": 18,
                "price_source": "tarif publicat 27.09",
            },
            {"scene_index": 5, "kind": "DATA_CARD", "credits": 0, "still_credits": 0},
            {"scene_index": 6, "kind": "BLACK", "credits": 0, "still_credits": 0},
        ],
    }


def _with_scene_3_wrong(report: dict) -> dict:
    changed = copy.deepcopy(report)
    for scene in changed["checks_json"]["picture_qc"]["scenes"]:
        if scene["scene"] == 3:
            scene["shows_the_scene"] = False
            scene["reason"] = "A face fills the frame; the scene asked for distant figures."
    changed["checks_json"]["picture_qc"]["passed"] = False
    return changed


def _section(text: str, heading: str) -> str:
    """The lines under one heading, up to the next blank line."""
    lines = text.splitlines()
    start = lines.index(heading)
    out: list[str] = []
    for line in lines[start + 1 :]:
        if not line.strip():
            break
        out.append(line)
    return "\n".join(out)


# ------------------------------------------------------------------ the Nepal report


def test_nepal_summary_names_the_peak_the_two_scenes_and_the_measured_credits(nepal):
    text = qc_summary_ro(nepal["report"], nepal["credits_measured"])

    assert "−0,93 dBTP" in text
    assert "−1,0 dBTP" in text
    assert "Scena 5" in text
    assert "Scena 6" in text
    # The looker's own words are quoted as the evidence.
    assert "Black screen was requested" in text
    assert "966 de credite" in text
    assert "9,66 USD" in text
    assert "0,25" in text
    # The measured side is the measured one: no "necunoscut" for Runway.
    credits_line = next(line for line in text.splitlines() if line.startswith("Credite"))
    assert UNKNOWN not in credits_line


def test_an_unmeasured_spend_reads_necunoscut(nepal):
    # The second render measured nothing (credits_measured null).
    assert nepal["credits_measured_second_render"] is None
    for spend in (None, {}, nepal["credits_measured_second_render"]):
        text = qc_summary_ro(nepal["report"], spend)
        credits_line = next(line for line in text.splitlines() if line.startswith("Credite"))
        assert UNKNOWN in credits_line
        assert "966" not in text


def test_an_estimate_is_never_shown_as_a_cost(nepal):
    # A number with no balance before and after is a quote, not a measurement.
    estimated = {
        "runway": {"kind": "runway", "unit": "credits", "spent": 500.0, "usd": 5.0},
        "motion": {"estimated_credits": 1224, "estimated_usd": 12.24},
    }
    text = qc_summary_ro(nepal["report"], estimated)
    credits_line = next(line for line in text.splitlines() if line.startswith("Credite"))
    assert UNKNOWN in credits_line
    assert "500" not in text and "1.224" not in text and "12,24" not in text
    assert measured_spend(estimated)["runway_credits"] is None


def test_measured_spend_reads_the_balance_delta_not_the_spent_field(nepal):
    spend = measured_spend(nepal["credits_measured"])
    assert spend["runway_credits"] == 966.0
    assert spend["runway_usd"] == 9.66
    assert spend["voice_characters"] == 220.0
    # A record whose "spent" disagrees with its own balances is not trusted.
    lying = {
        "r": {"kind": "runway", "unit": "credits", "before": 100.0, "after": 90.0, "spent": 3.0}
    }
    assert measured_spend(lying)["runway_credits"] is None


# ------------------------------------------------------------------ free versus paid


def test_it_separates_free_fixes_from_paid_ones_per_scene_with_sheet_prices(nepal):
    report = _with_scene_3_wrong(nepal["report"])
    sheet = _sheet()
    proposals = redo_proposals(report, sheet=sheet)
    by = {(p.scene_index, p.redo): p for p in proposals}

    assert by[(None, "audio")].credits == 0
    assert by[(5, "card")].credits == 0
    assert by[(6, "card")].credits == 0
    assert by[(3, "still")].credits == 18
    assert by[(3, "motion")].credits == 200
    assert by[(3, "motion")].usd_micros == 2_000_000
    assert by[(3, "motion")].price_source == "măsurat"
    assert by[(3, "motion")].model_id == "seedance2"
    # Scenes that passed are not touched, and nothing is a whole film.
    assert {p.scene_index for p in proposals} == {None, 3, 5, 6}
    assert {p.redo for p in proposals} <= {"still", "motion", "card", "audio", "encode"}

    text = qc_summary_ro(report, nepal["credits_measured"], sheet=sheet)
    free = _section(text, FREE_HEADING)
    paid = _section(text, PAID_HEADING)
    assert "se repară gratuit" in FREE_HEADING.lower()
    assert "necesită credite" in PAID_HEADING.lower()
    assert "Sunet" in free and "limitator" in free
    assert "Scena 5" in free and "grafic compus local" in free
    assert "Scena 6" in free and "ecran negru compus local" in free
    assert "Scena 3" not in free
    assert "Scena 3" in paid
    assert "18 credite" in paid and "200 de credite" in paid
    assert "seedance2" in paid and "măsurat" in paid
    assert "Scena 5" not in paid and "Scena 6" not in paid
    total = next(line for line in text.splitlines() if line.startswith("De plătit"))
    # Romanian counts: "18 credite", "200 de credite", "218 credite".
    assert "218 credite" in total and "218 de" not in total and "2,18 USD" in total


def test_without_a_sheet_a_paid_scene_says_its_price_is_unknown(nepal):
    report = _with_scene_3_wrong(nepal["report"])
    proposals = redo_proposals(report)
    paid = [p for p in proposals if p.scene_index == 3]
    assert {p.redo for p in paid} == {"still", "motion"}
    assert all(p.credits is None for p in paid)
    text = qc_summary_ro(report, None)
    assert "preț necunoscut" in _section(text, PAID_HEADING)
    # Nothing priced is not nothing to pay.
    assert f"De plătit: {UNKNOWN} (2 poziții fără preț)" in text
    assert "De plătit: 0" not in text
    # The cards of the Nepal film are recognised from what they asked, without a sheet.
    kinds = {(p.scene_index, p.redo) for p in proposals}
    assert (5, "card") in kinds and (6, "card") in kinds


def test_nothing_to_buy_says_so(nepal):
    text = qc_summary_ro(nepal["report"], nepal["credits_measured"])
    assert "nimic" in _section(text, PAID_HEADING)
    assert "De plătit: 0 credite" in text


def test_encode_and_caption_failures_are_fixed_for_free(nepal):
    report = copy.deepcopy(nepal["report"])
    report["checks_json"]["technical_qc"].update(
        {"passed": False, "measured_bitrate_bps": 2_579_530, "color_range": "pc"}
    )
    report["checks_json"]["captions_qc"].update(
        {"passed": False, "problems": ["subtitrare în afara zonei sigure"]}
    )
    proposals = redo_proposals(report)
    encode = [p for p in proposals if p.redo == "encode"]
    assert encode and all(p.credits == 0 and p.scene_index is None for p in encode)
    text = qc_summary_ro(report, None)
    free = _section(text, FREE_HEADING)
    assert "codare" in free.lower() and "subtitr" in free.lower()


def test_a_check_that_did_not_run_is_named_as_a_failure(nepal):
    report = copy.deepcopy(nepal["report"])
    report["checks_json"]["picture_qc"] = {"status": "NOT_RUN", "passed": None, "scenes": []}
    text = qc_summary_ro(report, None)
    assert "nu a rulat" in text


def test_the_summary_is_deterministic_and_never_proposes_a_whole_render(nepal):
    report = _with_scene_3_wrong(nepal["report"])
    one = qc_summary_ro(report, nepal["credits_measured"], sheet=_sheet())
    two = qc_summary_ro(report, nepal["credits_measured"], sheet=_sheet())
    assert one == two
    lowered = one.lower()
    for phrase in ("re-render", "randează din nou", "randare nouă", "tot filmul din nou"):
        assert phrase not in lowered


def test_a_failed_motion_check_that_counts_its_scenes_still_gets_the_owners_letter(nepal):
    """The real motion_qc stores ``scenes`` as a COUNT (6), next to the fallback numbers. The
    zero-credit Nepal rehearsal (2026-10-01) failed only on motion, and the letter writer
    raised TypeError on that integer, so the Owner got no report at all."""
    report = copy.deepcopy(nepal["report"])
    report["checks_json"]["motion_qc"] = {
        "passed": False,
        "scenes": 6,
        "fallback_scenes": 4,
        "max_fallback_scenes": 3,
        "clips": [{"scene_index": 3, "passed": False, "reason": "clip static"}],
    }
    text = qc_summary_ro(report, nepal["credits_measured"])
    assert "Mișcare" in text and "4 scene" in text


def test_a_scene_the_films_qc_found_made_of_panels_gets_a_new_still_and_new_motion():
    """2026-10-09: scene 5 of «The Particle That Shouldn't Exist (But Does)» was three stacked
    panels. The film's span check (qc.span_picture_qc) fails such a scene, and the studio's own
    report proposes what fixes it, priced from the sheet: a new still and new motion for that
    scene, nothing for the scene that passed, never the whole film."""
    reason = (
        "nu e o singură fotografie: cadrul first are o bandă plată pe toată lățimea, la "
        "mijloc, între două imagini (rândurile 159-320 din 480, 34% din înălțime; prag 15%)"
    )
    report = {
        "status": "FAILED",
        "score": 0.75,
        "checks_json": {
            "picture_spans_qc": {
                "status": "MEASURED",
                "passed": False,
                "detail": "2 din 2 scene filmate privite pe primul, mijlocul și ultimul cadru",
                "scenes": [
                    {"scene_index": 3, "kind": "LIVE", "status": "PASSED", "passed": True},
                    {
                        "scene_index": 4,
                        "kind": "LIVE",
                        "status": "FAILED",
                        "passed": False,
                        "reason": reason,
                        "panels": {"status": "FAILED", "detail_ro": reason},
                    },
                ],
                "failures": [f"Scena 4: {reason}"],
            }
        },
        "failure_reasons_json": [f"Scena 4: {reason}"],
    }

    proposals = redo_proposals(report, sheet=_sheet())

    assert {(p.scene_index, p.redo) for p in proposals} == {(4, "still"), (4, "motion")}
    by = {p.redo: p for p in proposals}
    assert by["still"].credits == 18 and by["motion"].credits == 60
    assert "singură fotografie" in by["still"].reason
    paid = _section(qc_summary_ro(report, None, sheet=_sheet()), PAID_HEADING)
    assert "Scena 4: imagine nouă" in paid and "Scena 4: mișcare nouă" in paid
    assert "Scena 3" not in paid
