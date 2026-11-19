import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("AGENT_API_KEY", "test-agent-" + "a" * 40)
os.environ.setdefault("MANAGER_API_KEY", "test-manager-" + "b" * 40)
os.environ.setdefault("AUDITOR_API_KEY", "test-auditor-" + "c" * 40)

from app.db import Base, get_session  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def client(engine):
    def override_session():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def payload():
    return {
        "source_message_id": "demo-email-001",
        "customer_reference": "SYN-001",
        "subject": "Please explain this charge",
        "body": "Please explain my fee and review a waiver.",
        "category": "charges",
        "questions": ["Why was this fee charged?", "Can it be waived?"],
    }


def auth(role="agent"):
    return {"Authorization": "Bearer " + os.environ[f"{role.upper()}_API_KEY"]}
