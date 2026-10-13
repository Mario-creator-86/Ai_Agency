"""The price of a film before a credit is spent: the published table and the pure arithmetic.

The Nepal film cost over a thousand credits and the books said 0.74 USD, because the price
Runway sent was never read and nothing priced a film from the vendor's own table. These
tests pin that table (config/runway_prices.json, read from Runway's published pricing page)
and the pure functions the shooting sheet, the budget and the motion loop price with. No
provider is called: the module reads a JSON file and does arithmetic.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from app.media import cost_plan
from app.media.cost_plan import (
    PRICE_FILE,
    UnpricedError,
    apply_measured,
    attribute_measured_credits,
    credits_to_micros,
    load_price_table,
    plan_film,
    price_shot,
    price_still,
    row_status,
    source_label,
)

READ_ON = date(2026, 9, 27)


@pytest.fixture
def table():
    return load_price_table()


# ------------------------------------------------------------------ the published figures --


def test_the_published_prices_the_spec_quotes(table):
    """The four figures the spec's cost of the next film is built from."""
    assert price_shot("seedance2_5", "1080p", 6, audio=False, table=table) == 408
    # 20 credits a second at 480p is 80 for four seconds, and never less than the minimum.
    assert price_shot("seedance2_5", "480p", 4, audio=False, table=table) == 80
    assert price_shot("seedance2_5", "480p", 3, audio=False, table=table) == 80, "80 minimum"
    assert price_shot("veo3.1_fast", "1080p", 6, audio=False, table=table) == 60
    assert price_still("seedream5_pro", "2K", 2, table=table) == 18


def test_a_span_is_priced_at_the_whole_seconds_the_vendor_will_bill(table):
    """Durations are rounded UP to what the request asks for; 4.4 s is a 5 s shot."""
    assert price_shot("seedance2_5", "1080p", 4.4, table=table) == 5 * 68


def test_audio_is_priced_where_the_page_prices_it(table):
    assert price_shot("veo3.1", "1080p", 8, audio=True, table=table) == 320
    assert price_shot("veo3.1", "1080p", 8, audio=False, table=table) == 160


def test_a_model_the_page_does_not_list_is_unpriced_not_guessed(table):
    with pytest.raises(UnpricedError):
        price_shot("wan3_prime", "1080p", 5, table=table)
    with pytest.raises(UnpricedError):
        price_still("seedream5_pro", "8K", 1, table=table)


def test_every_row_carries_its_source_its_date_and_its_provenance():
    raw = json.loads(PRICE_FILE.read_text(encoding="utf-8"))
    assert raw["credit_usd"] == 0.01
    assert raw["rows"], "an empty table prices nothing"
    for row in raw["rows"]:
        assert row["source_url"].startswith("https://"), row
        date.fromisoformat(row["date"])
        assert row["provenance"] == "DOCUMENTED", row


def test_a_row_older_than_thirty_days_reports_nevalidat(table):
    row = table.row("seedance2_5", "1080p")
    read = date.fromisoformat(row.date)
    assert row_status(row, today=read) == "validat"
    assert row_status(row, today=date.fromordinal(read.toordinal() + 30)) == "validat"
    late = date.fromordinal(read.toordinal() + 31)
    assert row_status(row, today=late) == "nevalidat"
    assert source_label(row, today=late) == "nevalidat"
    assert source_label(row, today=read) == f"tarif publicat {read:%d.%m}"


def test_credits_become_usd_micros_exactly():
    assert credits_to_micros(1636, 0.01) == 16_360_000
    assert credits_to_micros(0, 0.01) == 0


# ------------------------------------------------------------------------- a whole film --


def test_the_next_film_costs_what_the_spec_says(table):
    """Four LIVE scenes (5 + 6 + 6 + 6 s), two cards at no cost, seedance2_5 at 1080p."""
    film = plan_film(
        [5, 6, 6, 6], model_id="seedance2_5", resolution="1080p", table=table, today=READ_ON
    )

    assert film["stills_credits"] == 72  # 4 scenes x 2 candidates x 9
    assert film["hero_credits"] == 340  # the first shot, 5 s x 68, kept in the film
    assert film["rest_credits"] == 18 * 68
    assert film["total_credits"] == 72 + 340 + 1224
    # The hard cap: the total, one full redo of the longest shot, one still round.
    assert film["cap_credits"] == film["total_credits"] + 6 * 68 + 72
    assert film["total_usd_micros"] == 16_360_000
    assert film["price_source"].startswith("tarif publicat")
    stale = plan_film(
        [5], model_id="seedance2_5", resolution="1080p", table=table, today=date(2026, 12, 1)
    )
    assert stale["price_source"] == "nevalidat", "a stale table is said to be stale"


def test_cheaper_alternatives_are_priced_side_by_side(table):
    film = plan_film([5, 6, 6, 6], model_id="seedance2_5", resolution="1080p", table=table)
    alternatives = {
        (a["model_id"], a["resolution"]): a["total_credits"] for a in film["alternatives"]
    }
    assert alternatives[("seedance2_5", "720p")] == 72 + 23 * 30
    assert alternatives[("seedance2", "1080p")] == 72 + 23 * 40
    # veo bills 4, 6 or 8 s: the 5 s hero is a 6 s shot there.
    assert alternatives[("veo3.1_fast", "1080p")] == 72 + 24 * 10


def test_a_film_with_no_live_scene_buys_nothing(table):
    film = plan_film([], model_id="seedance2_5", resolution="1080p", table=table)
    assert film["total_credits"] == 0 and film["cap_credits"] == 0


# ------------------------------------------------ one model per SCENE (Owner, 2026-09-27) --
#
# "Nu trebuie un singur model pe tot filmul! Trebuie sa optimizam costurile!" The film's cost
# is the sum of each scene's own choice; the premium model is paid only where a scene needs it.


def _mixed_film():
    return [
        {"scene_index": 1, "seconds": 5, "model_id": "seedance2_5", "resolution": "1080p"},
        {"scene_index": 2, "seconds": 6, "model_id": "veo3.1_fast", "resolution": "1080p"},
        {"scene_index": 3, "seconds": 5.2, "model_id": "wan3", "resolution": "1080p"},
        {"scene_index": 4, "seconds": 4, "kind": "DATA_CARD"},
        {"scene_index": 5, "seconds": 3, "kind": "BLACK"},
    ]


def test_a_film_is_the_sum_of_its_scenes_own_choices(table):
    film = plan_film(_mixed_film(), table=table)

    by_scene = {s["scene_index"]: s for s in film["scenes"]}
    assert by_scene[1]["credits"] == 5 * 68 and by_scene[1]["billed_seconds"] == 5
    assert by_scene[2]["credits"] == 6 * 10
    assert by_scene[3]["credits"] == 6 * 20, "5.2 s is billed as 6 whole seconds"
    # Cards and black are composed locally: no still, no motion, no credit.
    assert by_scene[4]["credits"] == 0 and by_scene[4]["model_id"] is None
    assert by_scene[5]["credits"] == 0
    assert film["stills_credits"] == 3 * 2 * 9, "stills for the three LIVE scenes only"
    assert film["hero_credits"] == 5 * 68, "the first LIVE scene is the hero test by default"
    assert film["rest_credits"] == 60 + 120
    assert film["total_credits"] == 54 + 340 + 180
    # The cap: the dearest single shot redone once, plus one still round.
    assert film["cap_credits"] == film["total_credits"] + 340 + 54
    assert film["model_id"] == "mixt"


def test_the_plan_reports_what_it_saved_against_premium_everywhere(table):
    film = plan_film(_mixed_film(), table=table)
    # Premium everywhere: every LIVE scene on seedance2_5 at 1080p (5 + 6 + 6 s).
    assert film["premium_credits"] == 54 + 17 * 68
    assert film["saved_credits"] == film["premium_credits"] - film["total_credits"]
    assert film["saved_credits"] > 0


def test_a_scene_can_name_itself_the_hero(table):
    scenes = _mixed_film()
    scenes[1]["hero"] = True
    film = plan_film(scenes, table=table)
    assert film["hero_scene"] == 2 and film["hero_credits"] == 60


def test_a_span_longer_than_the_model_accepts_is_not_priced_as_one_shot(table):
    with pytest.raises(UnpricedError):
        price_shot("veo3.1_fast", "1080p", 9, table=table)


def test_a_film_with_an_unpriced_scene_does_not_pretend_to_a_total(table):
    scenes = _mixed_film()
    scenes[2]["model_id"] = "wan3_prime"
    with pytest.raises(UnpricedError):
        plan_film(scenes, table=table)


# --------------------------------------------------------------- measured over documented --


def test_a_measured_balance_drop_becomes_measured_rows(table):
    """966 credits measured for 6 stills and 4 shots: the drop is shared in proportion to
    the published prices, said to be an attribution, and the rows become MEASURED."""
    takes = [{"kind": "still", "model_id": "seedream5_pro", "resolution": "2K", "count": 6}] + [
        {"kind": "motion", "model_id": "seedance2_5", "resolution": "1080p", "seconds": 5}
    ] * 4
    result = attribute_measured_credits(966, takes, table=table, measured_on=READ_ON)

    assert result["quoted_credits"] == 54 + 4 * 5 * 68
    assert result["attribution"] == "proportional"
    rows = {(r.model_id, r.resolution): r for r in result["rows"]}
    motion = rows[("seedance2_5", "1080p")]
    assert motion.provenance == "MEASURED" and motion.date == READ_ON.isoformat()
    assert motion.credits_per_second == pytest.approx(966 * 1360 / 1414 / 20, rel=1e-6)
    still = rows[("seedream5_pro", "2K")]
    assert still.credits_per_image == pytest.approx(966 * 54 / 1414 / 6, rel=1e-6)

    measured = apply_measured(table, result["rows"])
    assert source_label(measured.row("seedance2_5", "1080p"), today=READ_ON) == "măsurat"
    assert measured.row("seedance2_5", "1080p").documented_credits_per_second == 68
    # The documented table itself is untouched: the overlay is a new table.
    assert table.row("seedance2_5", "1080p").provenance == "DOCUMENTED"


def test_one_model_alone_is_attributed_exactly(table):
    takes = [{"kind": "motion", "model_id": "seedance2_5", "resolution": "1080p", "seconds": 5}]
    result = attribute_measured_credits(340, takes, table=table, measured_on=READ_ON)
    assert result["attribution"] == "exact"
    assert result["rows"][0].credits_per_second == 68


def test_the_module_is_pure():
    """No database, no network: the shooting sheet prices a film at zero credits."""
    source = cost_plan.__file__
    text = open(source, encoding="utf-8").read()  # noqa: PTH123 - a plain read of our own file
    for forbidden in ("sqlalchemy", "httpx", "requests", "app.providers"):
        assert forbidden not in text, forbidden
