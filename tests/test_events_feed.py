"""The record as a person reads it (2026-10-11, the Owner's register).

The live register showed «scene take recorded ×2 — storyboard_id: f06808c9-… · scene_number:
8 · kind: still» and «Kael (Video Editor) sarcină reușită — still qc · kimi-k3». The Owner:
«Trebuie să fie mai pentru oameni, mai puțin cod … poate punem și imaginea celui care
lucrează … agenții să răspundă cu o bulă când fac ceva.» The page of the record now carries
each event's sentence (the film by its title, the take by its kind, who did what), the
employee it belongs to (name, role, for the portrait), the film's title and a short word for
the office's bubble — all read from the event and the rows it names, never invented.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agents.models import Agent, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import Storyboard
from app.services import append_event, read_events, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

TITLE = "The Zero Script Club"


def studio(engine) -> dict[str, Any]:
    """The staffed studio and one storyboard with a title the register can name."""
    seed_initial_workforce(engine)
    ids = {k: str(uuid4()) for k in ("topic", "script", "board")}
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=ids["topic"],
                title=TITLE,
                topic="office",
                angle="a",
                target_audience="g",
                novelty_score=0.5,
                status="SELECTED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=ids["script"],
                topic_id=ids["topic"],
                title=TITLE,
                voiceover_full_text="text",
                claim_ids_json=[],
                status="APPROVED",
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=ids["board"],
                script_draft_id=ids["script"],
                title=TITLE,
                status="APPROVED",
                total_scenes=3,
                visual_bible_json={},
                created_at=now,
            )
        )
    with Session(engine) as session:
        agents = {
            role.name: {"id": str(agent.id), "name": str(agent.display_name)}
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
    return {**ids, "agents": agents}


def record(engine, event_type: str, aggregate: tuple[str, str], payload: dict[str, Any]) -> None:
    with Session(engine) as session, session.begin():
        append_event(session, event_type, aggregate[0], aggregate[1], 1, payload, str(uuid4()))


def page(engine) -> dict[str, dict[str, Any]]:
    """The page's events by type (one of each in these tests)."""
    return {e["event_type"]: e for e in read_events(engine, 0, 100)["events"]}


def test_a_take_sent_and_one_that_arrived_are_said_with_the_film_and_the_editor(engine):
    ids = studio(engine)
    board = ("scene_take", str(uuid4()))
    record(
        engine,
        "media.scene_take_recorded",
        board,
        {
            "storyboard_id": ids["board"],
            "scene_number": 3,
            "kind": "still",
            "status": "SUBMITTED",
            "model_id": "Qwen-Image-2512",
        },
    )
    sent = page(engine)["media.scene_take_recorded"]
    kael = ids["agents"]["VideoEditor"]
    assert sent["words_ro"] == (
        f"{kael['name']} a trimis la RunPod imaginea scenei 3 din «{TITLE}»."
    )
    assert sent["actor"] == {
        "agent_id": kael["id"],
        "name": kael["name"],
        "role": "VideoEditor",
        "role_ro": "Video Editor",
    }
    assert sent["film_title"] == TITLE
    assert "bubble_ro" not in sent

    record(
        engine,
        "media.scene_take_recorded",
        ("scene_take", str(uuid4())),
        {"storyboard_id": ids["board"], "scene_number": 3, "kind": "still", "status": "PAID"},
    )
    arrived = [
        e for e in read_events(engine, 0, 100)["events"] if e["payload"].get("status") == "PAID"
    ][0]
    assert (
        arrived["words_ro"]
        == f"A sosit imaginea scenei 3 din «{TITLE}»; {kael['name']} o verifică."
    )
    assert arrived["bubble_ro"] == "A sosit imaginea scenei 3, o verific."
    # The event itself is untouched: the page's own fields stay as they were.
    assert (
        arrived["payload"]["kind"] == "still"
        and arrived["event_type"] == "media.scene_take_recorded"
    )


def test_the_gates_and_the_walk_speak_of_the_film_by_its_title(engine):
    ids = studio(engine)
    record(
        engine,
        "media.still_needs_owner",
        ("storyboard", ids["board"]),
        {
            "scene_number": 4,
            "status": "NEEDS_OWNER",
            "rerolls": 2,
            "reason": (
                "Scena 4: după 2 refaceri imaginea tot nu trece (Modelul de vedere nu vede o "
                "singură fotografie «three panels»). Decide Proprietarul pe foaia de filmare."
            ),
        },
    )
    record(
        engine,
        "runbook.film_continued",
        ("storyboard", ids["board"]),
        {
            "status": "BLOCKED",
            "reason": "Oprit: f06808c9: Prompturile au 1 blocaj.",
            "cause": "serial_unfilmed_after_start",
        },
    )
    record(
        engine,
        "media.sheet_repair_finished",
        ("storyboard", ids["board"]),
        {
            "status": "UNRESOLVED",
            "remaining": [
                {"code": "SAME_CAMERA_EVERY_SCENE", "scene_index": None},
                {"code": "NEEDS_SHOT_PLAN", "scene_index": 8},
            ],
        },
    )
    got = page(engine)
    held = got["media.still_needs_owner"]
    assert held["words_ro"].startswith(
        f"Scena 4 din «{TITLE}»: după 2 refaceri imaginea tot nu trece ("
    )
    assert held["words_ro"] == (
        f"Scena 4 din «{TITLE}»: după 2 refaceri imaginea tot nu trece (Modelul de vedere nu "
        "vede o singură fotografie «three panels»); Directoarea rescrie scena."
    )
    assert "Decide Proprietarul" not in held["words_ro"]
    assert held["bubble_ro"] == "Scena 4 tot nu trece; o rescriem."
    walk = got["runbook.film_continued"]
    assert walk["words_ro"] == f"Filmul «{TITLE}» s-a oprit: f06808c9: Prompturile au 1 blocaj."
    assert walk["film_title"] == TITLE
    repair = got["media.sheet_repair_finished"]
    assert (
        repair["words_ro"]
        == f"Foaia «{TITLE}» mai are blocaje: SAME_CAMERA_EVERY_SCENE, NEEDS_SHOT_PLAN (scena 8)."
    )


def test_the_directors_decision_and_her_retirement_are_hers(engine):
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    record(
        engine,
        "media.director_qc_decision",
        ("quality_control_report", str(uuid4())),
        {"storyboard_id": ids["board"], "decision": "REPAIR", "outcome": "REPAIRED"},
    )
    record(
        engine,
        "media.scene_take_retired",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "scene_number": 4,
            "kind": "still",
            "director_repair": True,
            "owner_press": False,
        },
    )
    got = page(engine)
    decided = got["media.director_qc_decision"]
    assert decided["actor"]["role"] == "Director" and decided["actor"]["role_ro"] == "Directoarea"
    assert decided["words_ro"] == (
        f"{sarah['name']} a decis filmul «{TITLE}»: se refac doar scenele pe care le-a numit "
        "— refăcut, din nou la control."
    )
    assert decided["bubble_ro"] == "Am decis: se refac doar scenele pe care le-a numit."
    retired = got["media.scene_take_retired"]
    assert retired["actor"]["role"] == "Director"
    assert (
        retired["words_ro"]
        == f"Imaginea scenei 4 din «{TITLE}» a fost retrasă la decizia Directoarei; "
        "nu se mai folosește."
    )


def test_a_finished_run_is_said_as_a_sentence_with_the_task_in_words(engine):
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    record(
        engine,
        "agent.run_completed",
        ("agent", kael["id"]),
        {
            "agent_id": kael["id"],
            "task_type": "still_qc",
            "status": "SUCCEEDED",
            "model_name": "kimi-k3",
        },
    )
    run = page(engine)["agent.run_completed"]
    assert (
        run["words_ro"]
        == f"{kael['name']} a terminat verificarea unei imagini: reușită (cu kimi-k3)."
    )
    assert run["bubble_ro"] == "Gata: verificarea unei imagini ✓"
    assert run["actor"]["agent_id"] == kael["id"]


def test_money_spent_names_the_film_from_its_reference_and_an_unknown_event_keeps_no_words(engine):
    ids = studio(engine)
    record(
        engine,
        "economy.spend_reservation_closed",
        ("spend_reservation", str(uuid4())),
        {
            "status": "SETTLED",
            "reference": f"foaie:{ids['board']}:stills:02b854243e4c99ca:7b8c",
            "usd": "4.2",
        },
    )
    record(engine, "office.room_created", ("office", str(uuid4())), {"room": "render bay"})
    got = page(engine)
    spent = got["economy.spend_reservation_closed"]
    assert spent["words_ro"] == f"Cheltuit: 4.2 USD pe imagini din «{TITLE}» (settled)."
    assert spent["film_title"] == TITLE and spent["actor"]["role"] == "Accountant"
    unknown = got["office.room_created"]
    assert "words_ro" not in unknown and "actor" not in unknown and "film_title" not in unknown
