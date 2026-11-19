from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.business_calendar import as_utc
from app.deadlines import scan_deadlines
from app.models import AuditEvent, Case, DeadlineAlert, utc_now
from tests.conftest import auth
from tests.test_business_calendar import dt
from tests.test_service import service
from tests.test_workflow import post, working


@pytest.fixture
def timed_case(client, engine, payload):
    c = working(client, payload)
    with Session(engine) as s:
        row = s.get(Case, c["id"])
        clock = row.clocks[0]
        clock.started_at = as_utc(dt("2026-11-20T09:00:00+05:30"))
        clock.response_due_at = as_utc(dt("2026-11-20T11:00:00+05:30"))
        clock.resolution_due_at = as_utc(dt("2026-11-20T17:00:00+05:30"))
        clock.action_due_at = clock.resolution_due_at
        clock.action_at = None
        s.commit()
    return c


def scan(engine, at):
    with Session(engine) as s:
        return scan_deadlines(s, dt(at))


def test_warning_overdue_restart_dedup_and_acknowledgement(client, engine, timed_case):
    assert scan(engine, "2026-11-20T10:29:00+05:30")["created"] == 0
    assert scan(engine, "2026-11-20T10:30:00+05:30")["created"] == 1
    assert scan(engine, "2026-11-20T10:45:00+05:30")["created"] == 0
    assert scan(engine, "2026-11-20T11:00:00+05:30")["created"] == 0
    assert scan(engine, "2026-11-20T11:00:01+05:30")["created"] == 1
    assert scan(engine, "2026-11-20T17:01:00+05:30")["created"] == 2
    assert scan(engine, "2026-11-23T12:00:00+05:30")["created"] == 0
    alerts = client.get("/alerts", headers=auth("auditor")).json()
    assert len(alerts) == 4
    alert_id = alerts[0]["id"]
    assert client.post(f"/alerts/{alert_id}/acknowledge", headers=auth("agent")).status_code == 403
    response = client.post(f"/alerts/{alert_id}/acknowledge", headers=auth("manager"))
    assert response.status_code == 200 and response.json()["acknowledged_by"] == "demo-manager"
    assert (
        client.post(f"/alerts/{alert_id}/acknowledge", headers=auth("manager")).status_code == 200
    )
    events = client.get(f"/cases/{timed_case['id']}/audit", headers=auth()).json()
    assert sum(e["action"] == "alert.acknowledged" for e in events) == 1
    assert sum(e["actor"] == "system-worker" for e in events) == 4
    assert (
        client.get(f"/cases/{timed_case['id']}", headers=auth()).json()["version"]
        == timed_case["version"]
    )


def test_late_completed_response_is_recovered_after_restart(engine, timed_case):
    with Session(engine) as s:
        c = s.get(Case, timed_case["id"])
        c.clocks[0].first_response_at = as_utc(dt("2026-11-20T11:05:00+05:30"))
        c.clocks[0].action_at = as_utc(dt("2026-11-20T09:15:00+05:30"))
        c.clocks[0].stopped_at = as_utc(dt("2026-11-20T12:00:00+05:30"))
        c.status = "closed"
        s.commit()
    assert scan(engine, "2026-11-23T12:00:00+05:30")["created"] == 1
    assert scan(engine, "2026-11-23T12:01:00+05:30")["created"] == 0


def test_met_response_and_resolution_do_not_generate_false_breaches(engine, timed_case):
    with Session(engine) as s:
        c = s.get(Case, timed_case["id"])
        c.clocks[0].first_response_at = as_utc(dt("2026-11-20T10:00:00+05:30"))
        c.clocks[0].action_at = c.clocks[0].first_response_at
        c.clocks[0].stopped_at = as_utc(dt("2026-11-20T16:00:00+05:30"))
        c.status = "closed"
        s.commit()
    assert scan(engine, "2026-11-23T12:00:00+05:30")["created"] == 0


def test_paused_resolution_does_not_hide_response_or_action_deadline(engine, timed_case):
    with Session(engine) as s:
        c = s.get(Case, timed_case["id"])
        c.clocks[0].paused_at = as_utc(dt("2026-11-20T10:00:00+05:30"))
        c.status = "awaiting_customer"
        s.commit()
    assert scan(engine, "2026-11-20T18:00:00+05:30")["created"] == 2
    with Session(engine) as s:
        assert "resolution" not in set(s.scalars(select(DeadlineAlert.source)).all())


def test_task_and_commitment_alerts_rescheduling_preserves_history(client, engine, timed_case):
    c = post(
        client,
        timed_case,
        "follow-ups",
        expected=201,
        unit="charges",
        owner="demo-charges-team",
        description="Synthetic backlog",
        next_action="Obtain record",
        due_at="2026-11-20T10:00:00+05:30",
    )
    c = post(
        client, c, "commitments", description="Check promise", due_at="2026-11-20T10:00:00+05:30"
    )
    scan(engine, "2026-11-20T10:01:00+05:30")
    rows = service(client, c)["alerts"]
    assert {a["source"] for a in rows} == {"followup", "commitment"}
    task = service(client, c)["followups"][0]
    c = post(
        client,
        c,
        f"follow-ups/{task['id']}/review",
        note="Approved follow-up reschedule",
        next_action="Escalate to supervisor",
        due_at="2026-11-23T10:00:00+05:30",
    )
    scan(engine, "2026-11-23T10:01:00+05:30")
    followups = [a for a in service(client, c)["alerts"] if a["source"] == "followup"]
    assert len(followups) == 2 and followups[0]["target_at"] != followups[1]["target_at"]


def test_scanner_audit_failure_rolls_back_alert(engine, timed_case):
    def fail(*_args):
        raise SQLAlchemyError("injected audit failure")

    event.listen(AuditEvent, "before_insert", fail)
    try:
        with pytest.raises(SQLAlchemyError):
            scan(engine, "2026-11-20T12:00:00+05:30")
    finally:
        event.remove(AuditEvent, "before_insert", fail)
    with Session(engine) as s:
        assert s.scalar(select(func.count()).select_from(DeadlineAlert)) == 0
    assert scan(engine, "2026-11-20T12:00:00+05:30")["created"] == 1


def test_manual_scan_permissions(client, timed_case):
    for role in ["agent", "auditor"]:
        assert client.post("/operations/deadline-scan", headers=auth(role)).status_code == 403
    assert client.post("/operations/deadline-scan", headers=auth("manager")).status_code == 200


def test_postgres_simultaneous_scanners_do_not_duplicate_alerts(payload):
    from app.config import get_settings
    from app.main import app

    url = get_settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("Requires migrated PostgreSQL database")
    with TestClient(app) as client:
        case = working(client, payload | {"source_message_id": f"scanner-race-{uuid4()}"})
    engine = create_engine(url)
    barrier = Barrier(2, timeout=10)
    when = utc_now() + timedelta(days=60)

    def run(_):
        with Session(engine) as session:
            barrier.wait()
            return scan_deadlines(session, when)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(r["created"] for r in results) >= 2
    with Session(engine) as s:
        alerts = s.scalars(select(DeadlineAlert).where(DeadlineAlert.case_id == case["id"])).all()
        assert len(alerts) == 2
        assert {a.source for a in alerts} == {"first_response", "resolution"}
        assert len({a.dedup_key for a in alerts}) == 2
    engine.dispose()


def test_reschedule_during_worker_downtime_does_not_erase_old_breach(client, engine, payload):
    from app.business_calendar import iso

    c = working(client, payload)
    previous_due = utc_now() - timedelta(hours=2)
    c = post(
        client,
        c,
        "follow-ups",
        expected=201,
        unit="charges",
        owner="demo-charges-team",
        description="Late synthetic backlog",
        next_action="Request input",
        due_at=iso(previous_due),
    )
    task = service(client, c)["followups"][0]
    c = post(
        client,
        c,
        f"follow-ups/{task['id']}/review",
        note="Record overdue backlog before rescheduling",
        next_action="Supervisor follow-up",
        due_at=iso(utc_now() + timedelta(days=7)),
    )
    with Session(engine) as session:
        scan_deadlines(session, utc_now() + timedelta(seconds=1))
    alerts = [a for a in service(client, c)["alerts"] if a["source"] == "followup"]
    assert len(alerts) == 1 and alerts[0]["level"] == "overdue"
    assert alerts[0]["target_at"] == iso(previous_due)


def test_worker_startup_catches_up_and_failure_logs_no_sensitive_details(
    engine, timed_case, monkeypatch, caplog
):
    import app.worker as worker

    monkeypatch.setattr(worker, "get_engine", lambda: engine)
    monkeypatch.setattr(worker, "utc_now", lambda: dt("2026-11-20T12:00:00+05:30"))
    assert worker.run_check()["created"] == 1
    assert worker.run_check()["created"] == 0

    def unavailable():
        raise RuntimeError("private-credential-example")

    monkeypatch.setattr(worker, "get_engine", unavailable)
    assert worker.run_check() is None
    assert "private-credential-example" not in caplog.text
