"""What the preflight tells the Owner before he spends anything.

The five checks here are not about whether the day can start — the runbook's own tests cover
that — but about whether the day that starts produces a film worth having. Each one names a
thing only the Owner can supply, and each one was measured as missing on the live copy: no
budget at all, so the reservation holds money it has no reason to refuse; no price for the
models the employees think with, so 391 agent runs recorded no cost; no employee whose model
declares vision, so the picture and character gates stand down on every film; five reference
slots null in every studio that has ever run; and a serial channel whose Director has no
leave to approve an episode.

None of them may fail the day. A missing thing the Owner deliberately chose — no budget while
the studio is in TEST, no serial channel — is a line he reads, never a refusal he has to work
around, so every assertion below also checks that the verdict did not turn BLOCKED.
"""

from __future__ import annotations

import secrets
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.models import Agent, Capability, ModelCapability, ModelRecord, ProviderRecord
from app.agents.services import seed_initial_workforce
from app.economy.budget import BudgetCommand, set_budget
from app.economy.prices import PriceCommand, set_price
from app.integrations.vault import CredentialVault
from app.media.models import CharacterBible, MediaAsset
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.runbook.preflight import DEGRADING, INFORMATIONAL, run_preflight
from app.services import utc_now
from app.youtube.models import YouTubeConnection
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "readiness.credentials.key")


@pytest.fixture
def studio(engine, settings):
    """A studio the Owner has started, with an encoder named so the run is observable.

    The same fixture the runbook tests use: a fresh studio ships with the STOP gate closed,
    and every test here is about what the preflight says *after* he opened it.
    """
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.scalars(select(ModelRecord)).first().is_available = True
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    return engine


def check(engine, settings, vault, name: str) -> dict:
    """One check out of a whole preflight, so every assertion runs the real thing."""
    result = run_preflight(engine, settings, vault)
    found = next((c for c in result["checks"] if c["name"] == name), None)
    assert found is not None, f"the preflight has no check named {name}"
    assert found["message"], f"{name} reported nothing"
    # None of these five may stop the day: they name what the Owner has not supplied yet,
    # and half of what they name is a choice of his rather than a fault.
    assert name not in result["blocking_failures"]
    assert result["status"] != "BLOCKED", result["blocking_failures"]
    return found


# ---------------------------------------------------------------------------
# 1. A budget exists at all
# ---------------------------------------------------------------------------


def test_the_preflight_says_when_no_budget_has_been_set(engine, settings, vault, studio):
    """With no budget the reservation holds a film's money and has nothing to refuse it by."""
    empty = check(engine, settings, vault, "spending_budget")

    assert empty["ok"] is False and empty["severity"] == DEGRADING
    assert "Niciun buget activ" in empty["message"]
    # The message names the one route that sets one; nobody else can.
    assert "PUT /economy/budget" in empty["message"]

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="25"))

    now_set = check(engine, settings, vault, "spending_budget")
    assert now_set["ok"] is True and now_set["severity"] == DEGRADING
    assert "DAILY" in now_set["detail"] and "25" in now_set["detail"]


# ---------------------------------------------------------------------------
# 2. The models the day will run have prices
# ---------------------------------------------------------------------------


def agent_models(engine) -> list[tuple[str, str]]:
    """(provider kind, model name) for every employee that can actually be run."""
    with Session(engine) as session:
        return [
            (str(kind).lower(), str(model))
            for kind, model in session.execute(
                select(ProviderRecord.provider_type, ModelRecord.model_name)
                .select_from(Agent)
                .join(ModelRecord, ModelRecord.id == Agent.model_id)
                .join(ProviderRecord, ProviderRecord.id == ModelRecord.provider_id)
                .where(Agent.lifecycle == "ACTIVE")
            ).all()
        ]


def test_the_preflight_says_which_kinds_of_model_have_no_price(engine, settings, vault, studio):
    """Without a price an agent run records no cost, and the books see a fraction of the day.

    The check never invents one: it names the provider kinds whose models are unpriced and
    the route the Owner types his own plan into.
    """
    kinds = {kind for kind, _ in agent_models(engine)}
    assert kinds, "the seeded workforce should run on at least one provider kind"

    unpriced = check(engine, settings, vault, "model_prices")
    assert unpriced["ok"] is False and unpriced["severity"] == DEGRADING
    for kind in kinds:
        assert kind in unpriced["message"]
    assert "PUT /economy/prices" in unpriced["message"]
    assert "0 USD" not in unpriced["message"] and "0 USD" not in unpriced["detail"]

    for kind in kinds:
        for unit in ("per_1m_input_tokens", "per_1m_output_tokens"):
            set_price(
                engine,
                PriceCommand(
                    command_id=uuid4(),
                    provider_kind=kind,
                    # "*" prices every resource of the kind that has no row of its own,
                    # which is how the Owner prices a plan rather than a model list.
                    resource="*",
                    unit=unit,
                    usd="0.5",
                ),
            )

    priced = check(engine, settings, vault, "model_prices")
    assert priced["ok"] is True
    assert "0" not in priced["message"].split()[0]


# ---------------------------------------------------------------------------
# 3. Somebody in the studio can see
# ---------------------------------------------------------------------------


def give_a_model_vision(engine) -> None:
    with Session(engine) as session, session.begin():
        capability = session.scalars(select(Capability).where(Capability.name == "vision")).first()
        if capability is None:
            capability = Capability(
                id=str(uuid4()), name="vision", description="Reads an image and answers about it"
            )
            session.add(capability)
            session.flush()
        model_id = session.scalars(
            select(Agent.model_id).where(Agent.lifecycle == "ACTIVE")
        ).first()
        session.add(
            ModelCapability(
                model_id=model_id, capability_id=capability.id, confidence="DECLARED_BY_PROVIDER"
            )
        )


def test_the_preflight_says_when_nobody_in_the_studio_can_see(engine, settings, vault, studio):
    """With no seeing model the picture and character gates stand down on every film, so a
    film of blank fields would pass every automatic check. The Owner has no other place that
    tells him, and the message says exactly that consequence."""
    blind = check(engine, settings, vault, "vision_capability")

    assert blind["ok"] is False and blind["severity"] == DEGRADING
    assert "vedere" in blind["message"]
    assert "câmpuri goale" in blind["message"]

    give_a_model_vision(engine)

    seeing = check(engine, settings, vault, "vision_capability")
    assert seeing["ok"] is True
    assert seeing["detail"], "the line should name who can look"


# ---------------------------------------------------------------------------
# 4. The characters that matter have reference pictures
# ---------------------------------------------------------------------------


def stored_reference(engine, tmp_path: Path) -> str:
    """A MediaAsset whose bytes are actually on disk, as the reference route writes one."""
    path = tmp_path / f"{uuid4()}.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="IMAGE",
                uri_or_path=str(path),
                file_size_bytes=path.stat().st_size,
                mime_type="image/png",
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
            )
        )
    return asset_id


def lock_one_character(engine, *, locked: bool, portrait: str | None = None) -> str:
    with Session(engine) as session, session.begin():
        rows = session.scalars(select(CharacterBible).order_by(CharacterBible.canonical_name)).all()
        for row in rows:
            row.identity_locks_json = {}
            row.reference_assets_json = {}
        first = rows[0]
        first.identity_locks_json = {"visual": True} if locked else {}
        first.reference_assets_json = {"portrait": portrait} if portrait else {}
        return first.canonical_name


def test_a_locked_character_without_a_reference_is_a_blocked_day_he_can_prevent(
    engine, settings, vault, studio, tmp_path
):
    """A locked character with no readable reference refuses its film before the first scene.
    That is a day lost to something he could have produced the evening before, so the line is
    DEGRADING and names him."""
    seed_default_character_bibles(engine)
    name = lock_one_character(engine, locked=True)

    missing = check(engine, settings, vault, "character_references")
    assert missing["ok"] is False and missing["severity"] == DEGRADING
    assert name in missing["message"]
    assert "/reference-set" in missing["message"]

    lock_one_character(engine, locked=True, portrait=stored_reference(engine, tmp_path))

    # The other seeded characters are still bare, and honestly reported as such — but no
    # locked one is, so nothing refuses a film any more and the line stops degrading the day.
    supplied = check(engine, settings, vault, "character_references")
    assert supplied["severity"] == INFORMATIONAL
    assert (
        "character_references" not in run_preflight(engine, settings, vault)["degrading_failures"]
    )


def test_an_unlocked_character_without_a_reference_is_only_a_line_he_reads(
    engine, settings, vault, studio
):
    """Nothing refuses a film for it: the still is drawn from the prompt, as it always was.
    So the severity is informational, and the verdict is the same with and without it."""
    seed_default_character_bibles(engine)
    lock_one_character(engine, locked=False)

    unlocked = check(engine, settings, vault, "character_references")

    assert unlocked["severity"] == INFORMATIONAL
    assert unlocked["ok"] is False
    assert "invenție nouă" in unlocked["message"]
    assert (
        "character_references" not in run_preflight(engine, settings, vault)["degrading_failures"]
    )


def test_a_reference_row_whose_file_is_gone_is_not_a_reference(
    engine, settings, vault, studio, tmp_path
):
    """The slot looks filled in the database and the film still has nothing to be drawn from."""
    seed_default_character_bibles(engine)
    asset_id = stored_reference(engine, tmp_path)
    lock_one_character(engine, locked=True, portrait=asset_id)
    with Session(engine) as session:
        Path(session.get(MediaAsset, asset_id).uri_or_path).unlink()

    gone = check(engine, settings, vault, "character_references")

    assert gone["ok"] is False and gone["severity"] == DEGRADING


# ---------------------------------------------------------------------------
# 5. The serial can reach its channel
# ---------------------------------------------------------------------------


def connect_and_bind_the_serial(engine) -> str:
    connection_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            YouTubeConnection(
                id=connection_id,
                name="Serial",
                client_id="client-id",
                redirect_uri="http://localhost/callback",
                encrypted_secrets="opaque",
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id=f"UC_{connection_id[:8]}",
                remote_channel_title="Office Serial",
                channel_snapshot={},
                created_at=utc_now(),
            )
        )
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "OFFICE_SERIAL")
        )
        channel.credentials_ref = f"youtube_connection:{connection_id}"
        return channel.id


def test_the_preflight_says_whether_the_serial_can_reach_its_channel(
    engine, settings, vault, studio
):
    """Without the leave every episode waits for him, which is his right and not autonomy —
    so the line names the command and never fails the day."""
    seed_default_channels(engine)

    unbound = check(engine, settings, vault, "serial_channel")
    assert unbound["ok"] is False and unbound["severity"] == INFORMATIONAL

    channel_id = connect_and_bind_the_serial(engine)

    waiting = check(engine, settings, vault, "serial_channel")
    assert waiting["ok"] is False and waiting["severity"] == INFORMATIONAL
    assert "director_may_approve_episodes" in waiting["message"]
    assert f"/publishing/channels/{channel_id}/publish-policy" in waiting["message"]

    with Session(engine) as session, session.begin():
        session.get(ChannelRecord, channel_id).director_may_approve_episodes = True

    granted = check(engine, settings, vault, "serial_channel")
    assert granted["ok"] is True
    assert "serial_channel" not in run_preflight(engine, settings, vault)["degrading_failures"]


def test_a_studio_with_no_serial_channel_at_all_is_told_so_and_not_refused(
    engine, settings, vault, studio
):
    """A studio that has not seeded its channels has no OFFICE_SERIAL row; that is a sentence
    to read, not a fault to repair before the day may run."""
    line = check(engine, settings, vault, "serial_channel")

    assert line["ok"] is False and line["severity"] == INFORMATIONAL
    assert "OFFICE_SERIAL" in line["message"]


# ---------------------------------------------------------------------------
# The five together change nothing about what stops a day
# ---------------------------------------------------------------------------


def test_the_new_checks_never_add_a_blocking_failure(engine, settings, vault):
    """A studio with nothing configured reports exactly the blocking failures it did before.

    Everything the five new checks look at is missing here — no budget, no price, no seeing
    model, no character, no channel — and the list of things that stop the day is unchanged.
    """
    seed_initial_workforce(engine)
    settings.ffmpeg_path = "ffmpeg-test-stub"

    result = run_preflight(engine, settings, vault)

    assert result["blocking_failures"] == ["stop_autonomy", "llm_provider"]
    for name in (
        "spending_budget",
        "model_prices",
        "vision_capability",
        "character_references",
        "serial_channel",
    ):
        assert name in {c["name"] for c in result["checks"]}
        assert name not in result["blocking_failures"]


# ---------------------------------------------------------------------------
# The clock on the Owner's answer is configuration, not a constant
# ---------------------------------------------------------------------------


def test_how_long_a_question_stands_is_a_setting_the_owner_can_change(engine, monkeypatch):
    """One number decides three things: how long an unanswered question stands, how long a
    refusal keeps the studio from asking again, and how long a yes can be spent. It was a
    module constant in `services.py`, where the Owner could not reach it; it is
    `approval_expires_after_hours` in `config.py` now, and the behaviour is unchanged — a day,
    so his morning is the natural answer.
    """
    from app import services
    from app.config import Settings

    assert not hasattr(services, "APPROVAL_EXPIRES_AFTER_HOURS")
    field = Settings.model_fields["approval_expires_after_hours"]
    assert field.default == 24

    monkeypatch.setattr(services, "approval_expires_after_hours", lambda: 2)
    with Session(engine) as session, session.begin():
        request = services.request_approval(
            session, "publishing.public_publish", "T3", "director", subject="film-1"
        )
        stands = datetime.fromisoformat(request.expires_at) - datetime.now(UTC)

    assert timedelta(hours=1, minutes=55) < stands <= timedelta(hours=2)


def test_the_expiry_setting_refuses_a_number_that_would_break_the_rule_it_serves():
    """Zero hours would expire a question before the Owner could read it; a month would let a
    yes be spent long after the film it was asked about. One hour to a week."""
    from app.config import Settings

    for hours in (0, 169):
        with pytest.raises(ValidationError):
            Settings(
                _env_file=None,
                owner_token=secrets.token_urlsafe(48),
                approval_expires_after_hours=hours,
            )
