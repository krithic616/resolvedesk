"""Bounded, explicit intake contracts; unexpected fields are rejected."""

from datetime import datetime, timezone
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


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
    disposition: str
    answer: str | None
    evidence_reference: str | None
    dependency: str | None


class CaseSummary(OrmView):
    id: str
    subject: str
    category: str
    status: str
    created_at: datetime
    owner: str | None
    version: int

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
    commitments: list["CommitmentView"]
    resolution_note: str | None
    closure_reason: str | None
    resolved_at: datetime | None

    @field_validator("resolved_at")
    @classmethod
    def optional_utc(cls, value):
        return CaseSummary.ensure_utc(value) if value else value


class CasePage(BaseModel):
    items: list[CaseSummary]
    total: int
    limit: int
    offset: int


class CommitmentView(OrmView):
    id: int
    description: str
    due_at: datetime
    completed_at: datetime | None
    completion_note: str | None

    _due_utc = field_validator("due_at")(CaseSummary.ensure_utc.__func__)

    @field_validator("completed_at")
    @classmethod
    def optional_utc(cls, value):
        return CaseSummary.ensure_utc(value) if value else value


class AuditView(OrmView):
    id: int
    actor: str
    action: str
    details: dict
    created_at: datetime

    _utc = field_validator("created_at")(CaseSummary.ensure_utc.__func__)


class VersionedWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_version: int = Field(ge=1)


class Assignment(VersionedWrite):
    owner: str = Field(pattern=r"^demo-(agent|manager)$")


class Transition(VersionedWrite):
    target: str = Field(
        pattern=r"^(in_progress|awaiting_business_unit|awaiting_customer|pending_review|closed)$"
    )
    reason: str = Field(min_length=1, max_length=2000)


class QueryUpdate(VersionedWrite):
    disposition: str = Field(pattern=r"^(open|answered|waiting)$")
    answer: str = Field(default="", max_length=5000)
    evidence_reference: str = Field(default="", max_length=500)
    dependency: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def check_disposition(self):
        if self.disposition == "answered":
            if not self.answer or not self.evidence_reference or self.dependency:
                raise ValueError(
                    "An answered query requires an answer and evidence, with no dependency"
                )
        elif self.disposition == "waiting":
            if not self.dependency or self.answer or self.evidence_reference:
                raise ValueError("A waiting query requires only a dependency note")
        elif self.answer or self.evidence_reference or self.dependency:
            raise ValueError("An open query must not contain answer or dependency fields")
        return self


class ResolveRequest(VersionedWrite):
    resolution_note: str = Field(min_length=1, max_length=5000)


class ReopenRequest(VersionedWrite):
    reason: str = Field(min_length=1, max_length=2000)


class CommitmentCreate(VersionedWrite):
    description: str = Field(min_length=1, max_length=1000)
    due_at: AwareDatetime

    @field_validator("due_at")
    @classmethod
    def normalize_due_at(cls, value):
        return value.astimezone(timezone.utc)


class CommitmentComplete(VersionedWrite):
    completion_note: str = Field(min_length=1, max_length=1000)
