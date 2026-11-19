"""Durable internal reminders and escalations; scanning is safe to repeat after restart."""

from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.business_calendar import BusinessCalendar, as_utc
from app.models import AuditEvent, Case, DeadlineAlert
from app.service import effective_resolution_due


def scan_deadlines(session, now):
    """One atomic scan. Advisory/SQLite write locks serialize concurrent scanners."""
    now = as_utc(now)
    if session.bind.dialect.name == "postgresql":
        locked = session.scalar(select(func.pg_try_advisory_xact_lock(81763201)))
        if not locked:
            session.rollback()
            return {"created": 0, "busy": True}
    elif session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    count = 0
    cases = session.scalars(
        select(Case).options(
            selectinload(Case.clocks), selectinload(Case.followups), selectinload(Case.commitments)
        )
    ).all()

    def check(case_id, source, source_id, generation, due, completed, stopped, config):
        nonlocal count
        if due is None:
            return
        due = as_utc(due)
        finished = completed or stopped
        finished = as_utc(finished) if finished else None
        horizon = min(now, finished) if finished else now
        if horizon > due:
            level = "overdue"
        elif (not finished or finished > now) and BusinessCalendar(config).seconds_between(
            now, due
        ) <= config["warning_minutes"] * 60:
            level = "warning"
        else:
            return
        key = f"{case_id}:{source}:{source_id}:{generation}:{level}"
        if session.scalar(select(DeadlineAlert.id).where(DeadlineAlert.dedup_key == key)):
            return
        try:
            with session.begin_nested():
                alert = DeadlineAlert(
                    case_id=case_id,
                    dedup_key=key,
                    source=source,
                    source_id=source_id,
                    level=level,
                    target_at=due,
                    created_at=now,
                    message=f"{source} deadline {level}; manager review required"
                    if level == "overdue"
                    else f"{source} deadline approaching; owner follow-up required",
                )
                session.add(alert)
                session.flush()
                session.add(
                    AuditEvent(
                        case_id=case_id,
                        actor="system-worker",
                        action=f"deadline.{level}",
                        details={
                            "alert_id": alert.id,
                            "source": source,
                            "source_id": source_id,
                            "generation": generation,
                            "target_at": due.isoformat(),
                        },
                        created_at=now,
                    )
                )
                session.flush()
            count += 1
        except IntegrityError:
            if not session.scalar(select(DeadlineAlert.id).where(DeadlineAlert.dedup_key == key)):
                raise

    reviews = session.scalars(
        select(AuditEvent).where(AuditEvent.action == "followup.reviewed")
    ).all()
    review_history = {}
    for entry in reviews:
        review_history.setdefault(entry.case_id, []).append(entry)
    for case in cases:
        if not case.clocks:
            continue
        for clock in case.clocks:
            config = clock.policy_snapshot["configuration"]
            check(
                case.id,
                "first_response",
                clock.id,
                clock.cycle,
                clock.response_due_at,
                clock.first_response_at,
                clock.stopped_at,
                config,
            )
            check(
                case.id,
                "same_day_action",
                clock.id,
                clock.cycle,
                clock.action_due_at,
                clock.action_at,
                clock.stopped_at,
                config,
            )
            if not clock.paused_at:
                check(
                    case.id,
                    "resolution",
                    clock.id,
                    clock.cycle,
                    effective_resolution_due(clock, now),
                    clock.stopped_at,
                    None,
                    config,
                )
        config = case.clocks[-1].policy_snapshot["configuration"]
        for task in case.followups:
            check(
                case.id,
                "followup",
                task.id,
                task.schedule_version,
                task.due_at,
                task.completed_at,
                None,
                config,
            )
        # A reschedule ends the old schedule, not its audit evidence. Recover an
        # old breach even if the worker was offline when the deadline was moved.
        for entry in review_history.get(case.id, []):
            before, after = entry.details["before"], entry.details["after"]
            if before["due_at"] != after["due_at"]:
                check(
                    case.id,
                    "followup",
                    before["id"],
                    before["schedule_version"],
                    datetime.fromisoformat(before["due_at"].replace("Z", "+00:00")),
                    entry.created_at,
                    None,
                    config,
                )
        for commitment in case.commitments:
            check(
                case.id,
                "commitment",
                commitment.id,
                1,
                commitment.due_at,
                commitment.completed_at,
                None,
                config,
            )
    session.commit()
    return {"created": count, "busy": False}
