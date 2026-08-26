"""VYOM's `/learn` capability - mirrors Hermes's own agent/learn_prompt.py
(a `/learn` slash command: point the agent at any source - a
conversation, a completed task, a pasted workflow description - and it
authors a reusable SKILL.md-equivalent from it).

VYOM's structured skill format (app/skills/schemas.py SkillSpec) is
richer than a markdown file: typed input slots, named tool/capability
per step, and an explicit TESTING status gate before a taught skill
can run for real (see TeachableSkillService.activate()). LearnService
is the bridge from a real, already-completed source of evidence into
that structured shape - it does not invent steps from nothing.

Two real sources, both genuinely available in this deployment today:
  - from_task(): a completed Task's own `plan` (list[PlanStep], each
    with a title/summary the planner itself wrote) and its execution
    result's `evidence` (list[str] - the SAME evidence trail
    postcondition verification already checks). A task that actually
    ran and left evidence is real, verifiable material to learn from.
  - from_description(): free-form text describing a workflow as
    numbered/bulleted steps ("1. open the file, 2. run pytest, 3. git
    commit"), parsed deterministically - no LLM call required, same
    keyless-first design choice as DialecticReasoner in this session.

Every derived skill is heuristic and UNVERIFIED until a human reviews
and activates it - it is written with status=TESTING (the same status
TeachableSkillService.create already uses for user-taught skills) and
NEVER auto-activated. This is a deliberate safety boundary: a skill
that will later run with real tool permissions must never go live from
an unreviewed guess.
"""
from __future__ import annotations

import re

from app.schemas.approvals import PermissionLevel
from app.schemas.tasks import PlanStep, Task
from app.skills.registry import SkillRegistry
from app.skills.schemas import (
    SkillBudget, SkillFailurePolicy, SkillSpec, SkillStatus, SkillStep, SkillVerification,
)

# Same deterministic-pattern-over-LLM-call philosophy as
# FailureAnalyzer/DialecticReasoner in this session: a keyword match to
# a real registered tool, not a guess dressed up as certainty. Order
# matters - more specific patterns are checked first.
_TOOL_KEYWORD_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bgit\b|\bcommit\b|\bpush\b|\bbranch\b", re.I), "git", "vcs.commit"),
    (re.compile(r"\bbrowser\b|\bnavigate\b|\bwebsite\b|\bclick\b|\bscroll\b", re.I), "browser", "browser.navigate"),
    (re.compile(r"\bscreenshot\b|\bcapture.*screen\b", re.I), "screenshot", "desktop.capture"),
    (re.compile(r"\brun\b|\bexecute\b|\bcommand\b|\bbuild\b|\btest\b|\bpytest\b|\bnpm\b", re.I), "terminal", "terminal.execute"),
    (re.compile(r"\bfile\b|\bwrite\b|\bread\b|\bsave\b|\bopen\b", re.I), "filesystem", "filesystem.read"),
]
_DEFAULT_TOOL = "terminal"
_DEFAULT_CAPABILITY = "terminal.execute"

_NUMBERED_STEP = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.+)$")


class LearnService:
    """Derives a TESTING-status SkillSpec from a real source (a
    completed Task's own plan+evidence, or a described workflow) and
    registers it - never activates it automatically."""

    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def from_task(self, task: Task, *, skill_id: str | None = None) -> SkillSpec:
        if not task.plan:
            raise ValueError("This task has no recorded plan to learn from")
        skill_id = skill_id or self._slug(task.user_request)
        steps = self._steps_from_plan(task.plan)
        evidence_note = f" Learned from real evidence: {'; '.join(task.result.evidence[:3])}" if task.result and task.result.evidence else ""
        return self._build(
            skill_id=skill_id,
            name=task.user_request[:120] or "Learned skill",
            description=f"Learned from completed task {task.id}.{evidence_note}",
            steps=steps,
            created_by=f"learned-from-task:{task.id}",
        )

    def from_description(self, description: str, *, skill_id: str, name: str) -> SkillSpec:
        lines = [line for line in description.splitlines() if line.strip()]
        step_texts = [m.group(1).strip() for line in lines if (m := _NUMBERED_STEP.match(line))]
        if not step_texts:
            # No numbered/bulleted structure - fall back to treating
            # non-empty lines as steps, so a plain paragraph still
            # produces something reviewable rather than failing outright.
            step_texts = [line.strip() for line in lines][:20]
        if not step_texts:
            raise ValueError("Could not find any steps in the description")
        steps = [self._step_from_text(f"step_{i}", text) for i, text in enumerate(step_texts, start=1)]
        return self._build(
            skill_id=skill_id, name=name,
            description=f"Learned from a described workflow ({len(steps)} steps).",
            steps=steps, created_by="learned-from-description",
        )

    def _steps_from_plan(self, plan: list[PlanStep]) -> list[SkillStep]:
        return [self._step_from_text(step.id, f"{step.title}. {step.summary}".strip(". ")) for step in plan]

    def _step_from_text(self, step_id: str, text: str) -> SkillStep:
        tool, capability = _DEFAULT_TOOL, _DEFAULT_CAPABILITY
        for pattern, matched_tool, matched_capability in _TOOL_KEYWORD_PATTERNS:
            if pattern.search(text):
                tool, capability = matched_tool, matched_capability
                break
        return SkillStep(id=step_id, action=text[:200] or step_id, capability=capability, tool=tool)

    def _build(self, *, skill_id: str, name: str, description: str, steps: list[SkillStep], created_by: str) -> SkillSpec:
        skill = SkillSpec(
            id=skill_id, name=name, version="1.0.0", description=description,
            category="learned",
            inputs={},
            outputs={"step_results": "verified tool outputs"},
            required_capabilities=sorted({step.capability for step in steps}),
            required_tools=sorted({step.tool for step in steps if step.tool}),
            required_permissions=PermissionLevel.L1,
            steps=steps,
            verification=SkillVerification(checks=["all_steps_succeeded"], require_evidence=True),
            failure_policy=SkillFailurePolicy(),
            budget=SkillBudget(),
            created_by=created_by,
            status=SkillStatus.TESTING,  # NEVER auto-activated - a human reviews this before it can run for real
        )
        return self.registry.register(
            skill,
            instructions=(
                "Heuristically learned skill - steps and tool assignments are pattern-matched guesses "
                "from real evidence, not human-authored. Review each step's tool/capability assignment "
                "before activating; activation requires an explicit call, it is never automatic."
            ),
            changelog="1.0.0 - Learned automatically; recorded as testing pending human review.",
        )

    @staticmethod
    def _slug(text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "learned-skill"
        return f"learned-{slug}"
