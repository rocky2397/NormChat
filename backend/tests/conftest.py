import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import settings
from db.database import Base, get_db
from main import app
from models.project import Project


@pytest.fixture(autouse=True)
def auth_gate_off_unless_a_test_asks_for_it(monkeypatch):
    """Pin the login gate off, so no test depends on the developer's machine.

    `Settings` reads `backend/.env` at import time (`config.py`), and that file
    is gitignored -- so it exists locally and never in CI. Any test reaching an
    `/api` route therefore passed in CI and returned 401 for anyone who had set
    AUTH_USERNAME for their own use, which is how nine tests came to fail only
    outside CI.

    The tests that exercise the gate set the credentials in their own body,
    which runs after this fixture; this removes only the ambient dependency on
    an untracked file, not the ability to test authentication.
    """
    monkeypatch.setattr(settings, "auth_username", "")
    monkeypatch.setattr(settings, "auth_password", "")


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    from models.document import Document  # noqa: F401
    from models.feedback import ChatFeedback  # noqa: F401

    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def project(db_session):
    project = Project(name="Testprojekt")
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)
    return project
