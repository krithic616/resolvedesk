"""Version-checked case workflow. Every mutation and audit event commit atomically."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditEvent, Case, utc_now

ACTIVE_STATES = {
    "assigned",
    "in_progress",
    "awaiting_business_unit",
    "awaiting_customer",
    "pending_review",
}
EDITABLE_STATES = {"in_progress", "awaiting_business_unit", "awaiting_customer"}
TRANSITIONS = {
    "assigned": {"in_progress"},
    "in_progress": {"awaiting_business_unit", "awaiting_customer", "pending_review"},
    "awaiting_business_unit": {"in_progress"},
    "awaiting_customer": {"in_progress"},
    "pending_review": {"in_progress"},
    "resolved": {"closed"},
}


def find_case(case_id: str, session: Session):
    case = session.scalar(
        select(Case)
        .options(selectinload(Case.queries), selectinload(Case.commitments))
        .where(Case.id == case_id)
    )
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def editable_case(case_id: str, expected: int, role: str, session: Session, owner_required=True):
    case = find_case(case_id, session)
    if case.version != expected:
        raise HTTPException(409, "Case changed; refresh before editing")
    if owner_required and role != "manager" and case.owner != f"demo-{role}":
        raise HTTPException(403, "Only the case owner or a manager can change this case")
    return case


def commit_change(case, role, action, details, session):
    # Explicitly dirty the parent for query/commitment edits as well. SQLAlchemy's
    # version column adds an atomic WHERE version = old_version to the UPDATE.
    case.version += 1
    session.add(
        AuditEvent(
            case_id=case.id,
            actor=f"demo-{role}",
            action=action,
            details={**details, "case_version": case.version},
        )
    )
    session.commit()
    session.refresh(case)
    return case


def ensure_editable(case):
    if case.status not in EDITABLE_STATES:
        raise HTTPException(409, "Start or resume work before changing questions or commitments")


def query_snapshot(query):
    return {
        "id": query.id,
        "disposition": query.disposition,
        "answer": query.answer,
        "evidence_reference": query.evidence_reference,
        "dependency": query.dependency,
    }


def resolve(case, note, role):
    if case.status not in {"in_progress", "pending_review"}:
        raise HTTPException(409, "Only an in-progress or reviewed case can be resolved")
    if case.status == "pending_review" and role != "manager":
        raise HTTPException(403, "A manager must decide a case awaiting review")
    if any(
        q.disposition != "answered" or not q.answer or not q.evidence_reference
        for q in case.queries
    ):
        raise HTTPException(409, "Answer every customer question with an evidence reference first")
    if any(c.completed_at is None for c in case.commitments):
        raise HTTPException(409, "Complete all customer commitments before resolution")
    case.status = "resolved"
    case.resolution_note = note
    case.resolved_at = utc_now()
