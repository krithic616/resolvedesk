"""Bounded, explicit intake contracts; unexpected fields are rejected."""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Category(StrEnum):
    charges = "charges"
    cards = "cards"
    account_service = "account_service"
    payments = "payments"
    other = "other"


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source_message_id: str = Field(min_length=1, max_length=200)
    customer_reference: str = Field(pattern=r"^SYN-[A-Z0-9-]{1,60}$")
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    category: Category
    questions: list[str] = Field(min_length=1, max_length=10)

    @field_validator("questions")
    @classmethod
    def validate_questions(cls, values):
        cleaned = [value.strip() for value in values]
        if any(not value or len(value) > 1000 for value in cleaned):
            raise ValueError("Questions must contain 1 to 1000 characters")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("Questions must be distinct")
        return cleaned


class OrmView(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class QueryView(OrmView):
    id: int
    question: str


class CaseSummary(OrmView):
    id: str
    subject: str
    category: str
    status: str
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, value):
        # SQLite drops timezone metadata; all application writes use UTC.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class CaseView(CaseSummary):
    source_message_id: str
    customer_reference: str
    body: str
    queries: list[QueryView]


class CasePage(BaseModel):
    items: list[CaseSummary]
    total: int
    limit: int
    offset: int


class AuditView(OrmView):
    id: int
    actor: str
    action: str
    created_at: datetime

    _utc = field_validator("created_at")(CaseSummary.ensure_utc.__func__)
