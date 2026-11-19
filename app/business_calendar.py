"""Working-time arithmetic for explicit, fixed-offset office calendars."""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
MAX_DAYS = 36600


def as_utc(value):
    # All SQLite writes are normalized to UTC before timezone metadata is dropped.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def iso(value):
    return as_utc(value).isoformat().replace("+00:00", "Z") if value else None


class BusinessCalendar:
    def __init__(self, configuration):
        self.zone = ZoneInfo(configuration["timezone"])
        self.open = time.fromisoformat(configuration["opens_at"])
        self.close = time.fromisoformat(configuration["closes_at"])
        self.weekdays = set(configuration["weekdays"])
        self.holidays = set(configuration["holidays"])

    def window(self, day):
        if day.weekday() not in self.weekdays or day.isoformat() in self.holidays:
            return None
        return (
            datetime.combine(day, self.open, self.zone).astimezone(UTC),
            datetime.combine(day, self.close, self.zone).astimezone(UTC),
        )

    def add_seconds(self, start, seconds):
        if seconds < 0:
            raise ValueError("Working-time increments must be nonnegative")
        cursor = as_utc(start)
        if seconds == 0:
            return cursor
        day = cursor.astimezone(self.zone).date()
        for _ in range(MAX_DAYS):
            window = self.window(day)
            if window:
                begin, end = window
                cursor = max(cursor, begin)
                available = (end - cursor).total_seconds()
                if available > 0:
                    if seconds <= available:
                        return cursor + timedelta(seconds=seconds)
                    seconds -= available
            day += timedelta(days=1)
        raise ValueError("Calendar calculation exceeds the supported 100-year horizon")

    def seconds_between(self, start, end):
        start, end = as_utc(start), as_utc(end)
        if end <= start:
            return 0
        day = start.astimezone(self.zone).date()
        last = end.astimezone(self.zone).date()
        total = 0
        for _ in range(MAX_DAYS):
            if day > last:
                return total
            window = self.window(day)
            if window:
                begin, finish = window
                total += max(0, (min(end, finish) - max(start, begin)).total_seconds())
            day += timedelta(days=1)
        raise ValueError("Calendar calculation exceeds the supported 100-year horizon")

    def action_cutoff(self, allocation):
        allocation = as_utc(allocation)
        day = allocation.astimezone(self.zone).date()
        for _ in range(MAX_DAYS):
            window = self.window(day)
            if window and allocation < window[1]:
                return window[1]
            day += timedelta(days=1)
        raise ValueError("No working day within the supported calendar horizon")
