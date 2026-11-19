from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.business_calendar import as_utc, iso
from app.models import ServiceClock
from app.service import clock_view, on_transition
from app.service_schemas import PolicyConfig
from tests.conftest import auth
from tests.test_business_calendar import dt
from tests.test_workflow import answer_all, create, post, working


def service(client, case):
    r = client.get(f"/cases/{case['id']}/service", headers=auth())
    assert r.status_code == 200
    return r.json()


def test_policy_snapshot_does_not_change_open_cases(client, payload):
    old = create(client, payload)
    config = PolicyConfig(response_minutes=60, resolution_minutes=240).model_dump(mode="json")
    assert (
        client.post(
            "/service-policies", headers=auth("agent"), json={"name": "V2", "configuration": config}
        ).status_code
        == 403
    )
    r = client.post(
        "/service-policies", headers=auth("manager"), json={"name": "V2", "configuration": config}
    )
    assert r.status_code == 201
    assert (
        client.post(
            "/service-policies",
            headers=auth("manager"),
            json={"name": "V2", "configuration": config},
        ).status_code
        == 409
    )
    new = create(client, payload | {"source_message_id": "new-policy-case"})
    assert (
        service(client, old)["clocks"][0]["policy_snapshot"]["configuration"]["response_minutes"]
        == 120
    )
    assert (
        service(client, new)["clocks"][0]["policy_snapshot"]["configuration"]["response_minutes"]
        == 60
    )
    assert client.get("/service-policies", headers=auth("auditor")).json()["active"]["name"] == "V2"


def test_first_response_is_simulated_and_does_not_extend_resolution(client, payload):
    c = working(client, payload)
    before = service(client, c)["clocks"][0]
    c = post(client, c, "first-response", note="Synthetic acknowledgement reviewed")
    after = service(client, c)["clocks"][0]
    assert after["first_response_at"] and after["response_state"] == "met"
    assert before["resolution_due_at"] == after["resolution_due_at"]
    post(client, c, "first-response", note="Duplicate", expected=409)
    assert after["action_at"]


def test_nfcr_task_ownership_review_reschedule_completion(client, payload):
    c = working(client, payload)
    post(
        client, c, "transition", target="awaiting_business_unit", reason="No task yet", expected=409
    )
    c = post(
        client,
        c,
        "follow-ups",
        expected=201,
        unit="charges",
        owner="demo-charges-team",
        description="Explain the synthetic fee",
        next_action="Request charge record",
    )
    task = service(client, c)["followups"][0]
    assert task["due_at"].endswith("Z") and task["schedule_version"] == 1
    c = post(
        client, c, "transition", target="awaiting_business_unit", reason="Awaiting charges unit"
    )
    c = post(
        client,
        c,
        f"follow-ups/{task['id']}/review",
        note="Unit acknowledged request",
        next_action="Obtain approved explanation",
        owner="demo-charges-supervisor",
        due_at="2026-12-01T11:00:00+05:30",
    )
    revised = service(client, c)["followups"][0]
    assert revised["schedule_version"] == 2 and revised["due_at"] == "2026-12-01T05:30:00Z"
    c = post(client, c, "transition", target="in_progress", reason="Prepare final resolution")
    c = answer_all(client, c)
    post(client, c, "resolve", resolution_note="Open follow-up", expected=409)
    c = post(
        client,
        c,
        f"follow-ups/{task['id']}/complete",
        completion_note="Synthetic evidence received",
    )
    post(client, c, f"follow-ups/{task['id']}/complete", completion_note="Duplicate", expected=409)
    c = post(client, c, "resolve", resolution_note="All synthetic questions and tasks addressed")
    assert c["status"] == "resolved"
    clock = service(client, c)["clocks"][0]
    assert clock["stopped_at"]


def test_reopen_starts_fresh_cycle_preserving_previous_deadlines(client, payload):
    c = answer_all(client, working(client, payload))
    c = post(client, c, "resolve", resolution_note="Synthetic resolution")
    old = deepcopy(service(client, c)["clocks"][0])
    c = post(client, c, "reopen", reason="Fresh customer questions")
    clocks = service(client, c)["clocks"]
    assert len(clocks) == 2 and clocks[1]["cycle"] == 2
    assert clocks[0] == old
    assert clocks[1]["first_response_at"] is None and clocks[1]["stopped_at"] is None


def test_legacy_activation_is_explicit_and_manager_only(client, engine, payload):
    c = working(client, payload)
    with Session(engine) as s:
        s.execute(delete(ServiceClock).where(ServiceClock.case_id == c["id"]))
        s.commit()
    assert not service(client, c)["tracked"]
    post(client, c, "service-clock/start", expected=403)
    c = post(client, c, "service-clock/start", role="manager")
    assert service(client, c)["tracked"]
    post(client, c, "service-clock/start", role="manager", expected=409)


@pytest.mark.parametrize(
    "path,fields",
    [
        ("first-response", {"note": "Attempt"}),
        ("service-clock/start", {}),
        (
            "follow-ups",
            {
                "unit": "charges",
                "owner": "demo-charges-team",
                "description": "Attempt",
                "next_action": "Contact",
            },
        ),
        ("follow-ups/1/review", {"note": "Attempt", "next_action": "Contact"}),
        ("follow-ups/1/complete", {"completion_note": "Attempt"}),
    ],
)
def test_auditor_cannot_change_service_records(client, payload, path, fields):
    c = working(client, payload)
    post(client, c, path, role="auditor", expected=403, **fields)


def test_followup_validation_and_cross_case_ids(client, payload):
    c = working(client, payload)
    fields = {
        "unit": "charges",
        "owner": "demo-charges-team",
        "description": "Input",
        "next_action": "Contact",
    }
    post(client, c, "follow-ups", expected=422, **(fields | {"due_at": "2026-11-20T11:00:00"}))
    post(client, c, "follow-ups", expected=422, **(fields | {"owner": ""}))
    other = working(client, payload | {"source_message_id": "other-case"})
    other = post(client, other, "follow-ups", expected=201, **fields)
    task = service(client, other)["followups"][0]
    post(client, c, f"follow-ups/{task['id']}/complete", completion_note="Wrong case", expected=404)
    c = post(client, c, "follow-ups", expected=201, **fields)
    post(
        client, c | {"version": c["version"] - 1}, "first-response", note="Stale edit", expected=409
    )


def test_customer_pause_counts_working_time_only_and_does_not_pause_response():
    config = PolicyConfig(pause_on_customer=True).model_dump(mode="json")
    clock = ServiceClock(
        policy_snapshot={"configuration": config},
        started_at=dt("2026-11-20T09:00:00+05:30"),
        response_due_at=dt("2026-11-20T11:00:00+05:30"),
        resolution_due_at=dt("2026-11-20T17:00:00+05:30"),
    )
    case = SimpleNamespace(clocks=[clock], status="awaiting_customer")
    on_transition(case, "in_progress", dt("2026-11-20T10:00:00+05:30"))
    assert clock.paused_at
    view = clock_view(clock, dt("2026-11-23T10:00:00+05:30"))
    assert view["resolution_state"] == "paused" and view["response_state"] == "overdue"
    case.status = "in_progress"
    on_transition(case, "awaiting_customer", dt("2026-11-23T10:00:00+05:30"))
    assert clock.paused_at is None
    assert iso(clock.resolution_due_at) == "2026-11-23T11:30:00Z"
    assert iso(clock.response_due_at) == "2026-11-20T05:30:00Z"


@pytest.mark.parametrize("pause_enabled,late", [(False, False), (True, True)])
def test_waiting_customer_cannot_hide_existing_breach(pause_enabled, late):
    config = PolicyConfig(pause_on_customer=pause_enabled).model_dump(mode="json")
    due = dt("2026-11-20T17:00:00+05:30")
    clock = ServiceClock(policy_snapshot={"configuration": config}, resolution_due_at=due)
    case = SimpleNamespace(clocks=[clock], status="awaiting_customer")
    on_transition(case, "in_progress", as_utc(due) + timedelta(seconds=1 if late else -1))
    assert clock.paused_at is None


def test_category_specific_targets_and_reassignment_keeps_deadlines(client, payload):
    config = PolicyConfig(
        category_targets={
            "charges": {"response_minutes": 30, "resolution_minutes": 240, "followup_minutes": 60}
        }
    ).model_dump(mode="json")
    assert (
        client.post(
            "/service-policies",
            headers=auth("manager"),
            json={"name": "CATEGORY-V1", "configuration": config},
        ).status_code
        == 201
    )
    c = working(client, payload)
    clock = service(client, c)["clocks"][0]
    assert clock["policy_snapshot"]["configuration"]["response_minutes"] == 30
    other = create(client, payload | {"source_message_id": "card-case", "category": "cards"})
    assert (
        service(client, other)["clocks"][0]["policy_snapshot"]["configuration"]["response_minutes"]
        == 120
    )
    c = post(client, c, "assignment", role="manager", owner="demo-manager")
    after = service(client, c)["clocks"][0]
    assert after["response_due_at"] == clock["response_due_at"]
    assert after["action_due_at"] == clock["action_due_at"]
