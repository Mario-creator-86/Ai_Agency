"""The publishing gate says why in Romanian, and keeps its codes as data.

The Owner's standing rule (2026-09-23): what the studio writes for him to read is Romanian.
Measured on 28ad681, the Distribution door and the register still read the gate in English —
«Global autonomy stop is active», «QC status is MISSING», «Factual provenance unverifiable: no
render job records this asset», «Duplicate publishing prevented; asset already published to
this channel», «Simulated upload: no video exists on any platform.» — and the preflight's
research line printed its codes inside a Romanian sentence («motor de căutare: NONE», «Picate:
www.loc.gov (OTHER)»).

Each test reads one of those sentences as the Owner would and holds two things: the sentence
is Romanian (numbers with a decimal comma, counts agreeing), and the code it used to print is
still there as data — ``reason_codes`` beside ``reasons``, a check's ``data`` beside its
``detail`` — where a page or a person diagnosing it reads it.
"""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from app.media.models import QualityControlReport
from app.models import OwnerPolicy
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    PublishingAssetNotFound,
    PublishingGateError,
    create_publication_intent,
    evaluate_publishing_gate,
    list_channels,
    publish_media_asset,
    seed_default_channels,
)
from app.wording import (
    AUTONOMY_STOPPED,
    error_words,
    host_test_reason,
    qc_status,
    search_engine,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_phase6_publishing import _create_verified_asset_bundle
from test_truthfulness_gates import _register_asset

#: English a sentence for the Owner must not carry. Words, not letters: «public» and «video»
#: are Romanian too, and a product name or an id may pass.
ENGLISH = re.compile(
    r"\b(the|is|of|on|not|found|already|must|claims?|policy|asset|score|below|stop|"
    r"active|prevented|published|referenced|supported|upload|missing|cleared|valid|file|"
    r"bytes|unverifiable|provenance|duplicate|channel|authorises|version|minimum|with|"
    r"none|verify|script|render|private|unlisted)\b",
    re.IGNORECASE,
)

#: Codes the gate keeps as data and must not print in a sentence.
CODES = ("MISSING", "PASSED", "FAILED", "SUPPORTED", "AUTONOMY_", "TEST", "PRODUCTION", "NONE")


def assert_romanian(text: str) -> None:
    assert text, "an empty sentence says nothing"
    found = ENGLISH.findall(text)
    assert not found, (found, text)
    for code in CODES:
        assert code not in text, (code, text)


def _channel(engine) -> str:
    seed_default_channels(engine)
    return list_channels(engine)[0]["id"]


def _check(verdict: dict, name: str) -> dict:
    return next(c for c in verdict["checks"] if c["check_name"] == name)


def _stop(engine, stopped: bool) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = stopped


# ----------------------------------------------------------------------------- the words


@pytest.mark.parametrize(
    ("code", "said"),
    [
        ("PASSED", "a trecut"),
        ("FAILED", "nu a trecut"),
        ("MISSING", "lipsește"),
        ("SOMETHING_NEW", "something new"),
    ],
)
def test_the_quality_verdict_is_said_as_the_glossary_says_it(code, said):
    assert qc_status(code) == said


@pytest.mark.parametrize(
    ("code", "said"),
    [
        ("HTTP_403", "a refuzat studioul (403)"),
        ("SCRIPT_ONLY", "nu arată nimic fără JavaScript"),
        ("NETWORK", "nu a răspuns"),
        ("OTHER", "nu a răspuns cu nimic utilizabil"),
    ],
)
def test_a_site_that_cannot_be_read_is_said_as_the_sources_list_says_it(code, said):
    assert host_test_reason(code) == said


def test_the_search_engine_is_said_as_a_fact_not_a_code():
    assert search_engine("VERIFIED") == "un motor de căutare verificat"
    assert search_engine("NONE") == "niciun motor de căutare verificat"


# ----------------------------------------------------------------------------- a passing gate


def test_a_passing_gate_says_each_check_in_romanian(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert verdict["eligible"] is True
    assert verdict["reasons"] == [] and verdict["reason_codes"] == []
    for check in verdict["checks"]:
        assert_romanian(check["detail"])
    assert _check(verdict, "AUTONOMY_GATE")["detail"] == "Autonomia studioului este pornită."
    qc = _check(verdict, "QC_GATE")
    # A decimal comma, and the score itself as data.
    assert "0,96" in qc["detail"] and qc["data"]["qc_score"] == pytest.approx(0.96)
    assert qc["data"]["qc_status"] == "PASSED"
    size = bundle["video_file"].stat().st_size
    disk = _check(verdict, "MEDIA_ASSET_ON_DISK")
    assert f"{size} de octeți" in disk["detail"] and disk["data"]["bytes"] == size
    factual = _check(verdict, "FACTUAL_INTEGRITY_GATE")
    assert factual["detail"] == "Afirmația citată de scenariu este verificată."
    assert factual["data"]["claim_ids"] == [bundle["claim_id"]]


# ----------------------------------------------------------------------------- refusals


def test_the_autonomy_stop_is_said_in_romanian_and_kept_as_a_code(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    _stop(engine, True)

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert verdict["eligible"] is False
    assert verdict["reasons"] == ["Autonomia studioului este oprită"]
    assert verdict["reason_codes"] == ["AUTONOMY_STOPPED"]
    gate = _check(verdict, "AUTONOMY_GATE")
    assert gate["passed"] is False and gate["detail"] == AUTONOMY_STOPPED
    assert_romanian(gate["detail"])


def test_a_missing_asset_is_said_in_romanian_with_its_id_as_data(engine):
    channel_id = _channel(engine)
    missing = str(uuid4())

    verdict = evaluate_publishing_gate(engine, missing, channel_id)

    gate = _check(verdict, "MEDIA_ASSET_EXISTS")
    assert gate["passed"] is False and gate["data"]["media_asset_id"] == missing
    assert_romanian(gate["detail"])
    assert "MEDIA_ASSET_MISSING" in verdict["reason_codes"]
    for reason in verdict["reasons"]:
        assert_romanian(reason)
    assert len(verdict["reasons"]) == len(verdict["reason_codes"])


def test_a_file_gone_from_disk_is_said_in_romanian(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    bundle["video_file"].unlink()

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    gate = _check(verdict, "MEDIA_ASSET_ON_DISK")
    assert gate["passed"] is False
    assert "lipsește de pe disc" in gate["detail"]
    assert gate["data"]["path"] == str(bundle["video_file"])
    assert "MEDIA_FILE_MISSING" in verdict["reason_codes"]


def test_a_missing_quality_report_reads_as_the_glossary_says_it(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    with Session(engine) as session, session.begin():
        for report in session.scalars(select(QualityControlReport)):
            session.delete(report)

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert verdict["reasons"] == ["Controlul calității: lipsește"]
    assert verdict["reason_codes"] == ["QC_NOT_PASSED"]
    gate = _check(verdict, "QC_GATE")
    assert gate["data"]["qc_status"] == "MISSING"
    assert_romanian(gate["detail"])


def test_a_failed_quality_report_reads_as_not_passed(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path, qc_passed=False)

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert "Controlul calității: nu a trecut" in verdict["reasons"]
    gate = _check(verdict, "QC_GATE")
    assert gate["data"]["qc_status"] == "FAILED"
    assert_romanian(gate["detail"])


def test_a_score_under_the_minimum_is_said_with_a_decimal_comma(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.scalars(select(QualityControlReport)).first().score = 0.5

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    assert verdict["reason_codes"] == ["QC_SCORE_BELOW_MINIMUM"]
    (reason,) = verdict["reasons"]
    assert "0,50" in reason and "sub minimul" in reason
    assert_romanian(reason)
    gate = _check(verdict, "QC_GATE")
    assert gate["data"]["qc_score"] == pytest.approx(0.5)
    assert gate["data"]["qc_minimum"] > 0.5


def test_a_film_with_no_provenance_is_refused_in_romanian(engine, tmp_path):
    channel_id = _channel(engine)
    video = tmp_path / "orphan.mp4"
    video.write_bytes(b"\x00" * 2048)
    asset_id = _register_asset(engine, video)
    _stop(engine, False)

    verdict = evaluate_publishing_gate(engine, asset_id, channel_id)

    gate = _check(verdict, "FACTUAL_INTEGRITY_GATE")
    assert gate["passed"] is False
    assert "nicio randare nu a produs acest material" in gate["detail"]
    assert gate["data"]["missing"] == "NO_RENDER_JOB"
    assert_romanian(gate["detail"])
    index = verdict["reason_codes"].index("FACTUAL_PROVENANCE_UNKNOWN")
    assert verdict["reasons"][index] == (
        "Proveniența factuală nu poate fi verificată: nicio randare nu a produs acest material"
    )


def test_a_refuted_claim_is_counted_in_words_and_named_by_id_as_data(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path, refuted_claim=True)

    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)

    gate = _check(verdict, "FACTUAL_INTEGRITY_GATE")
    assert gate["passed"] is False
    assert gate["data"]["unverified_claim_ids"] == [bundle["claim_id"]]
    assert gate["data"]["missing_claim_ids"] == []
    assert "1 afirmație neverificată sau infirmată" in gate["detail"]
    assert bundle["claim_id"] not in gate["detail"]
    assert_romanian(gate["detail"])
    assert "CLAIMS_NOT_SUPPORTED" in verdict["reason_codes"]


def test_a_duplicate_is_said_in_romanian_with_the_video_it_would_repeat(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel_id,
        title="JWST Deep Field",
        description="",
        tags=[],
        provider=DeterministicPublishingAdapter(),
    )

    with pytest.raises(PublishingGateError) as refused:
        publish_media_asset(
            engine,
            media_asset_id=bundle["asset_id"],
            channel_id=channel_id,
            title="Again",
            description="",
            tags=[],
            provider=DeterministicPublishingAdapter(),
        )

    message = refused.value.message
    assert message.startswith("Poarta de publicare a refuzat filmul: ")
    assert "Publicare dublă oprită" in message
    assert refused.value.reasons == ["Publicare dublă oprită: materialul este deja pe acest canal"]
    # The day's stage says the gate's own sentence, not the class's generic words.
    assert error_words(refused.value) == message.rstrip(".")
    with Session(engine) as session:
        blocked = session.scalars(
            select(PublicationRecord).where(PublicationRecord.status == "BLOCKED_GATE")
        ).one()
    assert blocked.error_detail == "Publicare dublă oprită: materialul este deja pe acest canal"
    verdict = evaluate_publishing_gate(engine, bundle["asset_id"], channel_id)
    gate = _check(verdict, "DUPLICATE_PROTECTION_GATE")
    assert published["remote_video_id"] in gate["detail"]
    assert gate["data"]["remote_video_id"] == published["remote_video_id"]
    assert verdict["reason_codes"] == ["DUPLICATE_ASSET"]


def test_a_visibility_the_policy_does_not_allow_is_said_in_words(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    verdict = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel_id, privacy_status="unlisted", policy_version=1
    )

    assert verdict["reason_codes"] == ["POLICY_VISIBILITY_EXCEEDED"]
    (reason,) = verdict["reasons"]
    assert reason == "Versiunea 1 a politicii canalului autorizează un film privat, nu nelistat"
    gate = _check(verdict, "POLICY_AUTHORISATION_GATE")
    assert_romanian(gate["detail"])
    assert gate["data"] == {
        "requested": "unlisted",
        "authorised": "private",
        "policy_version": 1,
        "current_policy_version": 1,
        "environment": "TEST",
    }


def test_a_visible_film_without_a_policy_stamp_is_said_in_words(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    verdict = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel_id, privacy_status="public"
    )

    assert verdict["reason_codes"] == ["POLICY_NO_VERSION"]
    assert verdict["reasons"] == [
        "Nicio versiune a politicii de publicare nu autorizează un film public"
    ]
    assert_romanian(_check(verdict, "POLICY_AUTHORISATION_GATE")["detail"])


def test_a_stale_policy_stamp_is_said_in_words(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    verdict = evaluate_publishing_gate(
        engine, bundle["asset_id"], channel_id, privacy_status="unlisted", policy_version=7
    )

    assert verdict["reason_codes"] == ["POLICY_VERSION_STALE"]
    assert verdict["reasons"] == [
        "Politica de publicare s-a schimbat de la versiunea 7; canalul este la versiunea 1"
    ]


def test_an_unknown_asset_or_channel_is_refused_in_romanian(engine):
    channel_id = _channel(engine)
    with pytest.raises(PublishingAssetNotFound) as no_asset:
        create_publication_intent(
            engine, channel_id, str(uuid4()), "t", "", [], "private", None, str(uuid4())
        )
    assert_romanian(no_asset.value.message)
    for reason in no_asset.value.reasons:
        assert_romanian(reason)


# ----------------------------------------------------------------------------- after the gate


def test_a_simulated_upload_says_so_in_romanian(engine, tmp_path):
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path)

    published = publish_media_asset(
        engine,
        media_asset_id=bundle["asset_id"],
        channel_id=channel_id,
        title="JWST Deep Field",
        description="",
        tags=[],
        provider=DeterministicPublishingAdapter(),
    )

    assert published["status"] == "PUBLISHED_SIMULATED"
    assert published["error_detail"] == (
        "Încărcare simulată: niciun video nu există pe vreo platformă."
    )


def test_the_api_carries_the_sentences_and_the_codes_side_by_side(
    client, headers, engine, tmp_path
):
    """The Distribution door reads the gate through the API: the response model must keep the
    codes (``reason_codes``, each check's ``data``) and the 422 of a refused intent must say
    why in Romanian."""
    channel_id = _channel(engine)
    bundle = _create_verified_asset_bundle(engine, tmp_path, qc_passed=False)

    gate = client.get(
        f"/api/v1/publishing/gate/evaluate/{bundle['asset_id']}/{channel_id}", headers=headers
    ).json()
    assert gate["reason_codes"] == ["QC_NOT_PASSED"]
    assert gate["reasons"] == ["Controlul calității: nu a trecut"]
    assert _check(gate, "QC_GATE")["data"]["qc_status"] == "FAILED"

    refused = client.post(
        "/api/v1/publishing/publications/intent",
        json={
            "command_id": str(uuid4()),
            "channel_id": channel_id,
            "media_asset_id": bundle["asset_id"],
            "title": "JWST",
            "description": "",
            "tags": [],
            "privacy_status": "private",
        },
        headers=headers,
    )
    assert refused.status_code == 422
    body = refused.json()["detail"]
    assert body["message"] == (
        "Poarta de publicare a refuzat filmul: Controlul calității: nu a trecut."
    )
    assert body["reasons"] == ["Controlul calității: nu a trecut"]
