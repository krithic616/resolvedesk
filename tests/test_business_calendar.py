from datetime import datetime

import pytest
from pydantic import ValidationError

from app.business_calendar import BusinessCalendar, iso
from app.service_schemas import PolicyConfig


def dt(value):
    return datetime.fromisoformat(value)


def calendar(**overrides):
    return BusinessCalendar(PolicyConfig(**overrides).model_dump(mode="json"))


@pytest.mark.parametrize(
    "start,minutes,expected",
    [
        ("2026-11-20T08:00:00+05:30", 120, "2026-11-20T05:30:00Z"),
        ("2026-11-20T16:30:00+05:30", 120, "2026-11-23T05:00:00Z"),
        ("2026-11-20T17:00:00+05:30", 60, "2026-11-23T04:30:00Z"),
        ("2026-11-21T12:00:00+05:30", 60, "2026-11-23T04:30:00Z"),
        ("2026-11-20T09:00:00+05:30", 480, "2026-11-20T11:30:00Z"),
        ("2026-11-20T16:59:30+05:30", 1, "2026-11-23T03:30:30Z"),
        ("2026-11-20T17:00:00+05:30", 0, "2026-11-20T11:30:00Z"),
    ],
)
def test_working_deadlines(start, minutes, expected):
    assert iso(calendar().add_seconds(dt(start), minutes * 60)) == expected


def test_holiday_and_elapsed_working_time():
    c = calendar(holidays=["2026-11-23"])
    start = dt("2026-11-20T16:30:00+05:30")
    end = c.add_seconds(start, 7200)
    assert iso(end) == "2026-11-24T05:00:00Z"
    assert c.seconds_between(start, end) == 7200
    assert c.seconds_between(end, start) == 0


@pytest.mark.parametrize(
    "allocated,expected",
    [
        ("2026-11-20T08:00:00+05:30", "2026-11-20T11:30:00Z"),
        ("2026-11-20T16:59:59+05:30", "2026-11-20T11:30:00Z"),
        ("2026-11-20T17:00:00+05:30", "2026-11-23T11:30:00Z"),
        ("2026-11-22T12:00:00+05:30", "2026-11-23T11:30:00Z"),
    ],
)
def test_action_cutoff(allocated, expected):
    assert iso(calendar().action_cutoff(dt(allocated))) == expected


@pytest.mark.parametrize(
    "change",
    [
        {"weekdays": []},
        {"weekdays": [0, 0]},
        {"weekdays": [7]},
        {"opens_at": "17:00"},
        {"opens_at": "09:00:01"},
        {"opens_at": "09:00+05:30"},
        {"timezone": "Europe/London"},
        {"response_minutes": 500, "resolution_minutes": 100},
        {"response_minutes": 0},
        {"holidays": ["not-a-date"]},
    ],
)
def test_invalid_policies_rejected(change):
    with pytest.raises(ValidationError):
        PolicyConfig(**change)
