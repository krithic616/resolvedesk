"""Business invariants, access controls, audit atomicity, and stale-edit protection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import AuditEvent, Case
from tests.conftest import auth


def create(client, payload):
    r = client.post("/cases", json=payload, headers=auth())
    assert r.status_code == 201, r.text
    return r.json()


def post(client, case, path, role="agent", expected=200, **fields):
    r = client.post(
        f"/cases/{case['id']}/{path}",
        headers=auth(role),
        json={"expected_version": case["version"], **fields},
    )
    assert r.status_code == expected, r.text
    return r.json()


def working(client, payload):
    c = create(client, payload)
    c = post(client, c, "assignment", owner="demo-agent")
    return post(client, c, "transition", target="in_progress", reason="Begin investigation")


def answer_all(client, case):
    for query in case["queries"]:
        r = client.put(
            f"/cases/{case['id']}/queries/{query['id']}",
            headers=auth(),
            json={
                "expected_version": case["version"],
                "disposition": "answered",
                "answer": "Synthetic explanation; no live banking action performed.",
                "evidence_reference": "DEMO-POLICY-001 section 2",
            },
        )
        assert r.status_code == 200, r.text
        case = r.json()
    return case


def test_full_resolution_close_and_reopen(client, payload):
    c = working(client, payload)
    assert c["owner"] == "demo-agent" and c["version"] == 3
    post(client, c, "resolve", resolution_note="Incomplete", expected=409)
    c = answer_all(client, c)
    c = post(client, c, "resolve", resolution_note="All synthetic questions explained.")
    assert c["status"] == "resolved" and c["resolved_at"].endswith("Z")
    c = post(client, c, "transition", target="closed", reason="Resolution recorded and reviewed")
    assert c["closure_reason"]
    c = post(client, c, "reopen", reason="Customer requires a fresh review")
    assert c["status"] == "in_progress" and c["resolution_note"] is None
    assert c["resolved_at"] is None and c["closure_reason"] is None
    assert all(q["disposition"] == "open" and q["answer"] is None for q in c["queries"])
    post(client, c, "resolve", resolution_note="No fresh review", expected=409)
    events = client.get(f"/cases/{c['id']}/audit", headers=auth("auditor")).json()
    assert len(events) == c["version"]
    assert events[-1]["details"]["previous"]["queries"][0]["answer"]
    assert events[-1]["details"]["reason"] == "Customer requires a fresh review"


def test_dependencies_and_wait_states_block_resolution(client, payload):
    c = working(client, payload)
    q = c["queries"][0]
    r = client.put(
        f"/cases/{c['id']}/queries/{q['id']}",
        headers=auth(),
        json={
            "expected_version": c["version"],
            "disposition": "waiting",
            "dependency": "Charges unit must supply the synthetic charge reason",
        },
    )
    assert r.status_code == 200
    c = r.json()
    post(client, c, "resolve", resolution_note="Not complete", expected=409)
    c = post(
        client,
        c,
        "follow-ups",
        expected=201,
        unit="charges",
        owner="demo-charges-team",
        description="Investigate charge",
        next_action="Contact charges team",
    )
    task = client.get(f"/cases/{c['id']}/service", headers=auth()).json()["followups"][0]
    c = post(client, c, "transition", target="awaiting_business_unit", reason="Unit input required")
    post(client, c, "resolve", resolution_note="Still waiting", expected=409)
    c = answer_all(client, c)
    c = post(
        client,
        c,
        f"follow-ups/{task['id']}/complete",
        completion_note="Synthetic unit input received",
    )
    c = post(client, c, "transition", target="in_progress", reason="Unit input received")
    assert (
        post(client, c, "resolve", resolution_note="Verified synthetic answers")["status"]
        == "resolved"
    )


def test_manager_review_and_owner_permissions(client, payload):
    c = answer_all(client, working(client, payload))
    c = post(client, c, "transition", target="pending_review", reason="Review proposed decline")
    post(client, c, "resolve", resolution_note="Agent approval", expected=403)
    post(client, c, "transition", target="in_progress", reason="Bypass review", expected=403)
    q = c["queries"][0]
    assert (
        client.put(
            f"/cases/{c['id']}/queries/{q['id']}",
            headers=auth(),
            json={"expected_version": c["version"], "disposition": "open"},
        ).status_code
        == 409
    )
    c = post(
        client,
        c,
        "transition",
        role="manager",
        target="in_progress",
        reason="Further checks required",
    )
    c = post(client, c, "assignment", role="manager", owner="demo-manager")
    post(client, c, "resolve", resolution_note="Not owner", expected=403)
    post(client, c, "assignment", owner="demo-agent", expected=403)
    c = post(
        client, c, "transition", role="manager", target="pending_review", reason="Checks complete"
    )
    assert (
        post(client, c, "resolve", role="manager", resolution_note="Manager reviewed evidence")[
            "status"
        ]
        == "resolved"
    )


def test_commitment_blocks_resolution_until_completed_and_normalizes_utc(client, payload):
    c = answer_all(client, working(client, payload))
    c = post(
        client,
        c,
        "commitments",
        description="Confirm the synthetic explanation",
        due_at="2026-12-01T18:00:00+05:30",
    )
    commitment = c["commitments"][0]
    assert commitment["due_at"] == "2026-12-01T12:30:00Z"
    post(client, c, "resolve", resolution_note="Outstanding promise", expected=409)
    c = post(
        client,
        c,
        f"commitments/{commitment['id']}/complete",
        completion_note="Confirmation recorded",
    )
    post(
        client,
        c,
        f"commitments/{commitment['id']}/complete",
        completion_note="Duplicate completion",
        expected=409,
    )
    assert (
        post(client, c, "resolve", resolution_note="All obligations complete")["status"]
        == "resolved"
    )


def test_stale_edit_has_no_side_effect(client, engine, payload):
    stale = working(client, payload)
    current = post(
        client, stale, "commitments", description="Track response", due_at="2026-12-01T12:00:00Z"
    )
    post(client, stale, "transition", target="awaiting_customer", reason="Stale edit", expected=409)
    with Session(engine) as s:
        row = s.get(Case, current["id"])
        assert row.status == "in_progress" and row.version == current["version"]
        assert s.scalar(select(func.count()).select_from(AuditEvent)) == current["version"]


@pytest.mark.parametrize(
    "path, fields",
    [
        ("assignment", {"owner": "demo-agent"}),
        ("transition", {"target": "in_progress", "reason": "Attempt"}),
        ("resolve", {"resolution_note": "Attempt"}),
        ("reopen", {"reason": "Attempt"}),
        ("commitments", {"description": "Attempt", "due_at": "2026-12-01T12:00:00Z"}),
        ("commitments/123/complete", {"completion_note": "Attempt"}),
    ],
)
def test_auditor_cannot_mutate_workflow(client, payload, path, fields):
    c = create(client, payload)
    post(client, c, path, role="auditor", expected=403, **fields)
    r = client.put(
        f"/cases/{c['id']}/queries/{c['queries'][0]['id']}",
        headers=auth("auditor"),
        json={"expected_version": 1, "disposition": "open"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "fields",
    [
        {"disposition": "answered", "answer": "Unsupported answer"},
        {"disposition": "answered", "answer": " ", "evidence_reference": "DEMO"},
        {"disposition": "waiting"},
        {"disposition": "open", "answer": "Contradictory state"},
        {
            "disposition": "answered",
            "answer": "Answer",
            "evidence_reference": "DEMO",
            "dependency": "Still waiting",
        },
    ],
)
def test_invalid_answers_are_rejected(client, payload, fields):
    c = working(client, payload)
    r = client.put(
        f"/cases/{c['id']}/queries/{c['queries'][0]['id']}",
        headers=auth(),
        json={"expected_version": c["version"], **fields},
    )
    assert r.status_code == 422


def test_invalid_transitions_and_cross_case_ids(client, payload):
    c = create(client, payload)
    post(client, c, "transition", target="closed", reason="Premature close", expected=403)
    post(client, c, "assignment", owner="demo-manager", expected=403)
    post(client, c, "assignment", owner="unknown", expected=422)
    c = post(client, c, "assignment", owner="demo-agent")
    post(client, c, "resolve", resolution_note="Before starting", expected=409)
    c = post(client, c, "transition", target="in_progress", reason="Start")
    post(client, c, "transition", target="closed", reason="Premature close", expected=409)
    other = create(client, payload | {"source_message_id": "other"})
    assert (
        client.put(
            f"/cases/{c['id']}/queries/{other['queries'][0]['id']}",
            headers=auth(),
            json={"expected_version": c["version"], "disposition": "open"},
        ).status_code
        == 404
    )
    post(client, c, "commitments/999/complete", completion_note="Missing", expected=404)
    post(
        client,
        c,
        "commitments",
        description="No timezone",
        due_at="2026-12-01T12:00:00",
        expected=422,
    )
    post(client, c, "reopen", reason="Already active", expected=409)


def test_workflow_audit_failure_rolls_back_answer_and_version(client, engine, payload):
    c = working(client, payload)

    def fail(*_args):
        raise SQLAlchemyError("Sensitive database detail")

    event.listen(AuditEvent, "before_insert", fail)
    try:
        r = client.put(
            f"/cases/{c['id']}/queries/{c['queries'][0]['id']}",
            headers=auth(),
            json={
                "expected_version": c["version"],
                "disposition": "answered",
                "answer": "Synthetic answer",
                "evidence_reference": "DEMO",
            },
        )
        assert r.status_code == 503 and "Sensitive database detail" not in r.text
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    with Session(engine) as s:
        row = s.get(Case, c["id"])
        assert row.version == c["version"] and row.queries[0].answer is None


def test_postgres_simultaneous_workflow_updates(monkeypatch, payload):
    import app.main as api
    from app.config import get_settings
    from app.main import app

    if not get_settings().database_url.startswith("postgresql"):
        pytest.skip("Requires migrated PostgreSQL database")
    with TestClient(app) as client:
        c = working(client, payload | {"source_message_id": f"workflow-race-{uuid4()}"})
        barrier = Barrier(2, timeout=10)
        original = api.commit_change

        def synchronized(*args, **kwargs):
            barrier.wait()
            return original(*args, **kwargs)

        monkeypatch.setattr(api, "commit_change", synchronized)

        def write(reason):
            return client.post(
                f"/cases/{c['id']}/transition",
                headers=auth(),
                json={
                    "expected_version": c["version"],
                    "target": "awaiting_customer",
                    "reason": reason,
                },
            ).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(write, ["First editor", "Second editor"])) == [200, 409]
        saved = client.get(f"/cases/{c['id']}", headers=auth()).json()
        events = client.get(f"/cases/{c['id']}/audit", headers=auth()).json()
        assert saved["version"] == c["version"] + 1
        assert len(events) == saved["version"]
