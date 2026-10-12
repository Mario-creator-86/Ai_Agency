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

import json
from typing import Any
from uuid import uuid4

from app.agents.models import Agent, AgentRun, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import Storyboard
from app.services import append_event, read_events, snapshot, utc_now
from app.workflows.models import OutboxRecord
from app.workflows.publisher import ConnectionManager, publish_pending_outbox, replay_events
from app.workflows.services import append_event_with_outbox
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
    # The office hears the editor send it (2026-10-12: the wait on RunPod used to be silent).
    assert sent["bubble_ro"] == "Am trimis imaginea scenei 3 la RunPod."

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


def test_a_walk_that_did_nothing_stood_still_and_names_the_film_once(engine):
    """2026-10-12 19:50 UTC, f06808c9: the Owner's GPU stop let nothing of her repair be done,
    and the register read «Filmul «…» a mers până la capăt: Filmul «Storyboard: …»: nimic din ce
    a cerut Directoarea nu se putea reface acum.» and «n-a putut decide încă» although she had
    decided. The walk stood still, the film is named once, and the real reason is said."""
    ids = studio(engine)
    record(
        engine,
        "media.director_qc_waiting",
        ("quality_control_report", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "reason": (
                "nimic din refacerea hotărâtă nu se putea face: Scena 4: mișcarea: Ai oprit "
                "GPU-ul: niciun cadru nu se cumpără până nu îl pornești din nou."
            ),
        },
    )
    record(
        engine,
        "runbook.film_continued",
        ("storyboard", ids["board"]),
        {
            "status": "COMPLETED",
            "reason": (
                f"Filmul «Storyboard: {TITLE}»: nimic din ce a cerut Directoarea nu se putea "
                "reface acum."
            ),
            "cause": "director_qc:c4a5a20e",
        },
    )
    got = page(engine)
    walk = got["runbook.film_continued"]["words_ro"]
    assert walk == (
        f"Filmul «{TITLE}» a stat pe loc: nimic din ce a cerut Directoarea nu se putea reface acum."
    ), walk
    assert "până la capăt" not in walk and "Storyboard" not in walk
    waiting = got["media.director_qc_waiting"]["words_ro"]
    assert f"a hotărât ce se reface la filmul «{TITLE}», dar acum nu se poate face: " in waiting
    assert "Ai oprit GPU-ul" in waiting and "n-a putut decide" not in waiting


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


def test_money_spent_names_the_film_from_its_reference_and_an_unknown_event_says_its_name(engine):
    """A kind nobody has words for is said by its name alone (2026-10-12): never its fields."""
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
    assert spent["words_ro"] == f"Cheltuit: 4.2 USD pe imagini din «{TITLE}»."
    assert spent["film_title"] == TITLE and spent["actor"]["role"] == "Accountant"
    unknown = got["office.room_created"]
    assert unknown["words_ro"] == "Birou: room created."
    assert "actor" not in unknown and "film_title" not in unknown and "bubble_ro" not in unknown


def test_the_directors_editorial_note_is_hers_and_says_the_score_and_the_outcome(engine):
    """`editorial.judged` (2026-10-12): a version that passed ships to filming; a version below
    the bar goes back to the writer with the two weakest criteria named. The event sits on the
    script draft, not on a storyboard, so the version's own title is what the register says."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    record(
        engine,
        "editorial.judged",
        ("script_draft", str(uuid4())),
        {
            "kind": "factual_short",
            "round": 2,
            "title": TITLE,
            "judged": True,
            "total": 41,
            "weakest": ["hook", "punchline"],
            "passed": True,
            "shipped": True,
            "stopped": "passed",
        },
    )
    shipped = page(engine)["editorial.judged"]
    assert shipped["actor"]["role"] == "Director"
    assert shipped["words_ro"] == (
        f"{sarah['name']} a notat scenariul short-ului «{TITLE}»: 41/50 la versiunea 2; "
        "trece la filmare."
    )
    assert shipped["bubble_ro"] == "Trece: 41/50."

    record(
        engine,
        "editorial.judged",
        ("story_episode", str(uuid4())),
        {
            "kind": "serial_episode",
            "round": 1,
            "title": "Episodul 2",
            "judged": True,
            "total": 25,
            "weakest": ["hook", "punchline"],
            "passed": False,
            "shipped": False,
            "stopped": "rounds_spent",
        },
    )
    sent_back = page(engine)["editorial.judged"]
    assert sent_back["words_ro"] == (
        f"{sarah['name']} a notat versiunea 1 a episodului serialului «Episodul 2»: 25/50; "
        "cele mai slabe: cârligul și poanta; brief la scenarist."
    )
    assert sent_back["bubble_ro"] == "Versiunea 1: 25/50, brief la scenarist."


# ---------------------------------------------------------------------------------------------
# 2026-10-12, the Director's repair loop on RunPod. The live register (10:27) read «run paused —
# endpoint_id: u07hiqhesi015d · items: 2 · seconds: 1.33», «gpu session opened — endpoint_id …
# purpose: image · step: scene_redo», «spend reserved — purpose: sheet:scene_redo · usd: 0.84»,
# «qc paid redo — scene_index: 4 · of_asset: c00866fc-…». The payloads below are those events'.


def test_the_runpod_round_and_the_gpu_are_said_without_endpoint_ids(engine):
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    gpu_session = str(uuid4())
    record(
        engine,
        "runpod.gpu_session_opened",
        ("gpu_session", gpu_session),
        {
            "endpoint_id": "u07hiqhesi015d",
            "purpose": "image",
            "step": "scene_redo",
            "storyboard_id": ids["board"],
            "workers_max": 1,
            "shared": False,
        },
    )
    record(
        engine,
        "runpod.run_paused",
        ("gpu_session", gpu_session),
        {
            "endpoint_id": "u07hiqhesi015d",
            "items": 2,
            "cleared": True,
            "seconds": 1.332,
            "paused_answers": 1,
            "ended": None,
            "budget_seconds": 180.0,
        },
    )
    off_reading = {
        "endpoint_id": "u07hiqhesi015d",
        "off": True,
        "workers_max": 0,
        "running": 0,
        "in_progress": 0,
        "in_queue": 0,
        "idle": 1,
        "reason_ro": None,
        "read_at": "2026-10-12T06:41:23.962201+00:00",
    }
    record(
        engine,
        "runpod.gpu_off_verified",
        ("gpu_session", gpu_session),
        {**off_reading, "reason": "STEP_DONE"},
    )
    record(
        engine,
        "runpod.gpu_forced_off",
        ("gpu_session", "u07hiqhesi015d"),
        {**off_reading, "reason": "SHUTDOWN", "fast": False, "errors": []},
    )
    got = page(engine)
    opened = got["runpod.gpu_session_opened"]
    assert opened["words_ro"] == (
        f"{kael['name']} a pornit GPU-ul RunPod pentru imagini din «{TITLE}» (refacerea unei "
        "scene); modelul se încarcă (~10 min)."
    )
    assert opened["bubble_ro"] == "GPU pornit: aștept imaginile."
    assert opened["actor"]["role"] == "VideoEditor" and opened["film_title"] == TITLE
    paused = got["runpod.run_paused"]
    assert paused["words_ro"] == (
        f"{kael['name']} a trimis la RunPod o rundă de 2 lucrări; RunPod a pornit după 1 s."
    )
    assert paused["bubble_ro"] == "Runda a plecat la RunPod; aștept."
    off = got["runpod.gpu_off_verified"]
    assert off["words_ro"] == "GPU-ul RunPod s-a oprit (pasul s-a încheiat); nu mai costă nimic."
    forced = got["runpod.gpu_forced_off"]
    assert forced["words_ro"] == "GPU-ul RunPod a fost oprit forțat (studioul s-a oprit)."
    # The GPU going off is the studio's housekeeping, nobody's portrait.
    assert "actor" not in off and "actor" not in forced
    for row in (opened, paused, off, forced):
        assert "u07hiqhesi015d" not in row["words_ro"]


def test_money_reserved_estimated_and_closed_names_the_film_and_the_redo(engine):
    ids = studio(engine)
    nadia = ids["agents"]["Accountant"]
    board = ids["board"]
    record(
        engine,
        "economy.spend_reserved",
        ("spend_reservation", str(uuid4())),
        {"purpose": "sheet:scene_redo", "usd": "0.84"},
    )
    record(
        engine,
        "economy.provider_cost_recorded",
        ("provider_cost", str(uuid4())),
        {
            "provider": "runpod",
            "reference": f"redo:{board}:still:1:dee80830-8a30-4d7e-b1c1-ab92ae40a52f",
            "status": "ESTIMATED",
            "vr": "0.28",
            "posted": False,
        },
    )
    record(
        engine,
        "economy.spend_reservation_closed",
        ("spend_reservation", str(uuid4())),
        {
            "status": "SETTLED",
            "reference": f"redo:{board}:motion:3:dee80830-8a30-4d7e-b1c1-ab92ae40a52f",
            "usd": "0.66",
        },
    )
    got = page(engine)
    reserved = got["economy.spend_reserved"]
    assert reserved["words_ro"] == (
        f"{nadia['name']} a pus deoparte 0.84 USD pentru refacerea unei scene."
    )
    assert reserved["bubble_ro"] == "Am pus deoparte 0.84 USD."
    assert reserved["actor"]["role"] == "Accountant"
    cost = got["economy.provider_cost_recorded"]
    assert cost["words_ro"] == (
        f"Cost estimat la RunPod: 0.28 VR$ pentru refacerea imaginii scenei 1 din «{TITLE}»."
    )
    assert cost["film_title"] == TITLE
    settled = got["economy.spend_reservation_closed"]
    assert settled["words_ro"] == (
        f"Cheltuit: 0.66 USD pe refacerea clipului scenei 3 din «{TITLE}»."
    )

    record(
        engine,
        "economy.spend_reservation_closed",
        ("spend_reservation", str(uuid4())),
        {"status": "RELEASED", "reference": f"redo:{board}:still:5:7b8c", "usd": "0.84"},
    )
    released = next(
        e for e in read_events(engine, 0, 100)["events"] if e["payload"].get("status") == "RELEASED"
    )
    assert released["words_ro"] == (
        f"Rezervarea de 0.84 USD pentru refacerea imaginii scenei 5 din «{TITLE}» a fost "
        "eliberată: nu s-a cheltuit."
    )


def test_the_directors_brief_names_the_layer_and_whether_the_rewrite_landed(engine):
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    kael = ids["agents"]["VideoEditor"]
    board = ("storyboard", ids["board"])
    record(
        engine,
        "media.director_scene_brief",
        board,
        {
            "scene_index": 5,
            "layer": "still",
            "asked_layer": "still",
            "rewritten": True,
            "same_prompt": False,
            "reason": "",
            "diagnosis": "The still prompt still contains the sentence 'There are no people'.",
            "avoid": ["the words 'people', 'person'"],
            "keep": ["medium shot, 50mm lens"],
        },
    )
    record(
        engine,
        "media.director_scene_brief",
        board,
        {
            "scene_index": 4,
            "layer": "motion",
            "asked_layer": "motion",
            "rewritten": False,
            "same_prompt": True,
            "reason": "Rescrierea a dat același prompt; nimic nou de cumpărat.",
        },
    )
    for scene, reason, layer in ((5, "director_brief", "still"), (3, "serial_recompose", "still")):
        record(
            engine,
            "media.prompts_rewritten",
            board,
            {
                "storyboard_id": ids["board"],
                "scene_index": scene,
                "reason": reason,
                "decided_by": "director",
                "layer": layer,
            },
        )
    record(
        engine,
        "media.prompts_rewritten",
        board,
        {
            "scene_index": 6,
            "reason": "serial_reroll",
            "decided_by": "director",
            "layer": "motion",
            "refused_code": "QC.CLIP",
        },
    )
    events = read_events(engine, 0, 100)["events"]

    def by_scene(kind: str) -> dict[int, dict[str, Any]]:
        return {e["payload"]["scene_index"]: e for e in events if e["event_type"] == kind}

    briefs = by_scene("media.director_scene_brief")
    assert briefs[5]["actor"]["role"] == "Director"
    assert briefs[5]["words_ro"] == (
        f"{sarah['name']} a dat brief de rescriere pentru imaginea scenei 5 din «{TITLE}»; "
        f"{kael['name']} a rescris-o."
    )
    assert briefs[5]["bubble_ro"] == "Brief pentru scena 5: imaginea."
    assert briefs[4]["words_ro"] == (
        f"{sarah['name']} a dat brief de rescriere pentru mișcarea scenei 4 din «{TITLE}»; "
        "rescrierea a dat același prompt, nimic nou de cumpărat."
    )
    rewrites = by_scene("media.prompts_rewritten")
    assert rewrites[5]["actor"]["role"] == "Director"
    assert rewrites[5]["words_ro"] == (
        f"Promptul imaginii scenei 5 din «{TITLE}» a fost rescris la brief-ul Directoarei."
    )
    assert rewrites[5]["bubble_ro"] == "Promptul scenei 5 e rescris."
    assert rewrites[3]["words_ro"] == (
        f"Scena 3 a serialului «{TITLE}» a fost compusă din nou cu cuvintele de azi; imaginea "
        "se reface."
    )
    assert rewrites[6]["words_ro"] == (
        f"Scena 6 a serialului «{TITLE}»: cadrul se reface pe aceleași cuvinte, cu altă sămânță."
    )


def test_the_repair_loop_speaks_of_scenes_and_films_never_of_assets(engine):
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    board = ids["board"]
    asset, report = str(uuid4()), str(uuid4())
    record(
        engine,
        "runbook.qc_paid_redo",
        ("storyboard", board),
        {
            "scene_index": 5,
            "of_asset": asset,
            "kinds": ["still"],
            "open_motion": True,
            "continues": None,
            "started_at": "2026-10-12T06:50:42.518752+00:00",
        },
    )
    record(
        engine,
        "runbook.qc_repair",
        ("storyboard", board),
        {
            "report_id": report,
            "storyboard_id": board,
            "of_asset": asset,
            "new_asset": str(uuid4()),
            "decided_by": "Director",
            "applied": [],
            "bought": [
                {"redo": "still", "scene_index": 1, "credits": 28.0},
                {"redo": "motion", "scene_index": 1, "credits": 58.1598},
                {"redo": "still", "scene_index": 3, "credits": 63.3533},
                {"redo": "motion", "scene_index": 3, "credits": 33.0},
                {"redo": "still", "scene_index": 5, "credits": 14.0},
            ],
            "asked": [],
            "refused": [],
            "limited": [],
            "skipped": [],
            "waiting": [
                {
                    "scene_index": 5,
                    "kind": "still",
                    "status": "NOT_BOUGHT",
                    "since": "2026-10-12T05:54:36.626712+00:00",
                    "next_ro": "Refacerea scenei 5 nu a adus nimic folosibil.",
                }
            ],
            "replaced_his": [],
            "made": [str(uuid4())],
            "requalified": "FAILED",
            "requalified_report_id": str(uuid4()),
        },
    )
    record(
        engine,
        "media.clip_qc_checked",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": board,
            "scene_number": 4,
            "take_id": str(uuid4()),
            "seed": 580970440,
            "attempt": 1,
            "scene": 4,
            "passed": True,
            "verdict": "PASSED",
            "checks": [{"code": "motion", "status": "PASSED", "blocking": False}],
            "blocks_ro": [],
            "warnings_ro": [],
        },
    )
    failure = (
        "Scene 5: the picture is not what the scene asked for — The frame shows a rough bare-rock "
        "tunnel with drifting orange sparks or embers, not the metallic detector cavern with "
        "flickering amber indicator points on its rings that the scene asks for."
    )
    record(
        engine,
        "media.qc_evaluated",
        ("quality_control_report", report),
        {"media_asset_id": asset, "status": "FAILED", "score": 0.5, "failures": [failure]},
    )
    kept_reason = "îl folosește un film mai nou, încă necitit de controlul calității"
    record(
        engine,
        "media.intermediates_released",
        ("media_asset", asset),
        {
            "files": ["shot_03_redo_85623e91.mp4"],
            "bytes": 47294502,
            "kept": [{"file": f"shot_0{n}_c75050fa.mp4", "reason": kept_reason} for n in range(4)],
        },
    )
    record(
        engine,
        "media.video_rendered",
        ("media_asset", str(uuid4())),
        {
            "storyboard_id": board,
            "render_engine": "FFMPEG",
            "remade_from": asset,
            "redo": "motion",
            "scene_index": 4,
            "provenance_hash": "5b173221a9022e2a57632b8ad30857c108fc24cfd5080e0d197ff12c4991d943",
            "file_size_bytes": 33827099,
            "duration_seconds": 38.249999,
        },
    )
    record(
        engine,
        "media.scene_take_restored",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": board,
            "scene_number": 5,
            "kind": "still",
            "status": "APPROVED",
            "retired_event_id": str(uuid4()),
            "retired_code": "REDO.OWNER",
            "cause": "redo_delivered_nothing",
            "prompt_matches": False,
            "bound_to_picture": False,
            "package_restored": False,
        },
    )
    got = page(engine)
    redo = got["runbook.qc_paid_redo"]
    assert redo["words_ro"] == (
        f"Refacerea plătită a scenei 5 din «{TITLE}»: imaginea cumpărată; mișcarea poate urma."
    )
    assert redo["bubble_ro"] == "Scena 5: imaginea cumpărată."
    assert redo["actor"]["role"] == "VideoEditor"
    repair = got["runbook.qc_repair"]
    assert repair["actor"]["role"] == "Director"
    assert repair["words_ro"] == (
        f"{sarah['name']} a aplicat refacerea filmului «{TITLE}»: 5 refaceri cumpărate (imaginea "
        "scenei 1, mișcarea scenei 1, imaginea scenei 3…); scena 5 încă așteaptă; filmul "
        "refăcut a picat din nou la control."
    )
    clip = got["media.clip_qc_checked"]
    assert clip["words_ro"] == f"Clipul scenei 4 din «{TITLE}» a trecut controlul."
    assert clip["bubble_ro"] == "Clipul scenei 4 a trecut ✓"
    assert clip["actor"]["role"] == "VideoEditor"
    judged = got["media.qc_evaluated"]
    assert judged["words_ro"].startswith(
        "Controlul calității a picat filmul (scor 0,50): Scene 5: the picture is not what"
    )
    # A shortened quotation trails off; no full stop after the ellipsis.
    assert judged["words_ro"].endswith("…") and not judged["words_ro"].endswith("….")
    assert judged["bubble_ro"] == "Filmul a picat la control."
    released = got["media.intermediates_released"]
    assert released["words_ro"] == (
        "Fișierele intermediare ale unei randări vechi au fost șterse: 47,3 MB eliberați; "
        f"4 fișiere păstrate ({kept_reason})."
    )
    rendered = got["media.video_rendered"]
    assert rendered["words_ro"] == (
        f"Filmul «{TITLE}» a fost asamblat din nou după refacerea mișcării scenei 4 (38 s)."
    )
    assert rendered["bubble_ro"] == "Filmul e asamblat din nou."
    restored = got["media.scene_take_restored"]
    assert restored["words_ro"] == (
        f"Imaginea scenei 5 din «{TITLE}» a fost pusă la loc: refacerea n-a adus nimic."
    )
    for row in (redo, repair, clip, judged, released, rendered, restored):
        assert asset not in row["words_ro"] and report not in row["words_ro"]


def test_a_still_sent_back_by_clip_qc_and_the_motions_hold_are_said_in_words(engine):
    """2026-10-12, the cyclotron's scene 1: clip QC found the fault in the still the clip was
    made from; the still goes back to the gate and the scene needs a new picture first. The
    register says it as a sentence, never as a status word with ids."""
    ids = studio(engine)
    board = ids["board"]
    still = str(uuid4())
    record(
        engine,
        "media.still_sent_back",
        ("scene_take", still),
        {
            "storyboard_id": board,
            "scene_number": 1,
            "failure_kind": "CLIP_QC",
            "failure_code": "LOCAL.STILL_GATE",
            "reason": "Scena 1: greșeala e în imaginea din care s-a făcut clipul (se vede o față).",
        },
    )
    record(
        engine,
        "media.motion_needs_owner",
        ("storyboard", board),
        {
            "severity": "WARNING",
            "scene_number": 1,
            "status": "NEEDS_STILL",
            "reason": (
                "Scena 1: greșeala e în imaginea din care s-a făcut clipul (se vede o față); "
                "aceeași imagine nu se mai animă."
            ),
            "failure_kind": None,
            "clip_qc": "FAILED",
            "holds": True,
        },
    )
    got = page(engine)
    sent_back = got["media.still_sent_back"]
    assert sent_back["words_ro"] == (
        f"Imaginea scenei 1 din «{TITLE}» se întoarce la poarta imaginilor: controlul clipului "
        "a găsit greșeala în ea; nu se mai animă."
    )
    assert sent_back["bubble_ro"] == "Scena 1: imagine nouă, apoi mișcare."
    assert sent_back["actor"]["role"] == "VideoEditor"
    hold = got["media.motion_needs_owner"]
    assert hold["words_ro"].startswith(
        f"Scena 1 din «{TITLE}» are nevoie de o imagine nouă înainte de mișcare: Scena 1: "
        "greșeala e în imaginea"
    )
    assert still not in hold["words_ro"] and "NEEDS" not in hold["words_ro"]


def test_a_refused_take_a_lost_one_and_a_sent_one_speak_for_the_editor(engine):
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    base = {"storyboard_id": ids["board"], "kind": "motion", "model_id": "LTX-2.5"}
    record(
        engine,
        "media.scene_take_recorded",
        ("scene_take", str(uuid4())),
        {
            **base,
            "scene_number": 6,
            "status": "REFUSED",
            "failure_code": "RUNPOD.CANCELLED",
            "failure_detail": "Lucrarea a fost anulată de studio la oprire.",
        },
    )
    record(
        engine,
        "media.scene_take_recorded",
        ("scene_take", str(uuid4())),
        {**base, "scene_number": 7, "status": "LOST", "failure_code": "RUNPOD.EXPIRED"},
    )
    record(
        engine,
        "media.scene_take_recorded",
        ("scene_take", str(uuid4())),
        {**base, "scene_number": 8, "status": "SUBMITTED", "credits_quoted": 24.0},
    )
    by_scene = {
        e["payload"]["scene_number"]: e
        for e in read_events(engine, 0, 100)["events"]
        if e["event_type"] == "media.scene_take_recorded"
    }
    assert by_scene[6]["words_ro"] == (
        f"RunPod a refuzat clipul scenei 6 din «{TITLE}»: Lucrarea a fost anulată de studio la "
        "oprire."
    )
    assert "RUNPOD.CANCELLED" not in by_scene[6]["words_ro"]
    assert by_scene[7]["words_ro"] == (
        f"Clipul scenei 7 din «{TITLE}» s-a pierdut: RunPod a primit lucrarea, dar rezultatul a "
        "expirat înainte să fie preluat."
    )
    sent = by_scene[8]
    assert sent["words_ro"] == f"{kael['name']} a trimis la RunPod clipul scenei 8 din «{TITLE}»."
    assert sent["bubble_ro"] == "Am trimis clipul scenei 8 la RunPod."


def test_an_agent_at_work_says_so_in_a_bubble_and_an_unknown_kind_shows_no_ids(engine):
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    record(
        engine,
        "agent.state_changed",
        ("agent", kael["id"]),
        {"runtime_state": "THINKING", "task_type": "clip_qc", "run_id": str(uuid4())},
    )
    record(
        engine,
        "runpod.gpu_guard_off",
        ("gpu_session", "u07hiqhesi015d"),
        {"endpoint_id": "u07hiqhesi015d", "workers_max": 0, "running": 0},
    )
    record(
        engine,
        "media.scene_take_collected",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "scene_number": 2,
            "remote_task_id": "65106659-77d9-46ea-8729-5605affc8e88-e2:0",
        },
    )
    got = page(engine)
    working = got["agent.state_changed"]
    assert working["words_ro"] == f"{kael['name']} lucrează la verificarea unui clip."
    assert working["bubble_ro"] == "Lucrez la verificarea unui clip."
    assert working["actor"]["agent_id"] == kael["id"]
    guard = got["runpod.gpu_guard_off"]
    assert guard["words_ro"] == "RunPod: gpu guard off."
    assert "u07hiqhesi015d" not in guard["words_ro"] and "actor" not in guard
    collected = got["media.scene_take_collected"]
    assert collected["words_ro"] == f"«{TITLE}», scena 2: scene take collected."
    assert "65106659" not in collected["words_ro"] and collected["actor"]["role"] == "VideoEditor"


class _Recorder(ConnectionManager):
    """A connection manager that keeps what it was asked to send."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> int:
        self.sent.append(message)
        return 1


def test_the_snapshot_and_the_live_socket_carry_the_same_words_as_the_record(engine):
    """The page keeps the first copy of an event it receives — the snapshot's twenty, then the
    socket's live ones — so those copies must carry the words too (2026-10-12: the newest
    rows of the live register were the raw ones while the paged history spoke)."""
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    with Session(engine) as session, session.begin():
        append_event_with_outbox(
            session,
            "media.scene_take_recorded",
            "scene_take",
            str(uuid4()),
            1,
            {
                "storyboard_id": ids["board"],
                "scene_number": 3,
                "kind": "still",
                "status": "SUBMITTED",
                "model_id": "Qwen-Image-2512",
            },
            str(uuid4()),
        )
    expected = f"{kael['name']} a trimis la RunPod imaginea scenei 3 din «{TITLE}»."

    newest = snapshot(engine)["events"][-1]
    assert newest["event_type"] == "media.scene_take_recorded"
    assert newest["words_ro"] == expected and newest["film_title"] == TITLE
    assert newest["actor"]["agent_id"] == kael["id"]

    manager = _Recorder()
    assert publish_pending_outbox(engine, manager) >= 1
    live = next(
        m["data"] for m in manager.sent if m["data"]["event_type"] == "media.scene_take_recorded"
    )
    assert live["words_ro"] == expected and live["actor"]["name"] == kael["name"]
    assert live["bubble_ro"] == "Am trimis imaginea scenei 3 la RunPod."
    # The socket's catch-up after a drop reads the same words.
    replayed = next(
        e for e in replay_events(engine) if e["event_type"] == "media.scene_take_recorded"
    )
    assert replayed["words_ro"] == expected and replayed["payload"] == live["payload"]
    # The outbox row itself keeps only the event: the words are the socket's, never written back.
    with Session(engine) as session:
        row = session.scalars(select(OutboxRecord).order_by(OutboxRecord.sequence.desc())).first()
    assert row is not None and "words_ro" not in row.payload


# --------------------------------------------------------------------- the scene a run works on
#
# 2026-10-12, the Owner's office: «GATA: RESCRIEREA PROMPTULUI UNEI SCENE ✓» over the editor's
# head, with no scene and no film, and his question «LA CE SCENĂ LUCREAZĂ?!». The run's own
# summary names its scene; the events of its correlation name the film.


def a_run(
    engine,
    agent_id: str,
    task: str,
    summary: str,
    correlation: str,
    *,
    output_text: str | None = None,
    template: str = "v1",
    started_at: str | None = None,
) -> str:
    """One finished run as `run_agent_task` records it, with its one-sentence summary."""
    run_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=run_id,
                agent_id=agent_id,
                task_type=task,
                objective="the prompt",
                prompt_template_version=template,
                model_name="kimi-k3",
                provider_name="fake",
                status="SUCCEEDED",
                output_text=output_text,
                correlation_id=correlation,
                started_at=started_at or utc_now(),
                finished_at=utc_now(),
                context_json={"task_summary": summary},
            )
        )
    return run_id


def run_events(engine, agent_id: str, run_id: str, task: str, correlation: str) -> None:
    """The run's THINKING state and its completion, as `run_agent_task` appends them."""
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "agent.state_changed",
            "agent",
            agent_id,
            1,
            {"runtime_state": "THINKING", "task_type": task, "run_id": run_id},
            correlation,
        )
        append_event(
            session,
            "agent.run_completed",
            "agent_run",
            run_id,
            1,
            {
                "agent_id": agent_id,
                "status": "SUCCEEDED",
                "task_type": task,
                "model_name": "kimi-k3",
            },
            correlation,
        )


def by_run(engine) -> dict[tuple[str, str], dict[str, Any]]:
    """The page's employee events by (event type, run id)."""
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for event in read_events(engine, 0, 200)["events"]:
        run_id = event["payload"].get("run_id") or (
            event["aggregate_id"] if event["aggregate_type"] == "agent_run" else None
        )
        if run_id:
            found[(event["event_type"], str(run_id))] = event
    return found


def test_a_rewrite_names_its_scene_and_its_film_while_it_works_and_when_it_is_done(engine):
    """The Director's ladder rewrites scenes 3 and 4 of one film under ONE correlation
    (2026-10-12, f06808c9, 13:47): each run is said with its own scene, both with the film."""
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    ladder = str(uuid4())
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "media.director_qc_decision",
            "quality_control_report",
            str(uuid4()),
            1,
            {"storyboard_id": ids["board"], "decision": "REPAIR", "scenes": [3, 4]},
            ladder,
        )
    runs = {}
    for scene in (3, 4):
        runs[scene] = a_run(
            engine,
            kael["id"],
            "scene_prompt_rewrite",
            f"Rescriu scena {scene} din «Storyboard: {TITLE}» după brief-ul Directoarei.",
            ladder,
        )
        run_events(engine, kael["id"], runs[scene], "scene_prompt_rewrite", ladder)

    got = by_run(engine)
    for scene, run_id in runs.items():
        working = got[("agent.state_changed", run_id)]
        assert working["bubble_ro"] == f"Lucrez la rescrierea scenei {scene} din «{TITLE}»."
        assert working["words_ro"] == (
            f"{kael['name']} lucrează la rescrierea scenei {scene} din «{TITLE}»."
        )
        done = got[("agent.run_completed", run_id)]
        assert done["bubble_ro"] == f"Gata: rescrierea scenei {scene} din «{TITLE}» ✓"
        assert done["words_ro"] == (
            f"{kael['name']} a terminat rescrierea scenei {scene} din «{TITLE}»: reușită "
            "(cu kimi-k3)."
        )
        assert done["actor"]["agent_id"] == kael["id"]


def review_answer(verdict: str, reason_ro: str) -> str:
    """Her review of a rewrite as her model writes it, in the shape her review's schema
    accepts (`scene_rewrite.RewriteReview`), with every field the shared contract names."""
    treated = verdict == "TREATS"
    finding = {
        "id": 1,
        "qc_text": "lettering on the ledger",
        "finding": "lettering on the ledger",
        "treated": treated,
        "by": "Pages and screens are blank." if treated else "",
        "why_not": "" if treated else "the ledger is still open at the figures",
        "severity": "serious",
        "layer": "still",
    }
    return json.dumps(
        {
            "verdict": verdict,
            "findings": [finding],
            "reason_ro": reason_ro,
            "cause": "an open ledger invites figures the model draws as writing",
            "lesson": "Ask for a closed ledger; an open one is drawn with lettering.",
        },
        ensure_ascii=False,
    )


def test_her_review_of_a_rewrite_says_whether_it_treats_the_finding(engine):
    """Her review refuses a rewrite (MISSES) or passes it (TREATS): the office hears which, for
    which scene — read from her answer before the brief records it, and from the brief once it
    does. A pass never says «se poate cumpăra»: whether anything is bought is the money's and
    the Owner's GPU hold's, not her review's (2026-10-12, review of a9f84ea)."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    ladder = str(uuid4())
    refused = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        f"Verific dacă rescrierea scenei 4 din «Storyboard: {TITLE}» tratează constatările "
        "înainte să cumpărăm ceva pe ea.",
        ladder,
        output_text=review_answer("MISSES", "Promptul cere tot registrul deschis la cifre."),
    )
    run_events(engine, sarah["id"], refused, "director_rewrite_review", ladder)
    treated = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        f"Verific dacă rescrierea scenei 3 din «Storyboard: {TITLE}» tratează constatările "
        "înainte să cumpărăm ceva pe ea.",
        ladder,
        output_text="not the answer she gave the second time",
    )
    run_events(engine, sarah["id"], treated, "director_rewrite_review", ladder)
    # Her brief for scene 3 records the review her second answer gave: TREATS.
    record_in = {
        "scene_index": 3,
        "layer": "still",
        "rewritten": True,
        "review_verdict": "TREATS",
        "review_reason_ro": "Registrul e acum închis.",
        "review_run_id": treated,
    }
    with Session(engine) as session, session.begin():
        append_event(
            session, "media.director_scene_brief", "storyboard", ids["board"], 1, record_in, ladder
        )

    got = by_run(engine)
    no = got[("agent.run_completed", refused)]
    assert no["bubble_ro"] == "Am refuzat rescrierea scenei 4: nu tratează constatarea."
    assert no["words_ro"] == (
        f"{sarah['name']} a refuzat rescrierea scenei 4 din «{TITLE}»: nu tratează constatarea "
        "(Promptul cere tot registrul deschis la cifre)."
    )
    yes = got[("agent.run_completed", treated)]
    assert yes["bubble_ro"] == "Rescrierea scenei 3 tratează constatarea ✓"
    assert yes["words_ro"] == (
        f"{sarah['name']} a verificat rescrierea scenei 3 din «{TITLE}»: tratează constatarea."
    )
    assert "cumpăra" not in yes["words_ro"]


def test_an_answer_her_review_refused_is_never_said_as_her_verdict(engine):
    """2026-10-12 (review of a9f84ea): a MISSES was read from an answer the validator refused,
    and the office announced a refusal she never made. An answer that her review's schema does
    not accept, or one that `structured_run` asked again (its next run is «+again»), says no
    verdict; a run the record names without a verdict (her review could not be made) says none
    either, whatever its answer held."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    ladder = str(uuid4())
    summary = (
        "Verific dacă rescrierea scenei {scene} din «Storyboard: " + TITLE + "» tratează "
        "constatările înainte să cumpărăm ceva pe ea."
    )
    # A MISSES whose untreated finding says no why_not: refused by her review's schema.
    invalid = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        summary.format(scene=2),
        ladder,
        output_text=(
            '{"verdict": "MISSES", "findings": [{"finding": "lettering on the ledger", '
            '"treated": false}], "reason_ro": "Promptul cere tot registrul deschis la cifre."}'
        ),
        started_at="2026-10-12T13:40:00.000001+00:00",
    )
    # A well-formed MISSES that was asked again all the same: the next run is its retry.
    asked_again = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        summary.format(scene=5),
        ladder,
        output_text=review_answer("MISSES", "Registrul e deschis."),
        started_at="2026-10-12T13:41:00.000001+00:00",
    )
    retry = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        summary.format(scene=5) + " (a doua încercare, cu motivele refuzului)",
        ladder,
        output_text=review_answer("TREATS", "Registrul e închis."),
        template="rewrite-review-v1+again",
        started_at="2026-10-12T13:42:00.000001+00:00",
    )
    # Named by her brief with no verdict: her review could not be made.
    unmade = a_run(
        engine,
        sarah["id"],
        "director_rewrite_review",
        summary.format(scene=6),
        ladder,
        output_text=review_answer("MISSES", "Registrul e deschis."),
        started_at="2026-10-12T13:43:00.000001+00:00",
    )
    for run_id in (invalid, asked_again, retry, unmade):
        run_events(engine, sarah["id"], run_id, "director_rewrite_review", ladder)
    brief = {"scene_index": 6, "layer": "still", "rewritten": False, "review_run_id": unmade}
    with Session(engine) as session, session.begin():
        append_event(
            session, "media.director_scene_brief", "storyboard", ids["board"], 1, brief, ladder
        )

    got = by_run(engine)
    for run_id, scene in ((invalid, 2), (asked_again, 5), (unmade, 6)):
        done = got[("agent.run_completed", run_id)]
        assert "refuzat" not in done["words_ro"] and "tratează" not in done["words_ro"], done
        assert done["bubble_ro"].startswith(f"Gata: verificarea rescrierii scenei {scene} din «")
    # The retry's own answer is the one her review accepted.
    assert got[("agent.run_completed", retry)]["bubble_ro"] == (
        "Rescrierea scenei 5 tratează constatarea ✓"
    )


def test_each_round_of_her_review_is_said_from_the_record(engine):
    """Her brief keeps every round of his rewrites with her verdict (1839dcf): the first
    round's MISSES is said as hers even when its answer is no longer readable, and the stored
    rewrite's ``review.refused`` names the reviews she refused before the one that passed."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    ladder = str(uuid4())
    summary = (
        "Verific dacă rescrierea scenei 7 din «Storyboard: " + TITLE + "» tratează "
        "constatările înainte să cumpărăm ceva pe ea."
    )
    first = a_run(engine, sarah["id"], "director_rewrite_review", summary, ladder)
    second = a_run(engine, sarah["id"], "director_rewrite_review", summary, ladder)
    for run_id in (first, second):
        run_events(engine, sarah["id"], run_id, "director_rewrite_review", ladder)
    stored = {
        "storyboard_id": ids["board"],
        "scene_index": 7,
        "reason": "director_brief",
        "layer": "still",
        "review": {
            "verdict": "TREATS",
            "reason_ro": "Registrul e închis acum.",
            "run_id": second,
            "refused": [{"round": 1, "review_run_id": first, "reason_ro": "Registrul e deschis."}],
        },
    }
    with Session(engine) as session, session.begin():
        append_event(
            session, "media.prompts_rewritten", "storyboard", ids["board"], 1, stored, ladder
        )

    got = by_run(engine)
    assert got[("agent.run_completed", first)]["words_ro"] == (
        f"{sarah['name']} a refuzat rescrierea scenei 7 din «{TITLE}»: nu tratează constatarea "
        "(Registrul e deschis)."
    )
    assert got[("agent.run_completed", second)]["bubble_ro"] == (
        "Rescrierea scenei 7 tratează constatarea ✓"
    )


def test_her_second_look_at_a_refusal_says_the_scene_the_film_and_what_follows(engine):
    """The Owner, 2026-10-12: «trece imaginile picate de la QC pe la Directoare și să decidă
    dacă au picat corect sau nu și dacă trebuie refăcute». Her second look is said with its
    scene and its film: a wrong refusal is accepted and nothing is bought, a right one is
    redone, a small defect she confirms is accepted, a look she could not take leaves the
    refusal standing. Her run is said with its scene while she looks.

    Review of 68fa0b4, 2026-10-12: a defect she judged real but minor was said as «refuzul
    controlului e greșit»; only a refusal of a defect not in the picture (severity none) is a
    wrong one. A look she could not take says its short why once, not her whole reason."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    unseen_reason = (
        "Directoarea nu s-a putut uita la imaginea: niciun model care vede. Refuzul controlului "
        "rămâne."
    )
    looks = {
        "accepted": {"kind": "still", "verdict": "OVERTURNED", "severity": "none", "redo": False},
        "minor": {"kind": "still", "verdict": "OVERTURNED", "severity": "minor", "redo": False},
        "redone": {"kind": "shot", "verdict": "CONFIRMED", "severity": "serious", "redo": True},
        "small": {"kind": "film_scene", "verdict": "CONFIRMED", "severity": "minor", "redo": False},
        "unseen": {"kind": "still", "verdict": "UNAVAILABLE", "severity": "none", "redo": True},
    }
    said: dict[str, dict[str, Any]] = {}
    for scene, (label, look) in enumerate(looks.items(), start=1):
        correlation = str(uuid4())
        run_id = a_run(engine, sarah["id"], "director_second_look", "Mă uit din nou.", correlation)
        run_events(engine, sarah["id"], run_id, "director_second_look", correlation)
        payload = {
            "storyboard_id": ids["board"],
            "scene_index": scene,
            "take_ids": [str(uuid4())],
            "refusal": ["lettering on the ledger"],
            "reason_ro": "Registrul e gol" if label != "unseen" else unseen_reason,
            "run_id": run_id,
            **look,
        }
        with Session(engine) as session, session.begin():
            append_event(
                session,
                "media.director_second_look",
                "storyboard",
                ids["board"],
                1,
                payload,
                correlation,
            )
        said[label] = {"run": run_id, "scene": scene}

    events = [
        e for e in read_events(engine, 0, 200)["events"] if e["event_type"].endswith("second_look")
    ]
    by_scene = {e["payload"]["scene_index"]: e for e in events}
    name = sarah["name"]
    assert by_scene[1]["words_ro"] == (
        f"{name} s-a uitat la imaginea scenei 1 din «{TITLE}»: refuzul controlului e greșit — "
        "se acceptă, nu se reface (Registrul e gol)."
    )
    assert by_scene[1]["bubble_ro"] == f"M-am uitat la scena 1 din «{TITLE}»: se acceptă."
    assert by_scene[1]["actor"]["agent_id"] == sarah["id"]
    assert by_scene[2]["words_ro"] == (
        f"{name} s-a uitat la imaginea scenei 2 din «{TITLE}»: defectul e real, dar mic — se "
        "acceptă, nu se reface (Registrul e gol)."
    )
    assert "refuzul controlului e greșit" not in by_scene[2]["words_ro"]
    assert by_scene[3]["words_ro"] == (
        f"{name} s-a uitat la clipul scenei 3 din «{TITLE}»: refuzul e corect — se reface "
        "(Registrul e gol)."
    )
    assert by_scene[3]["bubble_ro"] == f"M-am uitat la scena 3 din «{TITLE}»: se reface."
    assert by_scene[4]["words_ro"] == (
        f"{name} s-a uitat la cadrele scenei 4 din «{TITLE}»: defectul e real, dar mic — se "
        "acceptă, nu se reface (Registrul e gol)."
    )
    assert by_scene[5]["words_ro"] == (
        f"{name} nu s-a putut uita la imaginea scenei 5 din «{TITLE}»: refuzul controlului "
        "rămâne (niciun model care vede)."
    )
    assert "bubble_ro" not in by_scene[5]
    for event in events:
        assert len(event.get("bubble_ro") or "") <= 64
    # Her run, placed by the event that names it.
    got = by_run(engine)
    working = got[("agent.state_changed", said["redone"]["run"])]
    assert working["words_ro"] == (
        f"{name} lucrează la a doua privire asupra scenei 3 din «{TITLE}»."
    )
    assert working["bubble_ro"].startswith("Lucrez la a doua privire asupra scenei 3 din «The")
    assert len(working["bubble_ro"]) <= 64


def test_a_check_names_its_scene_a_long_title_is_shortened_and_an_unplaced_run_keeps_its_words(
    engine,
):
    """A still check names its scene and the film its correlation names; a title too long for
    the bubble is shortened inside its quotes, never the scene; a correlation naming two films
    names neither; a run with no summary is said as before."""
    ids = studio(engine)
    kael = ids["agents"]["VideoEditor"]
    long_title = "Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk"
    with Session(engine) as session, session.begin():
        script_id = session.get(Storyboard, ids["board"]).script_draft_id
        long_board = str(uuid4())
        session.add(
            Storyboard(
                id=long_board,
                script_draft_id=script_id,
                title=f"Storyboard: {long_title}",
                status="APPROVED",
                total_scenes=5,
                visual_bible_json={},
                created_at=utc_now(),
            )
        )
    gate = str(uuid4())
    record_board = {"storyboard_id": long_board, "scene_number": 5, "kind": "still"}
    with Session(engine) as session, session.begin():
        append_event(
            session, "media.scene_take_recorded", "scene_take", str(uuid4()), 1, record_board, gate
        )
    still = a_run(
        engine,
        kael["id"],
        "still_qc",
        "Mă uit la imaginea scenei 5 înainte să se cumpere mișcarea.",
        gate,
    )
    run_events(engine, kael["id"], still, "still_qc", gate)

    two_films = str(uuid4())
    with Session(engine) as session, session.begin():
        for board in (ids["board"], long_board):
            append_event(
                session,
                "media.scene_take_recorded",
                "scene_take",
                str(uuid4()),
                1,
                {"storyboard_id": board, "scene_number": 2, "kind": "motion"},
                two_films,
            )
    clip = a_run(
        engine,
        kael["id"],
        "clip_qc",
        "Mă uit la clipul scenei 2 înainte să intre în film.",
        two_films,
    )
    run_events(engine, kael["id"], clip, "clip_qc", two_films)
    unplaced = a_run(engine, kael["id"], "scene_prompt_rewrite", "", str(uuid4()))
    run_events(engine, kael["id"], unplaced, "scene_prompt_rewrite", str(uuid4()))

    got = by_run(engine)
    checked = got[("agent.run_completed", still)]
    assert checked["words_ro"] == (
        f"{kael['name']} a terminat verificarea imaginii scenei 5 din «{long_title}»: reușită "
        "(cu kimi-k3)."
    )
    bubble = checked["bubble_ro"]
    assert len(bubble) <= 64
    assert bubble.startswith("Gata: verificarea imaginii scenei 5 din «Why Ernest")
    assert bubble.endswith("…» ✓")
    assert got[("agent.run_completed", clip)]["bubble_ro"] == (
        "Gata: verificarea clipului scenei 2 ✓"
    )
    assert got[("agent.run_completed", unplaced)]["bubble_ro"] == (
        "Gata: rescrierea promptului unei scene ✓"
    )
    assert got[("agent.state_changed", unplaced)]["bubble_ro"] == (
        "Lucrez la rescrierea promptului unei scene."
    )


def test_a_clip_her_look_kept_reads_as_kept_never_as_refused(engine):
    """Review of 68fa0b4, 2026-10-12: a clip quality control refused and her second look kept
    (``accepted_by`` director_look, the take approved by her look) was said «nu a trecut
    controlul». It is the film's clip: said as kept, with her reason."""
    ids = studio(engine)
    look = {
        "verdict": "OVERTURNED",
        "severity": "minor",
        "redo": False,
        "reason_ro": "Mâna se mișcă puțin, dar fața rămâne aceeași.",
        "run_id": str(uuid4()),
    }
    record(
        engine,
        "media.clip_qc_checked",
        ("scene_take", str(uuid4())),
        {
            "storyboard_id": ids["board"],
            "scene_number": 3,
            "take_id": str(uuid4()),
            "attempt": 1,
            "scene": 3,
            "passed": False,
            "verdict": "PASSED",
            "blocks_ro": ["Fața se deformează în secunda a doua."],
            "accepted_by": "director_look",
            "director_look": look,
        },
    )
    clip = page(engine)["media.clip_qc_checked"]
    assert clip["words_ro"] == (
        f"Clipul scenei 3 din «{TITLE}» a fost păstrat de Directoare: controlul l-a refuzat, dar "
        "defectul e mic — se acceptă (Mâna se mișcă puțin, dar fața rămâne aceeași)."
    )
    assert "nu a trecut" not in clip["words_ro"]
    assert clip["bubble_ro"] == "Clipul scenei 3 păstrat ✓"


def test_her_reading_of_a_new_lesson_says_what_it_corrects(engine):
    """A new prompt lesson read beside the live ones (`prompt_agent.LESSON_READ_EVENT`): by
    her, what it corrects (retired) and repeats; by the words when she could not read it."""
    ids = studio(engine)
    sarah = ids["agents"]["Director"]
    record(
        engine,
        "media.prompt_lesson_read",
        ("memory_record", str(uuid4())),
        {
            "lesson": "Ask for a slow drift while the subject moves.",
            "scope": "serial",
            "read_by": "director",
            "agent_id": sarah["id"],
            "run_id": str(uuid4()),
            "corrects": ["Keep the camera static."],
            "repeats": [],
            "absorbed_into": None,
            "unavailable": None,
        },
    )
    read = page(engine)["media.prompt_lesson_read"]
    assert read["actor"]["agent_id"] == sarah["id"]
    assert read["words_ro"] == (
        f"{sarah['name']} a citit lecția nouă «Ask for a slow drift while the subject moves»: "
        "corectează «Keep the camera static» (retrasă)."
    )
    assert read["bubble_ro"] == "Am citit o lecție nouă."
