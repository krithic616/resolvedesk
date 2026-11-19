"""Immutable demonstration policies and versioned servicing requests."""

from datetime import date, time, timezone
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas import Category, VersionedWrite


class CategoryTargets(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response_minutes: int = Field(ge=1, le=10080)
    resolution_minutes: int = Field(ge=1, le=10080)
    followup_minutes: int = Field(ge=1, le=10080)

    @model_validator(mode="after")
    def validate_targets(self):
        if self.resolution_minutes < self.response_minutes:
            raise ValueError("Resolution target cannot be shorter than first response")
        return self


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # These supported zones have no DST ambiguity. Overnight shifts are out of scope.
    timezone: Literal["Asia/Kolkata", "UTC"] = "Asia/Kolkata"
    opens_at: time = time(9)
    closes_at: time = time(17)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)
    holidays: list[date] = Field(default_factory=list, max_length=3700)
    response_minutes: int = Field(default=120, ge=1, le=10080)
    resolution_minutes: int = Field(default=480, ge=1, le=10080)
    followup_minutes: int = Field(default=120, ge=1, le=10080)
    warning_minutes: int = Field(default=30, ge=1, le=480)
    pause_on_customer: bool = False
    category_targets: dict[Category, CategoryTargets] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_calendar(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(
            d < 0 or d > 6 for d in self.weekdays
        ):
            raise ValueError("Weekdays must be distinct integers from 0 (Monday) to 6 (Sunday)")
        for boundary in (self.opens_at, self.closes_at):
            if boundary.tzinfo is not None or boundary.second or boundary.microsecond:
                raise ValueError("Office times must be local times with minute precision")
        if self.opens_at >= self.closes_at:
            raise ValueError("Office opening must precede closing on the same day")
        span = (self.closes_at.hour * 60 + self.closes_at.minute) - (
            self.opens_at.hour * 60 + self.opens_at.minute
        )
        if span < 15:
            raise ValueError("Office windows must be at least 15 minutes")
        if self.resolution_minutes < self.response_minutes:
            raise ValueError("Resolution target cannot be shorter than the first-response target")
        return self


class PolicyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    configuration: PolicyConfig


class FirstResponse(VersionedWrite):
    note: str = Field(min_length=1, max_length=2000)


class FollowUpCreate(VersionedWrite):
    unit: Literal["charges", "cards", "payments", "branch_operations"]
    owner: str = Field(pattern=r"^demo-[a-z0-9-]{1,50}$")
    description: str = Field(min_length=1, max_length=1000)
    next_action: str = Field(min_length=1, max_length=1000)
    due_at: AwareDatetime | None = None

    @field_validator("due_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc) if value else None


class FollowUpReview(VersionedWrite):
    note: str = Field(min_length=1, max_length=2000)
    next_action: str = Field(min_length=1, max_length=1000)
    due_at: AwareDatetime | None = None
    owner: str | None = Field(default=None, pattern=r"^demo-[a-z0-9-]{1,50}$")
    _utc = field_validator("due_at")(FollowUpCreate.utc.__func__)


class FollowUpComplete(VersionedWrite):
    completion_note: str = Field(min_length=1, max_length=2000)
