from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


class CronValidationError(ValueError):
    pass


def _field(value: str, minimum: int, maximum: int, *, sunday: bool = False) -> tuple[set[int], bool]:
    wildcard = value == "*"
    selected: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if not part:
            raise CronValidationError("Empty cron field component")
        step = 1
        base = part
        if "/" in part:
            base, raw_step = part.split("/", 1)
            try:
                step = int(raw_step)
            except ValueError as error:
                raise CronValidationError(f"Invalid cron step: {raw_step}") from error
            if step < 1:
                raise CronValidationError("Cron step must be positive")
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            try:
                start, end = int(raw_start), int(raw_end)
            except ValueError as error:
                raise CronValidationError(f"Invalid cron range: {base}") from error
        else:
            try:
                start = end = int(base)
            except ValueError as error:
                raise CronValidationError(f"Invalid cron value: {base}") from error
        if start < minimum or end > maximum or start > end:
            raise CronValidationError(f"Cron value {base} is outside {minimum}-{maximum}")
        selected.update(range(start, end + 1, step))
    if sunday and 7 in selected:
        selected.remove(7)
        selected.add(0)
    return selected, wildcard


def parse_cron(expression: str) -> tuple[set[int], set[int], set[int], set[int], set[int], bool, bool]:
    parts = expression.strip().split()
    if len(parts) != 5:
        raise CronValidationError("Cron expression must have five fields: minute hour day month weekday")
    minutes, _ = _field(parts[0], 0, 59)
    hours, _ = _field(parts[1], 0, 23)
    days, day_wildcard = _field(parts[2], 1, 31)
    months, _ = _field(parts[3], 1, 12)
    weekdays, weekday_wildcard = _field(parts[4], 0, 7, sunday=True)
    return minutes, hours, days, months, weekdays, day_wildcard, weekday_wildcard


def next_cron_after(expression: str, after: datetime, timezone_name: str) -> datetime:
    """Return the next standard five-field cron occurrence in UTC.

    Day-of-month and day-of-week follow ordinary cron OR semantics when
    both are restricted. Searching by calendar day (rather than every
    minute) keeps sparse schedules and leap-day schedules bounded.
    """
    minutes, hours, days, months, weekdays, day_wildcard, weekday_wildcard = parse_cron(expression)
    zone = ZoneInfo(timezone_name)
    reference = after if after.tzinfo else after.replace(tzinfo=timezone.utc)
    local_after = reference.astimezone(zone)
    first_day = local_after.date()
    for offset in range(366 * 5 + 2):
        candidate_day = first_day + timedelta(days=offset)
        if candidate_day.month not in months:
            continue
        dom_match = candidate_day.day in days
        cron_weekday = (candidate_day.weekday() + 1) % 7
        dow_match = cron_weekday in weekdays
        if day_wildcard and weekday_wildcard:
            day_matches = True
        elif day_wildcard:
            day_matches = dow_match
        elif weekday_wildcard:
            day_matches = dom_match
        else:
            day_matches = dom_match or dow_match
        if not day_matches:
            continue
        for hour in sorted(hours):
            for minute in sorted(minutes):
                local_candidate = datetime(
                    candidate_day.year, candidate_day.month, candidate_day.day,
                    hour, minute, tzinfo=zone,
                )
                if local_candidate > local_after:
                    return local_candidate.astimezone(timezone.utc)
    raise CronValidationError("Cron expression has no occurrence in the next five years")
