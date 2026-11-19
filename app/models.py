"""Case records and attributable audit events (synthetic data only)."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utc_now():
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_message_id: Mapped[str] = mapped_column(String(200), unique=True)
    customer_reference: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    owner: Mapped[str | None] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    closure_reason: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    commitments: Mapped[list["Commitment"]] = relationship(
        cascade="all, delete-orphan", order_by="Commitment.id"
    )
    clocks: Mapped[list["ServiceClock"]] = relationship(
        cascade="all, delete-orphan", order_by="ServiceClock.cycle"
    )
    followups: Mapped[list["FollowUp"]] = relationship(
        cascade="all, delete-orphan", order_by="FollowUp.id"
    )
    __mapper_args__ = {"version_id_col": version}
    queries: Mapped[list["QueryItem"]] = relationship(
        cascade="all, delete-orphan", order_by="QueryItem.position"
    )


class QueryItem(Base):
    __tablename__ = "query_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(String(1000))

    disposition: Mapped[str] = mapped_column(String(20), default="open", server_default="open")
    answer: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(String(500))
    dependency: Mapped[str | None] = mapped_column(String(1000))


class Commitment(Base):
    __tablename__ = "commitments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    description: Mapped[str] = mapped_column(String(1000))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_note: Mapped[str | None] = mapped_column(String(1000))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    details: Mapped[dict] = mapped_column(JSON, default=dict, server_default=text("'{}'"))


class ServicePolicy(Base):
    __tablename__ = "service_policies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    configuration: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ServiceClock(Base):
    __tablename__ = "service_clocks"
    __table_args__ = (UniqueConstraint("case_id", "cycle"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    cycle: Mapped[int] = mapped_column(Integer)
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FollowUp(Base):
    __tablename__ = "follow_ups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    unit: Mapped[str] = mapped_column(String(50))
    owner: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(String(1000))
    next_action: Mapped[str] = mapped_column(String(1000))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completion_note: Mapped[str | None] = mapped_column(String(2000))


class DeadlineAlert(Base):
    __tablename__ = "deadline_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    dedup_key: Mapped[str] = mapped_column(String(250), unique=True)
    source: Mapped[str] = mapped_column(String(40))
    source_id: Mapped[int] = mapped_column(Integer)
    level: Mapped[str] = mapped_column(String(20))
    target_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    acknowledged_by: Mapped[str | None] = mapped_column(String(40))
