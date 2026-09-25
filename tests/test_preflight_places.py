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
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.runbook.preflight import (
    IMPACTS,
    PLACES,
    TECHNICAL_KEYS,
    run_preflight,
)
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


def test_the_budget_is_set_in_the_treasury_and_the_route_is_data(engine, settings, vault, studio):
    budget = line(run_preflight(engine, settings, vault), "spending_budget")
    assert budget["code"] == "spending_budget.none" and budget["impact"] == "degrades"
    assert "Trezorerie → Buget și cheltuieli" in budget["message"]
    assert budget["place"] == "treasury" and budget["place_section"] == "tr-budget"
    assert budget["place_label"] == "Trezorerie → Buget și cheltuieli"
    assert budget["technical"]["routes"] == ["PUT /economy/budget"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="25"))
    set_now = line(run_preflight(engine, settings, vault), "spending_budget")
    assert set_now["code"] == "spending_budget.set" and set_now["impact"] == "ok"


def test_the_films_the_budget_refuses_name_the_treasury_and_keep_the_knobs(
    engine, settings, vault, studio
):
    seed_default_channels(engine)
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    films = line(run_preflight(engine, settings, vault), "daily_budget_films")
    assert films["code"] == "daily_budget_films.second_film_refused"
    assert "Trezorerie → Buget și cheltuieli" in films["message"]
    assert "plafonul de mișcare" in films["message"]
    assert films["place"] == "treasury"
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


def test_the_directors_leave_is_said_honestly_as_not_yet_on_the_page(
    engine, settings, vault, studio
):
    seed_default_channels(engine)
    missing = line(run_preflight(engine, settings, vault), "serial_channel")
    assert missing["code"] == "serial_channel.unbound" and missing["place"] == "publishing"
    assert "Distribuție → Sloturi de canal" in missing["message"]
    assert missing["place_section"] == "channels-list"

    bind(engine, "OFFICE_SERIAL", "Serial", f"{READONLY} {UPLOAD}")
    waiting = line(run_preflight(engine, settings, vault), "serial_channel")
    assert waiting["code"] == "serial_channel.director_may_not_approve"
    assert waiting["impact"] == "informs"
    # No switch for it exists on the page; the line says so rather than naming a place that
    # has nothing to press.
    assert waiting["place"] == "not_on_page"
    assert "pagina nu are încă" in waiting["message"]
    with Session(engine) as session:
        serial_id = session.scalar(
            select(ChannelRecord.id).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
    assert waiting["technical"]["routes"] == [
        f"POST /publishing/channels/{serial_id}/publish-policy"
    ]
    assert waiting["technical"]["fields"] == ["director_may_approve_episodes"]


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


def test_the_price_line_says_there_is_no_place_for_prices_on_the_page_yet(
    engine, settings, vault, studio
):
    prices = line(run_preflight(engine, settings, vault), "model_prices")
    assert prices["code"] == "model_prices.unpriced"
    assert prices["place"] == "not_on_page"
    assert "tokenuri" in prices["message"]
    assert prices["technical"]["routes"] == ["PUT /economy/prices"]


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
