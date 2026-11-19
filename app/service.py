"""Persisted deadline cycles; policy snapshots prevent retroactive target changes."""

from fastapi import HTTPException
from sqlalchemy import select

from app.business_calendar import BusinessCalendar, as_utc, iso
from app.models import ServiceClock, ServicePolicy
from app.service_schemas import PolicyConfig


def active_policy(session):
    with session.no_autoflush:
        policy = session.scalar(select(ServicePolicy).order_by(ServicePolicy.id.desc()).limit(1))
    if policy:
        return {"policy_id": policy.id, "name": policy.name, "configuration": policy.configuration}
    return {
        "policy_id": 0,
        "name": "DEMO-IST-V1",
        "configuration": PolicyConfig().model_dump(mode="json"),
    }


def current_clock(case):
    return case.clocks[-1] if case.clocks else None


def require_clock(case):
    clock = current_clock(case)
    if clock is None:
        raise HTTPException(
            409, "Ask a manager to activate service tracking for this existing case"
        )
    return clock


def start_clock(case, session, now):
    snapshot = active_policy(session)
    config = dict(snapshot["configuration"])
    config.update(config.get("category_targets", {}).get(case.category, {}))
    snapshot = {**snapshot, "configuration": config, "category": case.category}
    calendar = BusinessCalendar(config)
    clock = ServiceClock(
        cycle=max((c.cycle for c in case.clocks), default=0) + 1,
        policy_snapshot=snapshot,
        started_at=as_utc(now),
        response_due_at=calendar.add_seconds(now, config["response_minutes"] * 60),
        resolution_due_at=calendar.add_seconds(now, config["resolution_minutes"] * 60),
    )
    if case.owner:
        clock.action_due_at = calendar.action_cutoff(now)
    case.clocks.append(clock)
    return clock


def mark_action(case, now):
    clock = current_clock(case)
    if clock and not clock.action_at and clock.action_due_at:
        clock.action_at = as_utc(now)


def on_assignment(case, now):
    clock = current_clock(case)
    if clock and not clock.action_due_at:
        clock.action_due_at = BusinessCalendar(
            clock.policy_snapshot["configuration"]
        ).action_cutoff(now)


def effective_resolution_due(clock, now):
    if not clock.paused_at:
        return as_utc(clock.resolution_due_at)
    calendar = BusinessCalendar(clock.policy_snapshot["configuration"])
    return calendar.add_seconds(
        clock.resolution_due_at, calendar.seconds_between(clock.paused_at, now)
    )


def resume_clock(clock, now):
    if clock and clock.paused_at:
        clock.resolution_due_at = effective_resolution_due(clock, now)
        clock.paused_at = None


def on_transition(case, previous, now):
    clock = current_clock(case)
    if clock:
        if previous == "awaiting_customer":
            resume_clock(clock, now)
        if (
            case.status == "awaiting_customer"
            and clock.policy_snapshot["configuration"]["pause_on_customer"]
            and as_utc(now) <= as_utc(clock.resolution_due_at)
        ):
            clock.paused_at = as_utc(now)
    if case.status == "in_progress":
        mark_action(case, now)


def stop_clock(case, now):
    clock = current_clock(case)
    if clock:
        resume_clock(clock, now)
        clock.stopped_at = as_utc(now)


def deadline_state(due, completed, now, stopped=None):
    if due is None:
        return "not_started"
    due = as_utc(due)
    if completed:
        return "met" if as_utc(completed) <= due else "late"
    horizon = min(as_utc(now), as_utc(stopped)) if stopped else as_utc(now)
    if horizon > due:
        return "overdue"
    return "not_recorded" if stopped else "pending"


def clock_view(clock, now):
    due = effective_resolution_due(clock, now)
    return {
        "id": clock.id,
        "cycle": clock.cycle,
        "policy_snapshot": clock.policy_snapshot,
        "started_at": iso(clock.started_at),
        "response_due_at": iso(clock.response_due_at),
        "resolution_due_at": iso(due),
        "action_due_at": iso(clock.action_due_at),
        "first_response_at": iso(clock.first_response_at),
        "action_at": iso(clock.action_at),
        "paused_at": iso(clock.paused_at),
        "stopped_at": iso(clock.stopped_at),
        "response_state": deadline_state(
            clock.response_due_at, clock.first_response_at, now, clock.stopped_at
        ),
        "action_state": deadline_state(clock.action_due_at, clock.action_at, now, clock.stopped_at),
        "resolution_state": "paused"
        if clock.paused_at
        else deadline_state(due, clock.stopped_at, now),
    }
