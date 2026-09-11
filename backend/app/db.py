from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url

from app.config import ROOT


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
        cursor.execute("PRAGMA busy_timeout=10000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def explicit_begin(connection: object) -> None:
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
