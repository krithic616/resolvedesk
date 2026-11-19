"""Servicing endpoints; NFCR ownership, follow-up reviews, and persisted clocks."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_role, require_writer
from app.business_calendar import BusinessCalendar, iso
from app.db import get_session
from app.models import AuditEvent, DeadlineAlert, FollowUp, ServicePolicy, utc_now
from app.schemas import CaseView, VersionedWrite
from app.service import (
    active_policy,
    clock_view,
    current_clock,
    mark_action,
    require_clock,
    start_clock,
)
from app.service_schemas import (
    FirstResponse,
    FollowUpComplete,
    FollowUpCreate,
    FollowUpReview,
    PolicyCreate,
)
from app.workflow import commit_change, editable_case, ensure_editable, find_case

router = APIRouter()


def manager(role: str = Depends(get_role)):
    if role != "manager":
        raise HTTPException(403, "Manager access required")
    return role


def task_view(task):
    return {
        "id": task.id,
        "unit": task.unit,
        "owner": task.owner,
        "description": task.description,
        "next_action": task.next_action,
        "due_at": iso(task.due_at),
        "schedule_version": task.schedule_version,
        "completed_at": iso(task.completed_at),
        "completion_note": task.completion_note,
    }


def alert_view(alert):
    return {
        "id": alert.id,
        "case_id": alert.case_id,
        "source": alert.source,
        "source_id": alert.source_id,
        "level": alert.level,
        "target_at": iso(alert.target_at),
        "message": alert.message,
        "created_at": iso(alert.created_at),
        "acknowledged_at": iso(alert.acknowledged_at),
        "acknowledged_by": alert.acknowledged_by,
    }


@router.get("/service-policies")
def policies(_role: str = Depends(get_role), session: Session = Depends(get_session)):
    rows = session.scalars(select(ServicePolicy).order_by(ServicePolicy.id.desc())).all()
    return {
        "active": active_policy(session),
        "published": [
            {
                "policy_id": row.id,
                "name": row.name,
                "configuration": row.configuration,
                "created_by": row.created_by,
                "created_at": iso(row.created_at),
            }
            for row in rows
        ],
    }


@router.post("/service-policies", status_code=201)
def publish_policy(
    payload: PolicyCreate, _role: str = Depends(manager), session: Session = Depends(get_session)
):
    if payload.name == "DEMO-IST-V1":
        raise HTTPException(409, "The built-in policy name is reserved; use a new version name")
    row = ServicePolicy(
        name=payload.name,
        configuration=payload.configuration.model_dump(mode="json"),
        created_by="demo-manager",
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Policy name already exists; publish a new version name") from None
    session.refresh(row)
    return {"policy_id": row.id, "name": row.name, "configuration": row.configuration}


@router.get("/cases/{case_id}/service")
def service_detail(
    case_id: str, _role: str = Depends(get_role), session: Session = Depends(get_session)
):
    case = find_case(case_id, session)
    alerts = session.scalars(
        select(DeadlineAlert)
        .where(DeadlineAlert.case_id == case_id)
        .order_by(DeadlineAlert.id.desc())
        .limit(200)
    ).all()
    return {
        "tracked": bool(case.clocks),
        "clocks": [clock_view(c, utc_now()) for c in case.clocks],
        "followups": [task_view(t) for t in case.followups],
        "alerts": [alert_view(a) for a in alerts],
    }


@router.post("/cases/{case_id}/service-clock/start", response_model=CaseView)
def activate(
    case_id: str,
    payload: VersionedWrite,
    role: str = Depends(manager),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    if case.status in {"resolved", "closed"} or current_clock(case):
        raise HTTPException(409, "Only an active, untracked legacy case can start service tracking")
    clock = start_clock(case, session, utc_now())
    return commit_change(case, role, "service.started", {"policy": clock.policy_snapshot}, session)


@router.post("/cases/{case_id}/first-response", response_model=CaseView)
def first_response(
    case_id: str,
    payload: FirstResponse,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    if case.status in {"new", "resolved", "closed"}:
        raise HTTPException(409, "Record a simulated response only on an assigned active case")
    clock = require_clock(case)
    if clock.first_response_at:
        raise HTTPException(409, "First response already recorded for this service cycle")
    clock.first_response_at = utc_now()
    mark_action(case, clock.first_response_at)
    return commit_change(
        case, role, "response.simulated", {"note": payload.note, "cycle": clock.cycle}, session
    )


@router.post("/cases/{case_id}/follow-ups", response_model=CaseView, status_code=201)
def create_task(
    case_id: str,
    payload: FollowUpCreate,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    clock = require_clock(case)
    now = utc_now()
    config = clock.policy_snapshot["configuration"]
    due = payload.due_at or BusinessCalendar(config).add_seconds(
        now, config["followup_minutes"] * 60
    )
    task = FollowUp(
        **payload.model_dump(exclude={"expected_version", "due_at"}), due_at=due, schedule_version=1
    )
    case.followups.append(task)
    mark_action(case, now)
    return commit_change(
        case,
        role,
        "followup.created",
        {
            "unit": payload.unit,
            "owner": payload.owner,
            "next_action": payload.next_action,
            "description": payload.description,
            "due_at": iso(due),
        },
        session,
    )


def task_in_case(case, task_id):
    task = next((t for t in case.followups if t.id == task_id), None)
    if task is None:
        raise HTTPException(404, "Follow-up task not found in this case")
    if task.completed_at:
        raise HTTPException(409, "Follow-up task already completed")
    return task


@router.post("/cases/{case_id}/follow-ups/{task_id}/review", response_model=CaseView)
def review_task(
    case_id: str,
    task_id: int,
    payload: FollowUpReview,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    task = task_in_case(case, task_id)
    before = task_view(task)
    task.next_action = payload.next_action
    if payload.owner:
        task.owner = payload.owner
    if payload.due_at and iso(payload.due_at) != iso(task.due_at):
        task.due_at = payload.due_at
        task.schedule_version += 1
    mark_action(case, utc_now())
    return commit_change(
        case,
        role,
        "followup.reviewed",
        {"before": before, "after": task_view(task), "note": payload.note},
        session,
    )


@router.post("/cases/{case_id}/follow-ups/{task_id}/complete", response_model=CaseView)
def complete_task(
    case_id: str,
    task_id: int,
    payload: FollowUpComplete,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    task = task_in_case(case, task_id)
    task.completed_at = utc_now()
    task.completion_note = payload.completion_note
    mark_action(case, task.completed_at)
    return commit_change(
        case,
        role,
        "followup.completed",
        {"task_id": task.id, "note": payload.completion_note},
        session,
    )


@router.get("/alerts")
def alerts(_role: str = Depends(get_role), session: Session = Depends(get_session)):
    return [
        alert_view(a)
        for a in session.scalars(select(DeadlineAlert).order_by(DeadlineAlert.id.desc()).limit(200))
    ]


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge(
    alert_id: int, _role: str = Depends(manager), session: Session = Depends(get_session)
):
    alert = session.get(DeadlineAlert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    changed = session.execute(
        update(DeadlineAlert)
        .where(DeadlineAlert.id == alert_id, DeadlineAlert.acknowledged_at.is_(None))
        .values(acknowledged_at=utc_now(), acknowledged_by="demo-manager")
    )
    if changed.rowcount:
        session.add(
            AuditEvent(
                case_id=alert.case_id,
                actor="demo-manager",
                action="alert.acknowledged",
                details={"alert_id": alert_id},
            )
        )
    session.commit()
    session.refresh(alert)
    return alert_view(alert)


@router.post("/operations/deadline-scan")
def run_deadline_scan(_role: str = Depends(manager), session: Session = Depends(get_session)):
    from app.deadlines import scan_deadlines

    return scan_deadlines(session, utc_now())
