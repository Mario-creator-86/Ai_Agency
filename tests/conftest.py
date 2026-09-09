import secrets

import pytest
from app.config import Settings
from app.db import create_db_engine, migrate
from app.main import create_app
from app.services import bootstrap_studio
from fastapi.testclient import TestClient


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        owner_token=secrets.token_urlsafe(48),
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        allowed_hosts=["testserver", "127.0.0.1"],
    )


@pytest.fixture
def engine(settings):
    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings)
    yield engine
    engine.dispose()


@pytest.fixture
def headers(settings):
    return {"Authorization": f"Bearer {settings.owner_token.get_secret_value()}"}


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings)) as client:
        yield client
