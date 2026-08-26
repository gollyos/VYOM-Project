from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class UsagePattern:
    """A detected pattern in user behavior."""
    pattern_id: str
    description: str
    frequency: int  # how many times observed
    last_seen: str
    confidence: float  # 0-1
    suggested_action: str = ""
    category: str = ""  # daily_routine | workflow | preference | schedule


@dataclass
class ProactiveSuggestion:
    """A suggestion VYOM offers proactively without being asked."""
    id: str
    title: str
    description: str
    confidence: float  # 0-1
    category: str  # anticipate | remind | optimize | learn
    priority: str = "medium"  # low | medium | high
    action_available: bool = False  # can VYOM do this automatically?
    estimated_time_ms: int = 0
    context: str = ""


@dataclass
class UserProfile:
    """VYOM's understanding of the user's habits and preferences."""
    active_hours: list[int] = field(default_factory=list)  # hours when user is most active
    common_tasks: list[str] = field(default_factory=list)
    preferred_language: str = "hinglish"
    work_patterns: list[str] = field(default_factory=list)
    tool_usage_frequency: dict[str, int] = field(default_factory=dict)
    last_updated: str = ""


class ProactiveEngine:
    """Anticipates user needs and suggests actions before being asked.

    This is what makes VYOM feel like a real assistant rather than a
    tool you have to命令 every time. It learns patterns like:
    - "Every morning at 9am, user checks status" → pre-generate briefing
    - "User always opens Chrome after checking files" → suggest it
    - "User corrects VYOM about X frequently" → learn the correction
    - "User's PC is slow when 10+ tabs open" → warn proactively
    """

    def __init__(self, data_dir: Path | None = None, task_store=None, experience_store=None):
        self.data_dir = data_dir or Path("data/proactive")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.task_store = task_store
        self.experience_store = experience_store
        self._patterns: dict[str, UsagePattern] = {}
        self._user_profile = UserProfile()
        self._recent_tasks: list[dict] = []

    async def observe_task(self, task) -> None:
        """Record a completed task for pattern learning."""
        if task is None:
            return

        record = {
            "goal": (task.goal or "")[:200],
            "intent": task.profile.intent if task.profile else "unknown",
            "status": task.status.value if hasattr(task.status, 'value') else str(task.status),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "hour": datetime.now().hour,
        }
        self._recent_tasks.append(record)

        # Keep only last 100 tasks in memory
        if len(self._recent_tasks) > 100:
            self._recent_tasks = self._recent_tasks[-100:]

        # Update user profile
        self._update_profile(record)

        # Detect patterns
        self._detect_patterns()

    def _update_profile(self, record: dict) -> None:
        """Update the user profile with new observation."""
        hour = record.get("hour", 12)
        if hour not in self._user_profile.active_hours:
            self._user_profile.active_hours.append(hour)
            self._user_profile.active_hours.sort()

        intent = record.get("intent", "")
        if intent and intent != "unknown":
            self._user_profile.tool_usage_frequency[intent] = \
                self._user_profile.tool_usage_frequency.get(intent, 0) + 1

        self._user_profile.last_updated = datetime.now(timezone.utc).isoformat()

    def _detect_patterns(self) -> None:
        """Analyze recent tasks to detect recurring patterns."""
        if len(self._recent_tasks) < 5:
            return

        # Detect time-based patterns
        hour_counts: dict[int, int] = {}
        for task in self._recent_tasks:
            hour = task.get("hour", 12)
            hour_counts[hour] = hour_counts.get(hour, 0) + 1

        # Detect intent patterns
        intent_counts: dict[str, int] = {}
        for task in self._recent_tasks:
            intent = task.get("intent", "unknown")
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        # Create patterns for frequent intents
        for intent, count in intent_counts.items():
            if count >= 3 and intent != "unknown":
                pattern_id = f"intent_{intent}"
                self._patterns[pattern_id] = UsagePattern(
                    pattern_id=pattern_id,
                    description=f"Frequent {intent} tasks",
                    frequency=count,
                    last_seen=self._recent_tasks[-1].get("timestamp", ""),
                    confidence=min(1.0, count / 10),
                    category="workflow",
                )

    def get_suggestions(self) -> list[ProactiveSuggestion]:
        """Generate proactive suggestions based on learned patterns."""
        suggestions = []

        # Suggest based on time of day
        current_hour = datetime.now().hour
        if 9 <= current_hour <= 10:
            suggestions.append(ProactiveSuggestion(
                id="morning_briefing",
                title="Morning briefing available",
                description="I can generate your daily status report, pending tasks, and priorities.",
                confidence=0.7,
                category="anticipate",
                priority="medium",
                action_available=True,
                estimated_time_ms=5000,
            ))

        if 17 <= current_hour <= 18:
            suggestions.append(ProactiveSuggestion(
                id="evening_review",
                title="End-of-day review",
                description="I can summarize what was accomplished today and prepare tomorrow's plan.",
                confidence=0.6,
                category="anticipate",
                priority="low",
                action_available=True,
                estimated_time_ms=3000,
            ))

        # Suggest based on patterns
        for pattern in self._patterns.values():
            if pattern.frequency >= 5 and pattern.confidence >= 0.5:
                suggestions.append(ProactiveSuggestion(
                    id=f"pattern_{pattern.pattern_id}",
                    title=f"Detected pattern: {pattern.description}",
                    description=f"This action has been performed {pattern.frequency} times. "
                               f"I can automate or shortcut this.",
                    confidence=pattern.confidence,
                    category="optimize",
                    priority="medium",
                    action_available=False,
                ))

        # Suggest based on failure patterns
        recent_failures = [t for t in self._recent_tasks if t.get("status") == "failed"]
        if len(recent_failures) >= 3:
            suggestions.append(ProactiveSuggestion(
                id="failure_review",
                title="Multiple recent failures detected",
                description=f"{len(recent_failures)} tasks failed recently. I can analyze the patterns "
                           f"and suggest fixes.",
                confidence=0.8,
                category="learn",
                priority="high",
                action_available=True,
                estimated_time_ms=2000,
            ))

        # Suggest learning from corrections
        suggestions.append(ProactiveSuggestion(
            id="learn_corrections",
            title="Learn from your corrections",
            description="When you correct me, I remember and improve. "
                       "Tell me what I got wrong and I'll do better next time.",
            confidence=0.9,
            category="learn",
            priority="medium",
            action_available=False,
        ))

        return sorted(suggestions, key=lambda s: -s.confidence)

    def get_user_profile(self) -> UserProfile:
        """Return VYOM's current understanding of the user."""
        return self._user_profile

    def get_patterns(self) -> list[UsagePattern]:
        """Return all detected usage patterns."""
        return sorted(self._patterns.values(), key=lambda p: -p.confidence)
