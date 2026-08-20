from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .schemas import AutomationCreate, AutomationType


_TIME = r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)?"


def is_schedule_request(text: str) -> bool:
    lowered = (text or "").strip().lower()
    return bool(
        re.search(r"\bcron\s+", lowered)
        or re.search(r"\b(?:every day|daily|every weekday)\b.*\b(?:at|baje)\b", lowered)
        or re.search(r"\bhar din\b.*\bbaje\b", lowered)
        or re.search(r"\b(?:tomorrow|kal)\b.*\b(?:at|baje)\b", lowered)
        or re.search(r"\bschedule\b.+\b(?:at|tomorrow|daily|every|cron)\b", lowered)
    )


def _clock(match: re.Match) -> tuple[int, int]:
    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = (match.group("ampm") or "").lower()
    if minute > 59:
        raise ValueError("Schedule minute must be between 00 and 59")
    if ampm:
        if hour < 1 or hour > 12:
            raise ValueError("12-hour schedule time must be between 1 and 12")
        hour %= 12
        if ampm == "pm":
            hour += 12
    elif hour > 23:
        raise ValueError("24-hour schedule time must be between 0 and 23")
    return hour, minute


def _command(value: str) -> str:
    cleaned = value.strip(" \t,:;-\"'")
    cleaned = re.sub(r"^(?:run|do|please|to)\s+", "", cleaned, flags=re.IGNORECASE)
    if len(cleaned) < 2:
        raise ValueError("The scheduled command is missing")
    return cleaned


def parse_schedule_request(
    text: str,
    *,
    now: datetime | None = None,
    timezone_name: str = "Asia/Calcutta",
) -> AutomationCreate:
    original = (text or "").strip()
    if not is_schedule_request(original):
        raise ValueError("No supported schedule was found")

    # Explicit standard cron: `cron 0 9 * * 1-5 run show my status`.
    cron = re.search(
        r"(?:^|\bschedule\s+)cron\s+(\S+\s+\S+\s+\S+\s+\S+\s+\S+)\s+(.+)$",
        original,
        re.IGNORECASE,
    )
    if cron:
        command = _command(cron.group(2))
        return AutomationCreate(
            name=f"Scheduled: {command[:80]}",
            type=AutomationType.RECURRING,
            action="run_vyom_command",
            cron_expression=cron.group(1),
            timezone=timezone_name,
            condition={"command": command},
        )

    recurrence_patterns = (
        rf"^\s*(?:every day|daily|every weekday)\s+(?:at\s+)?{_TIME}\s*[,;-]?\s*(?P<command>.+)$",
        rf"^\s*har din\s+{_TIME}\s*baje\s*[,;-]?\s*(?P<command>.+)$",
        rf"^\s*schedule\s+(?P<command>.+?)\s+(?P<frequency>every day|daily|every weekday)\s+at\s+{_TIME}\s*$",
    )
    for pattern in recurrence_patterns:
        match = re.search(pattern, original, re.IGNORECASE)
        if not match:
            continue
        hour, minute = _clock(match)
        command = _command(match.group("command"))
        frequency = (match.groupdict().get("frequency") or match.group(0)).lower()
        weekday = "1-5" if "weekday" in frequency else "*"
        return AutomationCreate(
            name=f"Scheduled: {command[:80]}",
            type=AutomationType.RECURRING,
            action="run_vyom_command",
            cron_expression=f"{minute} {hour} * * {weekday}",
            timezone=timezone_name,
            condition={"command": command},
        )

    one_time_patterns = (
        rf"^\s*(?:tomorrow\s+at\s+|kal\s+){_TIME}\s*(?:baje)?\s*[,;-]?\s*(?P<command>.+)$",
        rf"^\s*schedule\s+(?P<command>.+?)\s+(?:tomorrow\s+at\s+|kal\s+){_TIME}\s*(?:baje)?\s*$",
    )
    for pattern in one_time_patterns:
        match = re.search(pattern, original, re.IGNORECASE)
        if not match:
            continue
        hour, minute = _clock(match)
        zone = ZoneInfo(timezone_name)
        reference = (now or datetime.now(timezone.utc)).astimezone(zone)
        local_run = datetime.combine(
            reference.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=zone,
        ).replace(hour=hour, minute=minute)
        command = _command(match.group("command"))
        return AutomationCreate(
            name=f"Scheduled: {command[:80]}",
            type=AutomationType.ONE_TIME,
            action="run_vyom_command",
            run_at=local_run.astimezone(timezone.utc),
            timezone=timezone_name,
            condition={"command": command},
        )
    raise ValueError(
        "I understood this as scheduling, but not the time. Use 'tomorrow at 5 PM ...', "
        "'every day at 9:30 ...', or 'cron 0 9 * * 1-5 ...'."
    )
