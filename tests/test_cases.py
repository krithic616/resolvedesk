from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import AuditEvent, Case, QueryItem
from tests.conftest import auth


def test_authentication_required(client, payload):
    assert client.post("/cases", json=payload).status_code == 401
    assert client.get("/cases").status_code == 401
    assert client.get("/cases", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/cases", headers={"Authorization": "Basic invalid"}).status_code == 401


def test_case_query_and_audit_are_persisted(client, engine, payload):
    response = client.post("/cases", json=payload, headers=auth())
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "new"
    assert len(data["queries"]) == 2
    assert data["created_at"].endswith("Z")
    assert (
        client.get(f"/cases/{data['id']}", headers=auth("auditor")).json()["body"]
        == payload["body"]
    )
    events = client.get(f"/cases/{data['id']}/audit", headers=auth("auditor")).json()
    assert [(e["actor"], e["action"]) for e in events] == [("demo-agent", "case.created")]
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(QueryItem)) == 2


def test_duplicate_does_not_create_queries_or_audit_events(client, engine, payload):
    assert client.post("/cases", json=payload, headers=auth()).status_code == 201
    assert client.post("/cases", json=payload, headers=auth()).status_code == 409
    with Session(engine) as s:
        for model, count in [(Case, 1), (QueryItem, 2), (AuditEvent, 1)]:
            assert s.scalar(select(func.count()).select_from(model)) == count


def test_read_only_auditor_and_manager_write(client, payload):
    assert client.post("/cases", json=payload, headers=auth("auditor")).status_code == 403
    assert client.post("/cases", json=payload, headers=auth("manager")).status_code == 201
    page = client.get("/cases", headers=auth("auditor")).json()
    assert page["total"] == 1
    assert "body" not in page["items"][0]
    assert "customer_reference" not in page["items"][0]


@pytest.mark.parametrize(
    "change",
    [
        {"questions": []},
        {"questions": ["  "]},
        {"questions": ["Question", " question "]},
        {"questions": ["x" * 1001]},
        {"questions": [str(i) for i in range(11)]},
        {"customer_reference": "real-account-123"},
        {"subject": " "},
        {"category": "unknown"},
        {"status": "closed"},
        {"body": "x" * 20001},
    ],
)
def test_invalid_input_has_no_side_effects(client, engine, payload, change):
    response = client.post("/cases", json=payload | change, headers=auth())
    assert response.status_code == 422
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Case)) == 0


def test_validation_does_not_echo_customer_content(client, payload):
    response = client.post(
        "/cases", json=payload | {"customer_reference": "PRIVATE-CONTENT"}, headers=auth()
    )
    assert "PRIVATE-CONTENT" not in response.text


def test_pagination_and_not_found(client, payload):
    for n in range(3):
        assert (
            client.post(
                "/cases", json=payload | {"source_message_id": str(n)}, headers=auth()
            ).status_code
            == 201
        )
    first = client.get("/cases?limit=2", headers=auth()).json()
    second = client.get("/cases?limit=2&offset=2", headers=auth()).json()
    assert first["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert {x["id"] for x in first["items"]}.isdisjoint(x["id"] for x in second["items"])
    assert client.get("/cases?limit=101", headers=auth()).status_code == 422
    assert client.get("/cases?offset=-1", headers=auth()).status_code == 422
    assert client.get("/cases/missing", headers=auth()).status_code == 404
    assert client.get("/cases/missing/audit", headers=auth()).status_code == 404


def test_weak_or_reused_keys_are_rejected():
    with pytest.raises(ValueError):
        Settings(agent_api_key="short", manager_api_key="b" * 40, auditor_api_key="c" * 40)
    with pytest.raises(ValueError):
        Settings(agent_api_key="a" * 40, manager_api_key="a" * 40, auditor_api_key="c" * 40)


def test_live_and_ready(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_postgres_concurrent_duplicate_intake(payload):
    """Use the migrated PostgreSQL database when available (CI or local integration run)."""
    from app.config import get_settings
    from app.main import app

    url = get_settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration requires DATABASE_URL")
    source = f"concurrency-test-{uuid4()}"
    payload = payload | {"source_message_id": source}
    with TestClient(app) as c:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(
                pool.map(
                    lambda _: c.post("/cases", json=payload, headers=auth()).status_code, range(2)
                )
            )
        assert sorted(statuses) == [201, 409]
    engine = create_engine(url)
    with Session(engine) as s:
        case = s.scalar(select(Case).where(Case.source_message_id == source))
        assert len(case.queries) == 2
        assert (
            s.scalar(
                select(func.count()).select_from(AuditEvent).where(AuditEvent.case_id == case.id)
            )
            == 1
        )
    engine.dispose()


def test_audit_failure_rolls_back_entire_intake(client, engine, payload):
    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    def fail_audit(*_args):
        raise SQLAlchemyError("internal-sensitive-error")

    event.listen(AuditEvent, "before_insert", fail_audit)
    try:
        response = client.post("/cases", json=payload, headers=auth())
        assert response.status_code == 503
        assert "internal-sensitive-error" not in response.text
    finally:
        event.remove(AuditEvent, "before_insert", fail_audit)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(Case)) == 0
        assert s.scalar(select(func.count()).select_from(QueryItem)) == 0
