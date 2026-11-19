"""ResolveDesk milestone 3: authenticated, persistent synthetic case intake."""

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.auth import get_role, require_writer
from app.db import get_session
from app.models import AuditEvent, Case, Commitment, QueryItem, utc_now
from app.schemas import (
    Assignment,
    AuditView,
    CaseCreate,
    CasePage,
    CaseView,
    CommitmentComplete,
    CommitmentCreate,
    QueryUpdate,
    ReopenRequest,
    ResolveRequest,
    Transition,
)
from app.service import mark_action, on_assignment, on_transition, start_clock, stop_clock
from app.workflow import (
    ACTIVE_STATES,
    TRANSITIONS,
    commit_change,
    editable_case,
    ensure_editable,
    find_case,
    query_snapshot,
    resolve,
)

app = FastAPI(title="ResolveDesk", version="0.3.0", description="Synthetic banking service cases")


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # FastAPI's default includes rejected inputs, which can contain customer content.
    errors = [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(StaleDataError)
async def stale_edit(_request, _exc):
    return JSONResponse(status_code=409, content={"detail": "Case changed; refresh before editing"})


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable; retry later"})


@app.get("/health/live")
def live():
    return {"status": "ok", "version": "0.3.0"}


@app.get("/health/ready")
def ready(session: Session = Depends(get_session)):
    session.execute(text("SELECT 1 FROM cases LIMIT 1"))
    return {"status": "ready"}


@app.post("/cases", response_model=CaseView, status_code=201)
def create_case(
    payload: CaseCreate,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = Case(**payload.model_dump(exclude={"questions"}))
    case.queries = [QueryItem(position=i, question=q) for i, q in enumerate(payload.questions)]
    session.add(case)
    try:
        session.flush()
        start_clock(case, session, case.created_at)
        session.add(AuditEvent(case_id=case.id, actor=f"demo-{role}", action="case.created"))
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = session.scalar(
            select(Case.id).where(Case.source_message_id == payload.source_message_id)
        )
        if existing:
            raise HTTPException(409, "Source message already recorded") from None
        raise
    session.refresh(case)
    return case


@app.get("/cases", response_model=CasePage)
def list_cases(
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _role: str = Depends(get_role),
    session: Session = Depends(get_session),
):
    items = session.scalars(
        select(Case).order_by(Case.created_at.desc(), Case.id).limit(limit).offset(offset)
    ).all()
    total = session.scalar(select(func.count()).select_from(Case))
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@app.get("/cases/{case_id}", response_model=CaseView)
def detail(case_id: str, _role: str = Depends(get_role), session: Session = Depends(get_session)):
    return find_case(case_id, session)


@app.get("/cases/{case_id}/audit", response_model=list[AuditView])
def audit(case_id: str, _role: str = Depends(get_role), session: Session = Depends(get_session)):
    find_case(case_id, session)
    return session.scalars(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)
    ).all()


@app.post("/cases/{case_id}/assignment", response_model=CaseView)
def assign(
    case_id: str,
    payload: Assignment,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session, owner_required=False)
    if case.status not in ACTIVE_STATES | {"new"}:
        raise HTTPException(409, "Resolved or closed cases must be reopened before assignment")
    if role != "manager" and (
        payload.owner != "demo-agent" or case.owner not in {None, "demo-agent"}
    ):
        raise HTTPException(403, "Agents can only claim unassigned or agent-owned cases")
    if case.owner == payload.owner:
        raise HTTPException(409, "Case already has that owner")
    old = case.owner
    case.owner = payload.owner
    on_assignment(case, utc_now())
    if case.status == "new":
        case.status = "assigned"
    return commit_change(
        case, role, "case.assigned", {"previous_owner": old, "owner": case.owner}, session
    )


@app.post("/cases/{case_id}/transition", response_model=CaseView)
def transition(
    case_id: str,
    payload: Transition,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    if payload.target not in TRANSITIONS.get(case.status, set()):
        raise HTTPException(409, "This status transition is not allowed")
    if case.status == "pending_review" and role != "manager":
        raise HTTPException(403, "A manager must return this case for further work")
    if payload.target == "awaiting_business_unit" and not any(
        t.completed_at is None for t in case.followups
    ):
        raise HTTPException(
            409, "Create an owned NFCR follow-up task before waiting for a business unit"
        )
    previous = case.status
    case.status = payload.target
    on_transition(case, previous, utc_now())
    if payload.target == "closed":
        case.closure_reason = payload.reason
    return commit_change(
        case,
        role,
        "case.status_changed",
        {"from": previous, "to": case.status, "reason": payload.reason},
        session,
    )


@app.put("/cases/{case_id}/queries/{query_id}", response_model=CaseView)
def update_query(
    case_id: str,
    query_id: int,
    payload: QueryUpdate,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    query = next((q for q in case.queries if q.id == query_id), None)
    if query is None:
        raise HTTPException(404, "Question not found in this case")
    before = query_snapshot(query)
    mark_action(case, utc_now())
    for name in ("disposition", "answer", "evidence_reference", "dependency"):
        setattr(query, name, getattr(payload, name) or None)
    return commit_change(
        case, role, "query.updated", {"before": before, "after": query_snapshot(query)}, session
    )


@app.post("/cases/{case_id}/commitments", response_model=CaseView)
def create_commitment(
    case_id: str,
    payload: CommitmentCreate,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    commitment = Commitment(description=payload.description, due_at=payload.due_at)
    case.commitments.append(commitment)
    return commit_change(
        case,
        role,
        "commitment.created",
        {"description": payload.description, "due_at": payload.due_at.isoformat()},
        session,
    )


@app.post("/cases/{case_id}/commitments/{commitment_id}/complete", response_model=CaseView)
def complete_commitment(
    case_id: str,
    commitment_id: int,
    payload: CommitmentComplete,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    ensure_editable(case)
    commitment = next((c for c in case.commitments if c.id == commitment_id), None)
    if commitment is None:
        raise HTTPException(404, "Commitment not found in this case")
    if commitment.completed_at:
        raise HTTPException(409, "Commitment already completed")
    commitment.completed_at = utc_now()
    commitment.completion_note = payload.completion_note
    return commit_change(
        case,
        role,
        "commitment.completed",
        {"commitment_id": commitment_id, "note": payload.completion_note},
        session,
    )


@app.post("/cases/{case_id}/resolve", response_model=CaseView)
def resolve_case(
    case_id: str,
    payload: ResolveRequest,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    resolve(case, payload.resolution_note, role)
    stop_clock(case, case.resolved_at)
    return commit_change(case, role, "case.resolved", {"note": payload.resolution_note}, session)


@app.post("/cases/{case_id}/reopen", response_model=CaseView)
def reopen(
    case_id: str,
    payload: ReopenRequest,
    role: str = Depends(require_writer),
    session: Session = Depends(get_session),
):
    case = editable_case(case_id, payload.expected_version, role, session)
    if case.status not in {"resolved", "closed"}:
        raise HTTPException(409, "Only resolved or closed cases can be reopened")
    previous = {
        "status": case.status,
        "resolution_note": case.resolution_note,
        "closure_reason": case.closure_reason,
        "queries": [query_snapshot(q) for q in case.queries],
    }
    case.status = "in_progress"
    start_clock(case, session, utc_now())
    case.resolution_note = None
    case.resolved_at = None
    case.closure_reason = None
    for query in case.queries:
        query.disposition = "open"
        query.answer = query.evidence_reference = query.dependency = None
    return commit_change(
        case, role, "case.reopened", {"reason": payload.reason, "previous": previous}, session
    )


@app.get("/session")
def session_role(role: str = Depends(get_role)):
    return {"role": role, "actor": f"demo-{role}"}


from app.service_api import router as service_router  # noqa: E402

app.include_router(service_router)
