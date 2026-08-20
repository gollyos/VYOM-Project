from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import GoalCategory

_TEMPLATES: dict[GoalCategory, dict[str, list[str]]] = {
    GoalCategory.BUSINESS: {
        "milestones": ["Define the measurable target", "Identify current blockers", "Create the initial strategy", "Establish a review cadence"],
        "next_actions": ["Draft the initial strategy outline", "List the top 3 current blockers"],
    },
    GoalCategory.CAREER: {
        "milestones": ["Define the target role or outcome", "Identify the key skill gaps", "Build a visible track record"],
        "next_actions": ["List the concrete skill gaps to close"],
    },
    GoalCategory.HEALTH: {
        "milestones": ["Define the measurable habit or target", "Establish a baseline", "Build the initial routine"],
        "next_actions": ["Log a baseline data point"],
    },
    GoalCategory.LEARNING: {
        "milestones": ["Define the target skill or knowledge", "Choose learning resources", "Schedule regular practice time"],
        "next_actions": ["Choose the first resource"],
    },
    GoalCategory.FINANCE: {
        "milestones": ["Define the target number", "Assess the current position", "Identify the biggest lever"],
        "next_actions": ["Assess the current position"],
    },
    GoalCategory.PERSONAL: {
        "milestones": ["Clarify what success looks like", "Identify the main obstacle", "Define a first small step"],
        "next_actions": ["Define a first small step"],
    },
    GoalCategory.RELATIONSHIP: {
        "milestones": ["Clarify the desired outcome", "Identify a concrete first action"],
        "next_actions": ["Identify a concrete first action"],
    },
    GoalCategory.PROJECT: {
        "milestones": ["Define scope and success criteria", "Break the work into phases", "Identify dependencies"],
        "next_actions": ["Define scope and success criteria"],
    },
    GoalCategory.OTHER: {
        "milestones": ["Clarify the goal", "Define one measurable milestone"],
        "next_actions": ["Clarify what success looks like"],
    },
}


class MilestoneDraft(BaseModel):
    title: str
    target: str


class GoalPlan(BaseModel):
    milestones: list[MilestoneDraft] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    clarifying_questions: list[str] = Field(default_factory=list)


class GoalPlanner:
    """Deterministic template-based planning (rule 74 — no model call
    required). Produces a small, useful starting scaffold, never hundreds
    of tasks (rule 5); the user's own next steps refine it from there."""

    def __init__(self, *, max_milestones: int = 4, max_next_actions: int = 3):
        self.max_milestones = max_milestones
        self.max_next_actions = max_next_actions

    def plan(self, title: str, category: GoalCategory) -> GoalPlan:
        template = _TEMPLATES.get(category, _TEMPLATES[GoalCategory.OTHER])
        milestones = [MilestoneDraft(title=item, target=f"{item} for: {title}") for item in template["milestones"][: self.max_milestones]]
        next_actions = template["next_actions"][: self.max_next_actions]
        return GoalPlan(milestones=milestones, next_actions=next_actions)
