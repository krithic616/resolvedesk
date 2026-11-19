"""Case records and attributable audit events (synthetic data only)."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
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
    queries: Mapped[list["QueryItem"]] = relationship(
        cascade="all, delete-orphan", order_by="QueryItem.position"
    )


class QueryItem(Base):
    __tablename__ = "query_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(String(1000))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    actor: Mapped[str] = mapped_column(String(40))
    action: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
