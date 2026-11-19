"""ResolveDesk milestone 1: authenticated, persistent synthetic case intake."""

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.auth import get_role, require_writer
from app.db import get_session
from app.models import AuditEvent, Case, QueryItem
from app.schemas import AuditView, CaseCreate, CasePage, CaseView

app = FastAPI(title="ResolveDesk", version="0.1.0", description="Synthetic banking service cases")


@app.exception_handler(RequestValidationError)
async def validation_error(_request, exc):
    # FastAPI's default includes rejected inputs, which can contain customer content.
    errors = [{"loc": list(e["loc"]), "type": e["type"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, _exc):
    return JSONResponse(status_code=503, content={"detail": "Database unavailable; retry later"})


@app.get("/health/live")
def live():
    return {"status": "ok", "version": "0.1.0"}


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


def find_case(case_id: str, session: Session):
    case = session.scalar(
        select(Case).options(selectinload(Case.queries)).where(Case.id == case_id)
    )
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


@app.get("/cases/{case_id}", response_model=CaseView)
def detail(case_id: str, _role: str = Depends(get_role), session: Session = Depends(get_session)):
    return find_case(case_id, session)


@app.get("/cases/{case_id}/audit", response_model=list[AuditView])
def audit(case_id: str, _role: str = Depends(get_role), session: Session = Depends(get_session)):
    find_case(case_id, session)
    return session.scalars(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)
    ).all()
