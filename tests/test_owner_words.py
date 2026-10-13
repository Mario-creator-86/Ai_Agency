"""The studio's own sentences are Romanian, with the codes said as words.

The Owner's standing rule: what the studio writes for him to read is Romanian. Measured on the
release candidate (c9c846a, 2026-09-24), the backend's sentences still carried the record's
codes and English: «1 bugete active: DAILY 15 USD (OK)», «Modul de autonomie este
AUTONOMOUS_CEO», «fiecare episod rămâne DRAFT», «Gâtuire la APPROVAL: 29 în așteptare»,
a STATUS letter titled «publish: COMPLETED — …», growth reasons in English («1 measured films;
a baseline needs 3»), and a stage whose reason was the database driver's own text
(«OperationalError: (sqlite3.OperationalError) database is locked [SQL: UPDATE agent …]»).

Each test below reads one of those sentences as the Owner would and holds two things: the
sentence is Romanian with its numbers agreeing, and the code it used to print is still in the
structured field beside it, where a page or a person diagnosing it reads it.

And one behaviour the register had wrong: resuming an employee who is already at work recorded
an «agent.resumed» that never happened. A change that changes nothing is refused (409), with a
Romanian reason, and writes no event.
"""

from __future__ import annotations

import shutil
import sqlite3
from uuid import uuid4

import pytest
from app.agents.command import findings
from app.agents.director import file_stage_reports
from app.agents.models import Agent, AgentMessage, ModelRecord
from app.agents.services import (
    AgentLifecycleRefused,
    pause_agent,
    resume_agent,
    seed_initial_workforce,
)
from app.analytics.performance import channel_baselines, growth_diagnosis
from app.economy.budget import BudgetCommand, set_budget
from app.integrations.vault import CredentialVault
from app.models import DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.runbook.preflight import run_preflight
from app.runbook.services import (
    COMPLETED,
    FAILED,
    STAGES,
    execute_daily_run,
    run_summary,
)
from app.services import utc_now
from app.wording import count, error_fields, error_words, stage_name
from app.youtube.models import YouTubeConnection
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

#: The codes a sentence for the Owner must not print. Each is fine in a structured field.
CODES = (
    "DAILY",
    "MONTHLY",
    "AUTONOMOUS_CEO",
    "SUPERVISED",
    "DRAFT",
    "APPROVAL",
    "COMPLETED",
    "OFFICE_SERIAL",
    "OperationalError",
    "RuntimeError",
    "post_run",
    "script_and_storyboard",
    "edit_and_qc",
)


def assert_no_codes(sentence: str) -> None:
    for code in CODES:
        assert code not in sentence, (code, sentence)


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(tmp_path / "words.credentials.key")


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        session.scalars(select(ModelRecord)).first().is_available = True
    settings.ffmpeg_path = settings.ffmpeg_path or shutil.which("ffmpeg") or "ffmpeg-test-stub"
    settings.stage_retry_attempts = 0
    return engine


def preflight_line(engine, settings, vault, name: str) -> dict:
    result = run_preflight(engine, settings, vault)
    return next(c for c in result["checks"] if c["name"] == name)


# ----------------------------------------------------------------------------- counting


@pytest.mark.parametrize(
    ("n", "said"),
    [
        (0, "0 bugete active"),
        (1, "1 buget activ"),
        (2, "2 bugete active"),
        (19, "19 bugete active"),
        (20, "20 de bugete active"),
        (21, "21 de bugete active"),
        (100, "100 de bugete active"),
        (101, "101 bugete active"),
        (119, "119 bugete active"),
        (120, "120 de bugete active"),
    ],
)
def test_a_number_agrees_with_its_noun_as_romanian_counts(n, said):
    assert count(n, "buget activ", "bugete active") == said


def test_a_stage_is_named_as_the_register_names_it():
    assert stage_name("post_run") == "raportare și închiderea zilei"
    assert stage_name("edit_and_qc") == "montaj și controlul calității"
    # A stage nobody named passes through readable, never guessed into another.
    assert stage_name("some_new_stage") == "some new stage"


def test_a_fault_is_said_in_romanian_and_kept_as_data():
    locked = OperationalError(
        "UPDATE agent SET runtime_state=?", {}, sqlite3.OperationalError("database is locked")
    )
    said = error_words(locked)
    assert said == "baza de date era ocupată de o altă scriere"
    assert error_fields(locked)["error_class"] == "OperationalError"
    assert "database is locked" in error_fields(locked)["error_detail"]

    refused = RuntimeError("api.dev.runwayml.com refused the request (HTTP 400)")
    assert error_words(refused) == "furnizorul a refuzat cererea (HTTP 400)"

    # The studio's own Romanian reason is said as written.
    ours = ValueError("Răspunsul agentului nu este o listă JSON validă")
    assert error_words(ours) == "Răspunsul agentului nu este o listă JSON validă"

    # A vendor's English is said by what it is.
    from app.providers.media_http import MediaProviderError  # noqa: PLC0415

    assert error_words(MediaProviderError("the vendor refused this narration")) == (
        "furnizorul a refuzat sau a oprit lucrarea"
    )
    assert error_words(MediaProviderError("api.x did not answer", unanswered=True)) == (
        "furnizorul nu a răspuns la timp"
    )

    # A library's English is never the sentence.
    assert error_words(RuntimeError("provider timeout")) == (
        "o eroare neașteptată în codul studioului"
    )


# ----------------------------------------------------------------------------- the preflight


def test_the_budget_line_agrees_and_says_the_period_and_state_as_words(
    engine, settings, vault, studio
):
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="15"))

    line = preflight_line(engine, settings, vault, "spending_budget")

    assert line["message"].startswith("1 buget activ: zilnic 15")
    assert "(în limită)" in line["message"]
    assert_no_codes(line["message"])
    # The codes stay where a page reads them.
    assert line["value"][0]["period"] == "DAILY" and line["value"][0]["state"] == "OK"
    # What the page prints beside the message carries no code either.
    assert_no_codes(line["detail"])


@pytest.mark.parametrize(
    ("mode", "word"),
    [("MANUAL", "manual"), ("SUPERVISED", "supravegheat"), ("AUTONOMOUS_CEO", "CEO autonom")],
)
def test_the_autonomy_line_names_the_mode_in_words(engine, settings, vault, studio, mode, word):
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = mode

    line = preflight_line(engine, settings, vault, "autonomy_mode")

    assert f"Modul de autonomie este {word}" in line["message"]
    assert_no_codes(line["message"])
    assert line["value"] == mode
    assert mode not in line["detail"]


def test_the_serial_lines_say_draft_and_the_channel_type_in_words(engine, settings, vault, studio):
    missing = preflight_line(engine, settings, vault, "serial_channel")
    assert_no_codes(missing["message"])
    assert missing["value"]["channel_type"] == "OFFICE_SERIAL"
    assert_no_codes(missing["detail"])

    seed_default_channels(engine)
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

    waiting = preflight_line(engine, settings, vault, "serial_channel")
    assert "rămâne ciornă" in waiting["message"]
    assert_no_codes(waiting["message"])
    assert "legat" in waiting["detail"] and "=True" not in waiting["detail"]
    assert waiting["value"]["bound"] is True


# ----------------------------------------------------------------------------- the day's run


def test_the_days_headline_names_stages_in_words():
    stages = [
        {"stage": "idea_generation", "status": COMPLETED, "produced": 0},
        {"stage": "selection", "status": COMPLETED, "produced": 1},
        {"stage": "edit_and_qc", "status": FAILED, "produced": 0},
        {"stage": "publish", "status": "BLOCKED", "produced": 0},
    ]
    summary, productive = run_summary(stages)

    assert productive == 1
    assert "«generarea de idei»" in summary
    assert "«montaj și controlul calității»" in summary
    assert "«publicare»" in summary
    assert "idea_generation" not in summary and "edit_and_qc" not in summary


def test_a_stage_that_raises_is_told_in_romanian_with_its_class_kept(
    engine, settings, vault, studio, monkeypatch
):
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.agents.director.letter_to_owner",
        lambda engine, subject, body, *a, **k: sent.append((subject, body)) or "id",
    )

    def locked() -> dict:
        raise OperationalError(
            "UPDATE agent SET runtime_state=?", {}, sqlite3.OperationalError("database is locked")
        )

    runners = {name: (lambda: {"status": COMPLETED, "reason": "ok"}) for name in STAGES[1:]}
    runners.pop("daily_log")
    runners["post_run"] = locked

    result = execute_daily_run(
        engine, settings, vault, stage_runners=runners, sleep=lambda _s: None
    )

    stage = next(s for s in result["stages"] if s["stage"] == "post_run")
    assert stage["status"] == FAILED
    assert stage["reason"].startswith("Baza de date era ocupată de o altă scriere")
    assert_no_codes(stage["reason"])
    assert "[SQL:" not in stage["reason"]
    assert stage["error_class"] == "OperationalError"
    assert "database is locked" in stage["error_detail"]
    assert result["stop_reason"] and "OperationalError" not in result["stop_reason"]
    assert "«raportare și închiderea zilei»" in result["stop_reason"]
    for subject, body in sent:
        assert_no_codes(subject)
        assert_no_codes(body)


# ----------------------------------------------------------------------------- the company


def test_growth_and_baseline_reasons_are_romanian(engine, studio):
    seed_default_channels(engine)
    with Session(engine) as session:
        channel_id = session.scalars(select(ChannelRecord.id)).first()

    growth = growth_diagnosis(engine, channel_id)
    assert growth["constraint"] == "NO_DATA"
    assert growth["reason"].startswith("0 filme măsurate.")
    assert "measured" not in growth["reason"]

    note = channel_baselines(engine, channel_id)["note"]
    assert note == "0 filme măsurate; o bază de comparație cere 3"


def test_the_bottleneck_and_the_blockers_are_said_in_words(engine, settings, studio):
    state = {
        "pipeline": {
            "stages": {
                "publications_failed": 1,
                "renders_failed": 2,
                "scripts_blocked": 1,
                "published": 0,
            },
            "bottleneck": {"stage": "APPROVAL", "waiting": 29, "passed_on": 1},
            "in_flight": 30,
        },
        "agents": {"dead_letter_tasks": 1, "idle": []},
        "growth": [],
        "anomalies": [],
    }
    said = {m["matter_key"]: m["observation"] for m in findings(engine, settings, state)}

    assert said["bottleneck_approval"] == (
        "Gâtuire la aprobare: 29 în așteptare, 1 trecut mai departe."
    )
    assert said["publications_failed"] == "1 publicare a eșuat și stă neterminată."
    assert said["renders_failed"] == "2 randări au eșuat."
    assert said["dead_letters"] == "1 sarcină a murit în coadă."
    assert said["scripts_blocked"] == "1 scenariu este blocat de afirmații neverificate."


def test_a_stage_report_is_titled_in_words(engine, studio):
    outcomes = {"publish": {"status": "COMPLETED", "reason": "1 film publicat."}}
    (message_id,) = file_stage_reports(engine, outcomes, str(uuid4()))
    with Session(engine) as session:
        message = session.get(AgentMessage, message_id)
        assert message.subject == "Publicare: încheiată — 1 film publicat."
        # The codes stay in the body, where the Director's review reads them.
        assert message.body_json["stage"] == "publish"
        assert message.body_json["status"] == "COMPLETED"


# ----------------------------------------------------------------------------- the register


def _events(engine, event_type: str) -> int:
    with Session(engine) as session:
        return len(
            session.scalars(select(DomainEvent).where(DomainEvent.event_type == event_type)).all()
        )


def test_resuming_an_employee_at_work_is_refused_and_records_nothing(engine, studio):
    with Session(engine) as session:
        agent = session.scalars(select(Agent).where(Agent.lifecycle == "ACTIVE")).first()
        agent_id, version = agent.id, agent.version

    with pytest.raises(AgentLifecycleRefused) as refused:
        resume_agent(engine, agent_id)
    assert "lucrează deja" in str(refused.value)
    assert _events(engine, "agent.resumed") == 0
    with Session(engine) as session:
        assert session.get(Agent, agent_id).version == version

    pause_agent(engine, agent_id)
    with pytest.raises(AgentLifecycleRefused) as again:
        pause_agent(engine, agent_id)
    assert "deja în pauză" in str(again.value)
    assert _events(engine, "agent.paused") == 1

    resume_agent(engine, agent_id)
    assert _events(engine, "agent.resumed") == 1


def test_the_api_answers_a_change_that_changes_nothing_with_409(client, headers, engine):
    seed_initial_workforce(engine)
    with Session(engine) as session:
        agent_id = session.scalars(select(Agent.id).where(Agent.lifecycle == "ACTIVE")).first()

    response = client.post(f"/api/v1/agents/{agent_id}/resume", headers=headers)
    assert response.status_code == 409
    assert "lucrează deja" in response.json()["detail"]

    missing = client.post(f"/api/v1/agents/{uuid4()}/pause", headers=headers)
    assert missing.status_code == 404


# ----------------------------------------------------------------------- his rule for text

#: Sarah's letter 4d84450b of 2026-10-12, 17:20 UTC, as he read it.
SARAH_COST_LETTER = (
    "«The Universe's Missing Pieces: Why the LHC Upgrade Matters» (2026-09-12): niciun cost în "
    "cărți; pe același subiect, 1 altă placă au costat 1,62 USD; a adus 0 vizualizări, 0,0 "
    "minute vizionate, CTR 0,0 %, 0 abonați câștigați. «How ATLAS Caught the Higgs Boson in Real "
    "Time» (2026-09-12): 0,316 USD în cărți (0,316 estimat, 0 facturat); a adus 1 vizualizare, "
    "0,0 minute vizionate, CTR 0,0 %, 0 abonați câștigați. «The Higgs Boson: The Particle That "
    "Explains Why Mass Exists» (2026-10-10): 4,584453 USD în cărți (4,584453 estimat, 0 "
    "facturat); a adus 0 vizualizări, 0,0 minute vizionate, CTR 0,0 %, 0 abonați câștigați. "
    "«How NASA Keeps Webb Alive With Frozen Fuel» (2026-10-11): 3,03676 USD în cărți (3,03676 "
    "estimat, 0 facturat); a adus 0 vizualizări, 0,0 minute vizionate, CTR 0,0 %, 0 abonați "
    "câștigați. «The Higgs Boson: Why Heavy Particles Shouldn't Exist» (2026-10-12): 7,57392 USD "
    "în cărți (7,57392 estimat, 0 facturat); a adus încă nemăsurat. Costul agenților pe film: "
    "neatribuit (rulările nu poartă încă filmul)."
)


def test_a_sum_in_a_letter_is_said_in_cents():
    """«4,584453 USD» in the books is «4,58 USD» in a letter (2026-10-12, the Owner: «să îmi
    spună exact»): half-up on integers, a decimal comma, a dot between the thousands."""
    from app.wording import usd

    assert usd(4_584_453) == "4,58 USD"
    assert usd(316_000) == "0,32 USD"
    assert usd(3_036_760) == "3,04 USD"
    assert usd(17_131_133) == "17,13 USD"
    assert usd(0) == usd(None) == "0 USD"
    assert usd(4_999) == "sub 0,01 USD"
    assert usd(5_000) == "0,01 USD"
    assert usd(1_234_500_000) == "1.234,50 USD"
    assert usd(-2_500_000) == "-2,50 USD"


def test_his_rule_for_text_names_what_sarahs_cost_letter_did_wrong():
    """The Owner over this letter, 2026-10-12: «Textul de la Sara este greu de înțeles!
    Trebuie să fie mai succint, să îmi spună exact. Nu trebuie să conțină cod, nu trebuie să
    se repete!»"""
    from app.wording import owner_text_findings, owner_text_problems

    problems = owner_text_problems(SARAH_COST_LETTER)
    assert {"money_precision", "internal_word", "repeated_sentence", "too_long"} <= set(problems)
    found = owner_text_findings(SARAH_COST_LETTER)
    assert "4,584453 USD" in found["money_precision"] and "0,316 USD" in found["money_precision"]
    assert {"în cărți", "placă"} <= set(found["internal_word"])
    # The film titles are English and are his to read: nothing in «…» is called English.
    assert "english" not in problems


def test_his_rule_for_text_names_code_paths_ids_and_english():
    """What the Director's QC letters carried on 2026-10-12: a code's names, an /api path, a
    board's id, a redo code, the environment's code and English quotes."""
    from app.wording import owner_text_findings, owner_text_problems

    letter = (
        "Ce a găsit: picture_spans_qc pe storyboard_id f06808c9-40d4-4f40-a980-84b6a5540348, "
        "prompt_hash b2a94fcd. Foaia: /api/v1/media/storyboards/x/shooting-sheet. REDO.OWNER, "
        "mediul PRODUCTION, scena LIVE. The still is not the scene and the faces must go."
    )
    assert {"code_token", "api_path", "id", "english"} <= set(owner_text_problems(letter))
    assert owner_text_findings("picture_spans_qc pe storyboard_id, prompt_hash")["code_token"] == [
        "picture_spans_qc",
        "storyboard_id",
        "prompt_hash",
    ]
    assert owner_text_findings("Cod REDO.OWNER.")["code_token"] == ["REDO.OWNER"]
    assert owner_text_findings("în PRODUCTION, scena LIVE")["code_token"] == ["PRODUCTION", "LIVE"]
    found = owner_text_findings(letter)
    assert found["api_path"] == ["/api/"]
    assert found["id"] == ["f06808c9-40d4-4f40-a980-84b6a5540348", "b2a94fcd"]
    assert owner_text_findings("prin endpoint-ul de imagini")["internal_word"] == ["endpoint"]


def test_his_rule_for_text_lets_a_plain_letter_through():
    """The cost letter as the investigation of 2026-10-12 wrote it from the day's figures, a
    name in capitals that is a name (NASA, CERN), the studio's own Romanian headings, and an
    English title in guillemets: nothing to say. A «Storyboard:» prefix in a title is code."""
    from app.wording import owner_text_problems

    letter = "\n".join(
        [
            "Cheltuit pe filme până azi: 43,27 USD.",
            "Cele 5 filme publicate au costat 17,13 USD și au adus 1 vizualizare și 0 abonați.",
            "Filmele încă nepublicate au costat 26,14 USD: «Why Ernest Lawrence's First "
            "Cyclotron…» 12,61 USD, «The Zero Script Club» 11,89 USD.",
            "Concluzie: încă nu se poate spune ce aduc filmele — 2 filme sunt private; 3 filme "
            "sunt publice de mai puțin de 3 zile, iar YouTube dă cifrele cu până la 3 zile "
            "întârziere.",
            "Nu ai nimic de decis.",
        ]
    )
    assert owner_text_problems(letter) == []
    assert owner_text_problems("«How NASA Keeps Webb Alive With Frozen Fuel» costă 3,04 USD.") == []
    assert owner_text_problems("Filmul despre CERN și NASA a costat 3,04 USD pe GPU.") == []
    assert owner_text_problems("OBSERVAȚIE: 2 randări au eșuat.\nDE FĂCUT: refă imaginea.") == []
    assert owner_text_problems("Foaia de filmare: «Storyboard: The Zero Script Club».") == [
        "internal_word"
    ]
    # One sentence said twice is repetition; a short refrain is not.
    twice = "Imaginea scenei 1 are fețe vizibile. Imaginea scenei 1 are fețe vizibile."
    assert owner_text_problems(twice) == ["repeated_sentence"]
    assert owner_text_problems("• «A»: 0 vizualizări.\n• «B»: 0 vizualizări.") == []
    assert owner_text_problems("rând\n" * 9) == ["too_many_lines"]


def test_his_rule_for_text_reads_two_films_as_two_and_a_graphics_card_as_a_word():
    """The review of 2026-10-12 tried to break the rule with the letters it must pass: two
    films with the same figures are two sentences, not one said twice (their titles differ),
    and «placa video» in a GPU letter is a graphics card, not the sheet's «placă»."""
    from app.wording import owner_text_problems

    two = (
        "«Film A» a costat 4,58 USD și a adus 0 vizualizări. "
        "«Film B» a costat 4,58 USD și a adus 0 vizualizări."
    )
    assert owner_text_problems(two) == []
    assert owner_text_problems(two + " «Film B» a costat 4,58 USD și a adus 0 vizualizări.") == [
        "repeated_sentence"
    ]
    assert owner_text_problems("Placa video a RunPod este încă pornită; verific din nou.") == []
    assert owner_text_problems("Pe aceeași temă, 1 altă placă a costat 1,62 USD.") == [
        "internal_word"
    ]
