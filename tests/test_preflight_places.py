"""The preflight speaks in the page's places, and hands the page the rest as data.

Judged NO on 2026-09-25 (W31): the Rularea zilei door read as a console. The preflight told
the Owner to «PUT /economy/budget», to «POST /media/characters/{id}/reference-set», to call
«POST /publishing/channels/<uuid>/publish-policy (director_may_approve_episodes)», and named
STUDIO_* variables and OAuth scopes in the sentences he reads. What is asserted here:

- no sentence the Owner reads (a line's message and detail, the summary) carries a route, a
  settings variable, a scope, a policy field or Google's raw answer, in any studio state the
  preflight has a sentence for;
- every line carries, as data, a stable ``code``, an ``impact`` (blocks / degrades /
  informs / ok), the ``place`` that fixes it from a small fixed vocabulary, and a
  ``technical`` record (routes, settings, scopes, fields, answers) for the page's tooltips;
- the vocabulary is the page's own: every door is a room button in ``frontend/index.html``,
  every settings tab is a section of ``frontend/src/settings.js``, every section anchor exists;
- the technical detail that left the sentences is kept, whole, in ``technical`` — the file
  FFmpeg was found at included, which used to be the render line's detail.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.economy.budget import BudgetCommand, set_budget
from app.economy.prices import PriceCommand, set_price
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.runbook.preflight import (
    IMPACTS,
    PLACES,
    PRICES_PLACE,
    TECHNICAL_KEYS,
    run_preflight,
)
from app.wording import SETTINGS_TABS
from app.youtube.models import YouTubeConnection
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_readiness import give_a_model_vision

ROOT = Path(__file__).resolve().parents[1]
MORNING = datetime(2026, 9, 18, 5, 0, tzinfo=UTC)
READONLY = "https://www.googleapis.com/auth/youtube.readonly"
UPLOAD = "https://www.googleapis.com/auth/youtube.upload"

#: What a sentence for the Owner must never carry. Each one is fine in ``technical``.
CONSOLE = (
    re.compile(r"\b(GET|PUT|POST|DELETE|PATCH) /"),
    re.compile(r"/economy/|/media/characters|/publishing/channels|/reference-set"),
    re.compile(r"\bSTUDIO_[A-Z_]+"),
    re.compile(r"\b[a-z]+_[a-z_]+\b"),  # a settings or policy field: motion_budget_usd, …
    re.compile(r"youtube\.(upload|readonly)|yt-analytics"),
    re.compile(r"invalid_grant|insufficient_scope"),
    re.compile(r"\bSettings\b"),
    re.compile(r"Publicare →|Owner-ului|jetoane"),
    re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"),  # a record's id
    re.compile(r"\d+\.\d+ USD"),  # an amount with the decimal point, not «1,2 USD»
)


def assert_owner_words(text: str, where: str) -> None:
    for pattern in CONSOLE:
        found = pattern.search(text or "")
        assert found is None, (where, found.group(0) if found else "", text)


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "places.credentials.key")


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    return engine


def line(result: dict, name: str) -> dict:
    found = next((c for c in result["checks"] if c["name"] == name), None)
    assert found is not None, name
    return found


def bind(engine, channel_type: str, name: str, scopes: str | None) -> str:
    connection_id = str(uuid4())
    granted = MORNING - timedelta(days=2)
    with Session(engine) as session, session.begin():
        session.add(
            YouTubeConnection(
                id=connection_id,
                name=name,
                client_id="client-id",
                redirect_uri="http://localhost/callback",
                encrypted_secrets="opaque",
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id=f"UC_{connection_id[:8]}",
                remote_channel_title=name,
                channel_snapshot={},
                granted_scopes=scopes,
                connected_at=granted.isoformat(),
                last_checked_at=granted.isoformat(),
                created_at=granted.isoformat(),
            )
        )
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == channel_type)
        )
        channel.credentials_ref = f"youtube_connection:{connection_id}"
    return connection_id


def refuse_token(engine, connection_id: str) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            DomainEvent(
                event_id=str(uuid4()),
                event_type="youtube.token_refresh_failed",
                timestamp=(MORNING - timedelta(hours=1)).isoformat(),
                aggregate_type="youtube_connection",
                aggregate_id=connection_id,
                aggregate_version=1,
                correlation_id=str(uuid4()),
                causation_id=None,
                schema_version=1,
                visibility="OWNER",
                payload={
                    "connection_id": connection_id,
                    "during": "token_refresh",
                    "http_status": 400,
                    "oauth_error": "invalid_grant",
                    "auth_refused": True,
                },
            )
        )


def lock_first_character(engine) -> CharacterBible:
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        rows = session.scalars(select(CharacterBible).order_by(CharacterBible.canonical_name)).all()
        for row in rows:
            row.identity_locks_json = {}
            row.reference_assets_json = {}
        rows[0].identity_locks_json = {"visual": True}
        session.flush()
        session.expunge(rows[0])
        return rows[0]


# ------------------------------------------------------------------ the states said in words


def the_worst_studio(engine, settings, vault) -> dict:
    """Everything the preflight has a failing sentence for, at once."""
    seed_default_channels(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    lock_first_character(engine)
    refuse_token(engine, bind(engine, "MAIN_FACTUAL", "Nexus Curiosity", READONLY))
    bind(engine, "OFFICE_SERIAL", "Serial", f"{READONLY} {UPLOAD}")
    return run_preflight(engine, settings, vault, now=MORNING)


def test_no_sentence_the_owner_reads_is_a_console_line(engine, settings, vault, studio):
    states = [run_preflight(engine, settings, vault, now=MORNING)]
    states.append(the_worst_studio(engine, settings, vault))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
        session.get(OwnerPolicy, 1).environment = "TEST"
    states.append(run_preflight(engine, settings, vault, now=MORNING))

    for result in states:
        assert_owner_words(result["summary"], "summary")
        for check in result["checks"]:
            assert_owner_words(check["message"], f"{check['name']}.message")
            assert_owner_words(check["detail"], f"{check['name']}.detail")


def test_a_bare_studio_says_nothing_technical_either(engine, settings, vault):
    """Nothing configured at all: no workforce verified, no FFmpeg on the path given."""
    seed_initial_workforce(engine)
    settings.ffmpeg_path = None
    result = run_preflight(engine, settings, vault)
    for check in result["checks"]:
        assert_owner_words(check["message"], f"{check['name']}.message")
        assert_owner_words(check["detail"], f"{check['name']}.detail")


# ------------------------------------------------------------------ the fields, on every line


def test_every_line_carries_code_impact_place_and_technical(engine, settings, vault, studio):
    for result in (
        run_preflight(engine, settings, vault, now=MORNING),
        the_worst_studio(engine, settings, vault),
    ):
        for check in result["checks"]:
            name = check["name"]
            assert check["code"].startswith(f"{name}."), check["code"]
            assert re.fullmatch(r"[a-z_]+\.[a-z_]+", check["code"]), check["code"]
            assert check["impact"] in IMPACTS
            expected = (
                "ok"
                if check["ok"]
                else {"BLOCKING": "blocks", "DEGRADING": "degrades", "INFORMATIONAL": "informs"}[
                    check["severity"]
                ]
            )
            assert check["impact"] == expected, name
            if check["ok"]:
                assert check["place"] is None and check["place_label"] is None
                assert check["place_section"] is None
            else:
                assert check["place"] in PLACES, (name, check["place"])
                assert check["place_label"], name
            assert set(check["technical"]) == set(TECHNICAL_KEYS), name
            for key in TECHNICAL_KEYS:
                assert isinstance(check["technical"][key], list), (name, key)


def test_the_places_are_the_pages_own_rooms_tabs_and_sections():
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    settings_js = (ROOT / "frontend" / "src" / "settings.js").read_text(encoding="utf-8")
    for place, label in PLACES.items():
        if place.startswith("settings:"):
            tab = place.split(":", 1)[1]
            words = label.split(" → ", 1)[1]
            assert f"['{tab}', '{words}']" in settings_js, place
        elif place in {"machine", "not_on_page"}:
            continue
        elif place == "autonomy_switch":
            assert 'id="stop-toggle"' in index and ">AUTONOMIE<" in index
        else:
            assert f'id="open-{place}-btn"' in index, place
            assert f'<span class="room-label">{label}</span>' in index, place


def test_where_ffmpeg_was_found_is_a_path_in_the_technical_record(engine, settings, vault, studio):
    render = line(run_preflight(engine, settings, vault), "render_engine")
    assert render["ok"] is True and render["detail"] == ""
    assert render["technical"]["paths"] == [settings.ffmpeg_path]


def test_who_can_see_is_said_by_name_and_the_id_is_data(engine, settings, vault, studio):
    give_a_model_vision(engine)
    vision = line(run_preflight(engine, settings, vault), "vision_capability")
    assert vision["ok"] is True
    assert vision["value"]["agent_name"] in vision["message"]
    assert vision["value"]["agent_id"] not in vision["message"] + vision["detail"]


def test_every_section_a_line_names_is_an_element_of_the_page(engine, settings, vault, studio):
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    result = the_worst_studio(engine, settings, vault)
    sections = {c["place_section"] for c in result["checks"] if c["place_section"]}
    assert sections, "the worst studio names at least the budget's section"
    for section in sections:
        assert f'id="{section}"' in index, section


# ------------------------------------------------------------------ line by line


def test_the_budget_is_set_in_autonomy_settings_and_the_route_is_data(
    engine, settings, vault, studio
):
    budget = line(run_preflight(engine, settings, vault), "spending_budget")
    assert budget["code"] == "spending_budget.none" and budget["impact"] == "degrades"
    assert "Autonomie → Buget și cheltuieli" in budget["message"]
    assert budget["place"] == "autonomy" and budget["place_section"] == "autonomy-budget"
    assert budget["place_label"] == "Autonomie → Buget și cheltuieli"
    assert budget["technical"]["routes"] == ["PUT /economy/budget"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="25"))
    set_now = line(run_preflight(engine, settings, vault), "spending_budget")
    assert set_now["code"] == "spending_budget.set" and set_now["impact"] == "ok"


def test_the_films_the_budget_refuses_name_autonomy_settings_and_keep_the_knobs(
    engine, settings, vault, studio
):
    seed_default_channels(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    # The film's ceiling, enforced before every paid step since 2026-10-02 (MONEY-07).
    settings.film_budget_usd = 12.0
    films = line(run_preflight(engine, settings, vault), "daily_budget_films")
    assert films["code"] == "daily_budget_films.second_film_refused"
    assert "Autonomie → Buget și cheltuieli" in films["message"]
    assert "plafonul unui film" in films["message"]
    assert films["place"] == "autonomy"
    assert "PUT /economy/budget" in films["technical"]["routes"]
    assert "STUDIO_MOTION_BUDGET_USD" in films["technical"]["settings"]
    assert "motion_budget_usd" in films["technical"]["fields"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    none_fit = line(run_preflight(engine, settings, vault), "daily_budget_films")
    assert none_fit["code"] == "daily_budget_films.no_film_fits"

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "TEST"
    later = line(run_preflight(engine, settings, vault), "daily_budget_films")
    assert later["code"] == "daily_budget_films.production_would_refuse"
    assert later["impact"] == "informs"
    assert "STUDIO_MOTION_BUDGET_USD" in later["technical"]["settings"]


def test_a_locked_character_is_fixed_at_its_card_in_the_character_bible(
    engine, settings, vault, studio
):
    character = lock_first_character(engine)
    refs = line(run_preflight(engine, settings, vault), "character_references")
    assert refs["code"] == "character_references.locked_missing"
    assert "Producție media → Character Bible" in refs["message"]
    assert "«Produ setul de referință»" in refs["message"]
    assert refs["place"] == "media" and refs["place_section"] == "media-characters-section"
    assert refs["technical"]["routes"] == [f"POST /media/characters/{character.id}/reference-set"]


def test_the_directors_leave_is_given_in_settings_channels(engine, settings, vault, studio):
    """W34: the page has a switch for the Director's leave in Setări → Canale, so the line
    names it there; until W33 it said «pagina nu are încă un comutator» and had no place."""
    seed_default_channels(engine)
    missing = line(run_preflight(engine, settings, vault), "serial_channel")
    assert missing["code"] == "serial_channel.unbound" and missing["place"] == "publishing"
    assert "Distribuție → Sloturi de canal" in missing["message"]
    assert missing["place_section"] == "channels-list"

    bind(engine, "OFFICE_SERIAL", "Serial", f"{READONLY} {UPLOAD}")
    waiting = line(run_preflight(engine, settings, vault), "serial_channel")
    assert waiting["code"] == "serial_channel.director_may_not_approve"
    assert waiting["impact"] == "informs"
    assert waiting["place"] == "settings:channels"
    assert waiting["place_label"] == "Setări → Canale"
    assert waiting["place_section"] is None
    assert "Setări → Canale" in waiting["message"]
    assert "pagina nu are" not in waiting["message"]
    assert "API" not in waiting["message"]
    with Session(engine) as session:
        serial_id = session.scalar(
            select(ChannelRecord.id).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
    assert waiting["technical"]["routes"] == [
        f"POST /publishing/channels/{serial_id}/publish-policy"
    ]
    assert waiting["technical"]["fields"] == ["director_may_approve_episodes"]
    # The switch writes this channel's policy: the page reads which channel and at which
    # version from the line itself, never by parsing a route.
    assert waiting["value"]["channel_id"] == serial_id
    assert waiting["value"]["policy_version"] == 1


def test_a_studio_with_no_serial_slot_is_told_where_slots_come_from(
    engine, settings, vault, studio
):
    missing = line(run_preflight(engine, settings, vault), "serial_channel")
    assert missing["code"] == "serial_channel.missing" and missing["place"] == "not_on_page"
    assert missing["technical"]["routes"] == ["POST /publishing/channels/seed"]


def test_a_refused_token_keeps_googles_answer_and_the_scopes_as_data(
    engine, settings, vault, studio
):
    seed_default_channels(engine)
    refuse_token(engine, bind(engine, "MAIN_FACTUAL", "Nexus Curiosity", READONLY))
    result = run_preflight(engine, settings, vault, now=MORNING)
    upload = line(result, "youtube_upload_access")
    assert upload["code"] == "youtube_upload_access.upload_not_granted"
    assert upload["impact"] == "blocks"
    assert upload["place"] == "settings:social"
    assert "Setări → Conturi și e-mail" in upload["message"]
    assert "youtube.upload" in upload["technical"]["scopes"]
    assert any("400 invalid_grant" in answer for answer in upload["technical"]["answers"])
    # The scopes Google granted, said as what they let the studio do.
    assert "citirea canalului" in upload["detail"]

    statistics = line(result, "youtube_statistics_access")
    assert statistics["code"] == "youtube_statistics_access.token_refused"
    assert statistics["place"] == "settings:social"
    assert "yt-analytics.readonly" in statistics["technical"]["scopes"]


def test_the_price_line_sends_the_owner_to_autonomy_settingss_price_form(
    engine, settings, vault, studio
):
    """W34: the prices are typed in Autonomie → Prețurile modelelor (section ``autonomy-prices``);
    until W33 the line said the page had no place for them. The models still unpriced, and
    which of their two token prices each lacks, are data the form reads."""
    prices = line(run_preflight(engine, settings, vault), "model_prices")
    assert prices["code"] == "model_prices.unpriced"
    assert prices["place"] == "autonomy"
    assert prices["place_section"] == "autonomy-prices"
    assert prices["place_label"] == "Autonomie → Prețurile modelelor"
    assert "Autonomie → Prețurile modelelor" in prices["message"]
    assert "pagina nu are" not in prices["message"] and "API" not in prices["message"]
    assert "tokenuri" in prices["message"]
    assert prices["technical"]["routes"] == ["PUT /economy/prices"]
    unpriced = prices["value"]["unpriced"]
    assert unpriced, prices["value"]
    for model in unpriced:
        assert set(model) == {"provider_kind", "resource", "missing_units"}
        assert model["provider_kind"] == model["provider_kind"].lower()
        assert model["missing_units"] == ["per_1m_input_tokens", "per_1m_output_tokens"]
    assert prices["value"]["models"] >= len(unpriced)
    assert unpriced == sorted(unpriced, key=lambda m: (m["provider_kind"], m["resource"]))


def test_a_model_priced_on_one_side_is_listed_with_the_side_it_lacks(
    engine, settings, vault, studio
):
    first = line(run_preflight(engine, settings, vault), "model_prices")["value"]["unpriced"][0]
    set_price(
        engine,
        PriceCommand(
            command_id=uuid4(),
            provider_kind=first["provider_kind"],
            resource=first["resource"],
            unit="per_1m_input_tokens",
            usd="0.15",
        ),
    )
    after = line(run_preflight(engine, settings, vault), "model_prices")["value"]["unpriced"]
    same = next(
        m
        for m in after
        if (m["provider_kind"], m["resource"]) == (first["provider_kind"], first["resource"])
    )
    assert same["missing_units"] == ["per_1m_output_tokens"]


def test_every_model_priced_leaves_the_line_passing_with_no_place(engine, settings, vault, studio):
    for model in line(run_preflight(engine, settings, vault), "model_prices")["value"]["unpriced"]:
        for unit in model["missing_units"]:
            set_price(
                engine,
                PriceCommand(
                    command_id=uuid4(),
                    provider_kind=model["provider_kind"],
                    resource=model["resource"],
                    unit=unit,
                    usd="0.1",
                ),
            )
    prices = line(run_preflight(engine, settings, vault), "model_prices")
    assert prices["ok"] is True and prices["code"] == "model_prices.ok"
    assert prices["place"] is None and prices["place_section"] is None
    assert prices["value"]["unpriced"] == []


def test_the_two_new_places_are_in_the_vocabulary():
    assert PLACES["settings:channels"] == "Setări → Canale"
    assert PRICES_PLACE == ("autonomy", "autonomy-prices", "Autonomie → Prețurile modelelor")
    # The Settings tabs are said the way `app.wording` says them for every other sentence.
    for place, label in PLACES.items():
        if place.startswith("settings:"):
            assert label == SETTINGS_TABS[place.split(":", 1)[1]]


def test_the_machine_lines_and_the_settings_lines(engine, settings, vault, monkeypatch):
    seed_initial_workforce(engine)
    settings.ffmpeg_path = None
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    result = run_preflight(engine, settings, vault)
    render = line(result, "render_engine")
    assert render["code"] == "render_engine.ffmpeg_missing" and render["place"] == "machine"
    assert render["technical"]["settings"] == ["STUDIO_FFMPEG_PATH"]
    assert render["technical"]["paths"] == []
    assert line(result, "stop_autonomy")["place"] == "autonomy_switch"
    assert line(result, "stop_autonomy")["code"] == "stop_autonomy.stopped"
    assert line(result, "llm_provider")["place"] == "settings:llm"
    assert line(result, "vision_capability")["place"] == "settings:agents"
    assert line(result, "image_provider")["place"] == "settings:media"
    assert line(result, "image_provider")["code"] == "image_provider.no_selection"
    assert line(result, "research_sources")["place"] == "research"
    assert line(result, "research_sources")["place_section"] == "rs-sources"
    assert line(result, "research_sources")["code"] == "research_sources.no_hosts"
    with Session(engine) as session:
        mode = session.get(OwnerPolicy, 1).autonomy_mode
    assert line(result, "autonomy_mode")["code"] == f"autonomy_mode.{mode.lower()}"


# ------------------------------- PAGE-04: what the next run buys alone, under his rule and mode


def rule(
    engine,
    value: str,
    over: float | None = None,
    *,
    mode: str = "AUTONOMOUS_CEO",
    environment: str = "PRODUCTION",
) -> None:
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.paid_media_approval = value
        policy.paid_media_approval_over_usd = over
        policy.autonomy_mode = mode
        policy.environment = environment


def test_the_ceo_mode_names_the_rule_instead_of_saying_the_day_runs_alone():
    from app.runbook.preflight import MODE_MEANS

    assert "regula" in MODE_MEANS["AUTONOMOUS_CEO"]
    assert "merge singură" not in MODE_MEANS["AUTONOMOUS_CEO"]


def test_an_informational_line_says_what_the_next_run_buys_alone(engine, settings, vault, studio):
    rule(engine, "EVERY_PAID_STEP")
    line_now = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert line_now["severity"] == "INFORMATIONAL" and line_now["ok"] is True
    assert line_now["impact"] == "ok" and line_now["place"] is None
    assert "te întreabă" in line_now["message"]
    assert line_now["value"] == {
        "environment": "PRODUCTION",
        "autonomy_mode": "AUTONOMOUS_CEO",
        "paid_media_approval": "EVERY_PAID_STEP",
        "over_usd": None,
        "daily_budget_usd": None,
    }

    rule(engine, "MODE")
    no_budget = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert "fără un buget zilnic activ" in no_budget["message"]
    assert "nu cumpără nimic singur" in no_budget["message"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    alone = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert "cumpără singur" in alone["message"] and "15,00 USD" in alone["message"]
    assert "controlul clipului" in alone["message"]

    rule(engine, "OVER_USD", 5.0)
    over = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert "cel mult 5,00 USD" in over["message"] and "te întreabă" in over["message"]

    rule(engine, "MODE", mode="MANUAL")
    manual = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert "nu cumpără nimic singur" in manual["message"]

    rule(engine, "MODE", environment="TEST")
    test_env = line(run_preflight(engine, settings, vault, now=MORNING), "paid_media_rule")
    assert "mediul TEST" in test_env["message"]
    for result_line in (line_now, no_budget, alone, over, manual, test_env):
        assert_owner_words(result_line["message"], "paid_media_rule")


def test_the_new_line_is_never_counted_against_the_day(engine, settings, vault, studio):
    rule(engine, "MODE")
    result = run_preflight(engine, settings, vault, now=MORNING)
    assert line(result, "paid_media_rule")["ok"] is True
    assert "paid_media_rule" not in {c["name"] for c in result["checks"] if not c["ok"]}
