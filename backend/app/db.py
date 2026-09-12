from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.engine import make_url

from app.config import ROOT

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def lock_for_write(session: "Session") -> None:
    """Take SQLite's write lock now, before this transaction reads anything.

    SQLite's deferred BEGIN takes a read snapshot at the first SELECT. A transaction that
    reads and then writes asks to upgrade that snapshot, and if anything committed in between
    SQLite refuses **immediately** — "database is locked" with the lock already free and
    `busy_timeout` irrelevant, because no amount of waiting makes an old snapshot writable.
    Measured: the write fails in 0.00s after the other connection has committed and closed.
    Two watched runs died that way, both updating one agent's runtime state while the outbox
    dispatcher committed beside them once a second.

    `BEGIN IMMEDIATE` for every transaction would fix it and cannot be used: the studio opens a
    writing session inside an open reading session in many places (the economy suite is full of
    them), and there the inner write waits on the outer read's own lock until it times out —
    measured at 32.8 seconds, then the same error. So the lock is taken here, per transaction,
    by the transactions that know they are going to write: a no-op UPDATE of the policy row.
    From then on the transaction is a writer, later writes cannot be refused, and anyone else
    waits their turn (which `busy_timeout` covers) instead of failing outright.

    Call it as the FIRST statement of a write transaction, and keep that transaction short —
    it holds the studio's write lock until it commits.
    """
    session.execute(text("UPDATE owner_policy SET version = version WHERE id = 1"))


def create_db_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        raise ValueError("Foundation supports SQLite; PostgreSQL requires a tested migration phase")
    if not url.database or url.database == ":memory:":
        raise ValueError("Use a file-backed database for durable studio state")
    path = Path(url.database)
    if not path.is_absolute():
        path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    url = url.set(database=str(path.resolve()))
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 10})

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: object, record: object) -> None:
        # Explicit BEGIN below also makes reads/snapshots transactional on older sqlite3 drivers.
        connection.isolation_level = None  # type: ignore[attr-defined]
        cursor = connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        # Long enough for a writer to finish while another waits. It was ten seconds, and a
        # four-minute script stage died on "database is locked" while updating one agent's
        # runtime state: the stage writes dozens of small transactions as it works, the outbox
        # dispatcher writes once a second beside it, and a WAL checkpoint takes the write lock
        # for as long as it needs. Thirty seconds costs nothing when nothing is contended.
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def explicit_begin(connection: object) -> None:
        # Deferred, deliberately. BEGIN IMMEDIATE would take the write lock up front and make
        # a waiting writer wait instead of failing — but the studio opens a writing session
        # inside an open reading session in a dozen places, and under IMMEDIATE the inner
        # write waits on the outer read's own lock until `busy_timeout` expires and then
        # fails. Measured: 32.8 seconds, then the same "database is locked" it was meant to
        # cure. Deferred keeps those nested sessions working; contention is handled by the
        # timeout below.
        connection.exec_driver_sql("BEGIN")  # type: ignore[attr-defined]

    return engine


def migrate(engine: Engine, revision: str = "head") -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    with engine.connect() as connection:
        # Batch migrations rebuild a table (copy, drop, rename). With foreign keys enforced,
        # SQLite refuses to drop a table that other rows still reference, so a migration that
        # passed on an empty database failed on a studio with YouTube channels bound to
        # channel records. Enforcement is suspended for this connection only, outside the
        # transaction (the pragma is a no-op inside one), and the result is checked before
        # it comes back on — the recipe SQLite and Alembic document for table rebuilds.
        raw = connection.connection.driver_connection
        if raw is None:
            raise RuntimeError("The migration connection has no SQLite driver connection")
        raw.execute("PRAGMA foreign_keys=OFF")
        try:
            with connection.begin():
                config.attributes["connection"] = connection
                command.upgrade(config, revision)
            violations = raw.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                tables = sorted({str(row[0]) for row in violations})
                raise RuntimeError("Migration left foreign key violations in: " + ", ".join(tables))
        finally:
            raw.execute("PRAGMA foreign_keys=ON")
