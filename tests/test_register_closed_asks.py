"""The studio closing its own stale asks, in sentences (the Owner's register, 2026-10-17).

At 00:50:56 (Bucharest) the register showed «Angajați: ask expired.», the raw name of the
``agent.ask_expired`` event, above «Studioul a închis fără răspuns o cerere — Blocaje foaie: …»,
both for one act of the studio's sweep (`agents.inbox.expire_stale_asks`), which writes the
answer event (``expired``) and the closing for every ask it closes. The page now draws no row
for either (`frontend/src/ledger.js` isBookkeeping); the words are for any place that still
lists them: one true Romanian sentence per reason, with the ask's subject and addressee read
for the whole page at once — never the event's name, and never «fără răspuns» for a repeated
ask, whose newest copy stays open. No model is called.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.agents.inbox import (
    ANSWER_FAILED,
    DUPLICATE,
    EPISODE_CLOSED,
    EXPIRED,
    EXPIRED_EVENT,
    FILM_CLOSED,
    STALE_ASK_DAYS,
    TOPIC_REJECTED,
    expire_stale_asks,
)
from app.agents.mail import note_failed_answer
from app.agents.messages import EXPIRED_BY, post_message, resolve_message
from app.events_feed import enrich
from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import Storyboard
from app.services import append_event, read_events, utc_now
from app.workflows.publisher import ConnectionManager, publish_pending_outbox
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session
from test_context_profiles import (
    ago,
    staffed,  # noqa: F401 - the fixture
)

TITLE = "The Zero Script Club"
RAW = ("ask expired", "ask_expired", "message answered", "Angajați:", "kept_message_id")


def _board(engine) -> str:
    """A storyboard whose title the register names (the media stage writes «Storyboard: …»)."""
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
                title=f"Storyboard: {TITLE}",
                status="APPROVED",
                total_scenes=3,
                visual_bible_json={},
                created_at=now,
            )
        )
    return ids["board"]


def _ask(engine, staffed, subject: str, *, to: str = "ScriptWriter", days_old: int = 0) -> str:  # noqa: F811
    sarah, addressee = staffed["agents"]["Director"], staffed["agents"][to]
    with Session(engine) as session, session.begin():
        row = post_message(
            session,
            intent="REQUEST_REVIEW",
            subject=subject,
            body={},
            body_text=f"{subject}?",
            from_agent_id=sarah.id,
            to_agent_id=addressee.id,
        )
        if days_old:
            row.created_at = ago(days=days_old)
        return row.id


def _close(engine, message_id: str, reason: str, words: str, detail: dict[str, Any]) -> None:
    """The pair `expire_stale_asks` writes for one ask, for the reasons whose state (a film
    published, an episode rewritten, a topic refused) the test does not build."""
    correlation = str(uuid4())
    with Session(engine) as session, session.begin():
        resolve_message(
            session,
            message_id,
            resolution=words,
            resolved_by=EXPIRED_BY,
            status="ANSWERED",
            correlation_id=correlation,
        )
        append_event(
            session,
            EXPIRED_EVENT,
            "agent_message",
            message_id,
            2,
            {"reason": reason, "resolution": words, **detail},
            correlation,
        )


def _said(engine) -> dict[tuple[str, str], dict[str, Any]]:
    """The record's page: {(event type, message id): the event with its words}."""
    events = read_events(engine, 0, 500)["events"]
    return {
        (e["event_type"], e["aggregate_id"]): e
        for e in events
        if e["event_type"] in (EXPIRED_EVENT, "agent.message_answered")
    }


def _plain(words: str) -> None:
    assert words, "every closing has its sentence"
    for raw in RAW:
        assert raw not in words, words


def test_each_reason_the_studio_closes_an_ask_for_is_said_in_a_sentence(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    marcus = staffed["agents"]["ScriptWriter"].display_name
    sarah = staffed["agents"]["Director"].display_name
    board = _board(engine)
    film = _ask(engine, staffed, f"Blocaje foaie: Storyboard: {TITLE}", to="Director")
    other_film = _ask(engine, staffed, "Remediere înainte de cadre: ScriptWriter")
    episode = _ask(engine, staffed, "Rescris: The Week of Two Videos")
    episode_film = _ask(engine, staffed, "Rescris: The Zero Club")
    topic = _ask(engine, staffed, "De investigat: subiectul zilei")
    _close(
        engine,
        film,
        FILM_CLOSED,
        f"Închisă de studio: filmul «Storyboard: {TITLE}» este încheiat (publicat sau închis); "
        "cererea nu mai are obiect.",
        {"storyboard_id": board},
    )
    _close(
        engine,
        other_film,
        FILM_CLOSED,
        f"Închisă de studio: filmul «Storyboard: {TITLE}» este încheiat (publicat sau închis); "
        "cererea nu mai are obiect.",
        {"storyboard_id": board},
    )
    _close(
        engine,
        episode,
        EPISODE_CLOSED,
        "Închisă de studio: episodul «The Week of Two Videos» a fost înlocuit de o rescriere; "
        "cererea nu mai are obiect.",
        {"episode_id": str(uuid4())},
    )
    _close(
        engine,
        episode_film,
        EPISODE_CLOSED,
        "Închisă de studio: episodul «The Zero Club» are filmul încheiat; cererea nu mai are "
        "obiect.",
        {"episode_id": str(uuid4())},
    )
    _close(
        engine,
        topic,
        TOPIC_REJECTED,
        "Închisă de studio: subiectul «Why Nepal Pays» a fost respins; cererea nu mai are obiect.",
        {"topic_id": str(uuid4())},
    )
    # the three the sweep reaches on its own: an old ask, an old one whose answers failed, and
    # an ask said twice
    old = _ask(engine, staffed, "Ce cârlig merge", days_old=STALE_ASK_DAYS + 2)
    failed = _ask(engine, staffed, "Ce titlu merge", days_old=STALE_ASK_DAYS + 2)
    for _ in range(2):
        note_failed_answer(engine, failed, "context window exceeded", run_status="FAILED")
    repeated = _ask(engine, staffed, f"Repară foaia: Storyboard: {TITLE}", to="VideoEditor")
    newest = _ask(engine, staffed, f"Repară foaia: Storyboard: {TITLE}", to="VideoEditor")
    swept = expire_stale_asks(engine)
    assert swept["by_reason"] == {EXPIRED: 1, ANSWER_FAILED: 1, DUPLICATE: 1}
    assert newest not in swept["expired"]

    said = _said(engine)
    words = {mid: said[(EXPIRED_EVENT, mid)]["words_ro"] for mid in said_ids(said)}
    for sentence in words.values():
        _plain(sentence)
    for closed in said.values():
        assert "bubble_ro" not in closed, "the office says nothing of the studio's bookkeeping"
    kael = staffed["agents"]["VideoEditor"].display_name
    assert words[film] == (
        f"Studioul a închis cererea «Blocaje foaie: {TITLE}» către {sarah}: filmul ei s-a "
        "încheiat (publicat sau închis)."
    )
    assert words[other_film] == (
        f"Studioul a închis cererea «Remediere înainte de cadre: ScriptWriter» către {marcus}: "
        f"filmul «{TITLE}» s-a încheiat (publicat sau închis)."
    )
    assert words[episode] == (
        f"Studioul a închis cererea «Rescris: The Week of Two Videos» către {marcus}: episodul "
        "ei a fost înlocuit de o rescriere."
    )
    assert words[episode_film] == (
        f"Studioul a închis cererea «Rescris: The Zero Club» către {marcus}: episodul ei are "
        "filmul încheiat."
    )
    assert words[topic] == (
        f"Studioul a închis cererea «De investigat: subiectul zilei» către {marcus}: subiectul "
        "«Why Nepal Pays» a fost respins."
    )
    assert words[old] == (
        f"Studioul a închis cererea «Ce cârlig merge» către {marcus}: a stat deschisă mai mult "
        f"de {STALE_ASK_DAYS} zile fără să țină de un film în lucru."
    )
    assert words[failed] == (
        f"Studioul a închis fără răspuns cererea «Ce titlu merge»: modelul lui {marcus} a "
        "încercat să răspundă și n-a reușit (2 încercări eșuate)."
    )
    assert words[repeated] == (
        f"Cererea «Repară foaia: {TITLE}» către {kael} a venit din nou; studioul a închis "
        "copia veche, rămâne deschisă cea mai nouă."
    )
    assert "fără răspuns" not in words[repeated]


def said_ids(said: dict[tuple[str, str], dict[str, Any]]) -> list[str]:
    return [mid for kind, mid in said if kind == EXPIRED_EVENT]


def test_the_answer_event_beside_a_closing_is_said_by_the_closing_s_reason(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    """The answer event the sweep writes beside its closing: a repeated ask's old copy is closed
    while its newest stays open, so it is never «închisă fără răspuns»; any other is. The page
    and the socket say the same — the socket sends the answer alone, without its closing."""
    kael = staffed["agents"]["VideoEditor"].display_name
    marcus = staffed["agents"]["ScriptWriter"].display_name
    _ask(engine, staffed, f"Repară foaia: Storyboard: {TITLE}", to="VideoEditor")
    _ask(engine, staffed, f"Repară foaia: Storyboard: {TITLE}", to="VideoEditor")
    old = _ask(engine, staffed, "Ce cârlig merge", days_old=STALE_ASK_DAYS + 2)
    swept = expire_stale_asks(engine)
    repeated = next(mid for mid in swept["expired"] if mid != old)

    said = _said(engine)
    copy = said[("agent.message_answered", repeated)]
    expected_copy = (
        f"Studioul a închis o copie veche a cererii «Repară foaia: {TITLE}» către {kael}; cea "
        "mai nouă rămâne deschisă."
    )
    assert copy["words_ro"] == expected_copy
    assert said[("agent.message_answered", old)]["words_ro"] == (
        f"Studioul a închis fără răspuns cererea «Ce cârlig merge» către {marcus}."
    )

    manager = _Recorder()
    assert publish_pending_outbox(engine, manager) >= 1
    live = [m["data"] for m in manager.sent if m["data"]["event_type"] == "agent.message_answered"]
    assert {e["aggregate_id"]: e["words_ro"] for e in live}[repeated] == expected_copy
    assert all(e["event_type"] != EXPIRED_EVENT for e in (m["data"] for m in manager.sent))
    # An answer recorded before the event carried ``expired`` is read by its closer.
    older = {**copy, "payload": {k: v for k, v in copy["payload"].items() if k != "expired"}}
    older.pop("words_ro")
    with Session(engine) as session:
        assert enrich(session, [older])[0]["words_ro"] == expected_copy


def test_a_real_answer_names_who_answered_and_the_letter(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    marcus = staffed["agents"]["ScriptWriter"].display_name
    asked = _ask(engine, staffed, "Ce cârlig merge")
    owners = _ask(engine, staffed, "Ce titlu merge")
    with Session(engine) as session, session.begin():
        resolve_message(
            session, asked, resolution="Cel cu cifra.", resolved_by=marcus, status="ANSWERED"
        )
        resolve_message(
            session, owners, resolution="Al doilea.", resolved_by="Owner", status="ANSWERED"
        )
    said = _said(engine)
    assert said[("agent.message_answered", asked)]["words_ro"] == (
        f"{marcus} a răspuns la «Ce cârlig merge»."
    )
    assert said[("agent.message_answered", owners)]["words_ro"] == (
        "Proprietarul a răspuns la «Ce titlu merge»."
    )


def test_the_asks_of_a_whole_page_are_read_in_one_query(
    engine,
    staffed,  # noqa: F811 - the fixture, imported
):
    """Like the films' titles (`_titles`): one read of the letters for the page, never one per
    event (the sweep of 2026-10-16 19:15 closed 117 asks in one second)."""
    for n in range(6):
        _ask(engine, staffed, f"Ce cârlig merge {n}", days_old=STALE_ASK_DAYS + 2)
    assert len(expire_stale_asks(engine)["expired"]) == 6
    letters: list[str] = []

    def seen(_conn, _cursor, statement, *_args) -> None:
        if "FROM agent_message" in statement:
            letters.append(statement)

    sa_event.listen(engine, "before_cursor_execute", seen)
    try:
        page = read_events(engine, 0, 500)["events"]
    finally:
        sa_event.remove(engine, "before_cursor_execute", seen)
    closings = [e for e in page if e["event_type"] == EXPIRED_EVENT]
    assert len(closings) == 6 and all("Ce cârlig merge" in e["words_ro"] for e in closings)
    assert len(letters) == 1, letters


class _Recorder(ConnectionManager):
    """A connection manager that keeps what it was asked to send."""

    def __init__(self) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []

    async def broadcast(self, message: dict[str, Any]) -> int:
        self.sent.append(message)
        return 1
