"""The preflight's image and voice lines when a chosen, verified connection gives no generator.

W31, the release judge, on a copy of the Owner's database: the copy keeps his connections but
not their keys, so the connection is chosen and verified (readiness READY, whose sentence is
empty) while no adapter can be built. The line then read « Până atunci randările folosesc
substitute, …»: a sentence with its subject missing, starting with a space. The same happens in
his studio whenever a stored key cannot be used. The line now says what is wrong.
"""

from __future__ import annotations

import shutil
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.integrations.models import Integration, ServiceSelection
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.runbook.preflight import run_preflight
from app.services import append_event
from app.wording import MEDIA_KEY_UNUSABLE
from sqlalchemy.orm import Session


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "media-key.credentials.key")


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    return engine


def choose(engine, vault, kind: str, purpose: str, config: dict, secrets: dict) -> str:
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind=kind,
                name="Imagini OpenAI",
                config=config,
                encrypted_secrets=vault.encrypt(secrets),
                secret_fields=sorted(secrets),
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.flush()
        session.add(
            ServiceSelection(
                purpose=purpose, integration_id=identifier, version=1, event_id=event.event_id
            )
        )
    return identifier


def image_line(result: dict) -> dict:
    return next(c for c in result["checks"] if c["name"] == "image_provider")


def test_a_verified_choice_whose_key_cannot_be_used_says_so(engine, settings, vault, studio):
    choose(engine, vault, "openai_media", "image", {"model": "gpt-image-1"}, {})

    line = image_line(run_preflight(engine, settings, vault))

    assert line["ok"] is False
    assert line["message"] == line["message"].strip(), "the line starts with its subject"
    assert line["message"].startswith(
        MEDIA_KEY_UNUSABLE.format(name="Imagini OpenAI", purpose="Imagini")
    )
    assert line["message"].endswith(
        "Până atunci randările folosesc substitute, iar QC le blochează de la publicare."
    )
    assert line["value"] == "READY", "the readiness code is kept as it was"


def test_an_unchosen_image_service_keeps_its_own_sentence(engine, settings, vault, studio):
    line = image_line(run_preflight(engine, settings, vault))

    assert line["ok"] is False
    assert line["message"].startswith("Niciun serviciu ales pentru Imagini.")
    assert line["value"] == "NO_SELECTION"


def test_a_usable_choice_passes_with_the_generator_named(engine, settings, vault, studio):
    choose(engine, vault, "openai_media", "image", {"model": "gpt-image-1"}, {"api_key": "k"})

    line = image_line(run_preflight(engine, settings, vault))

    assert line["ok"] is True
    assert line["message"].startswith("Imagini: ")
