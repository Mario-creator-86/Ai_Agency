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
