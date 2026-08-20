from __future__ import annotations

import re

from app.goals.schemas import GoalCategory

GOAL_TRIGGER_PATTERN = re.compile(r"\bi want to\b\s*(.*)", re.IGNORECASE)

CATEGORY_KEYWORDS: dict[GoalCategory, tuple[str, ...]] = {
    GoalCategory.BUSINESS: ("agency", "clients", "revenue", "business", "grow the"),
    GoalCategory.CAREER: ("career", "promotion", "job", "role"),
    GoalCategory.HEALTH: ("exercise", "weight", "fitness", "sleep", "health"),
    GoalCategory.LEARNING: ("learn", "study", "course", "skill"),
    GoalCategory.FINANCE: ("save", "invest", "financial", "budget", "money"),
    GoalCategory.RELATIONSHIP: ("relationship", "friend", "family"),
    GoalCategory.PROJECT: ("project", "ship", "launch", "build"),
}


def extract_goal_title(text: str) -> str:
    match = GOAL_TRIGGER_PATTERN.search(text)
    remainder = match.group(1) if match else text
    return remainder.strip(" .?!:").capitalize() or text.strip()


def infer_goal_category(text: str) -> GoalCategory:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return category
    return GoalCategory.OTHER


def extract_focus_minutes(text: str, *, default: float = 25.0) -> float:
    match = re.search(r"(\d+)\s*-?\s*minutes?", text, re.IGNORECASE)
    return float(match.group(1)) if match else default


def extract_focus_goal(text: str) -> str:
    match = re.search(r"focus (?:mode|session)?\s*(?:for|on)\s+(.*)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip(" .?!:")
    return text.strip(" .?!:")


def extract_quiet_minutes(text: str, *, default: float = 120.0) -> float:
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*hours?", text, re.IGNORECASE)
    if hour_match:
        return float(hour_match.group(1)) * 60
    minute_match = re.search(r"(\d+)\s*minutes?", text, re.IGNORECASE)
    if minute_match:
        return float(minute_match.group(1))
    return default
