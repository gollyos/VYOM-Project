from __future__ import annotations

from .experience_store import ExperienceStore


def skill_id_for(task_type: str, tools: tuple[str, ...]) -> str:
    """Deterministic id for the auto-taught skill of one (goal-kind,
    tool-sequence) pattern — stable across repeated detections so the
    SAME pattern never registers twice."""
    slug_type = "".join(ch if ch.isalnum() else "-" for ch in task_type.lower()).strip("-") or "goal"
    slug_tools = "-".join(tools) or "notool"
    raw = f"auto-{slug_type}-{slug_tools}"[:64]
    # SkillSpec.id pattern requires 3-64 lowercase alnum/hyphen chars.
    return raw if len(raw) >= 3 else (raw + "-x")


class SkillAutoPromoter:
    """Closes the loop from repeated real experience to a taught skill.

    When the SAME deterministic tool sequence has succeeded at least
    `min_repetitions` times for the SAME kind of goal (task_type), this
    automatically calls the EXISTING TeachableSkillService to record
    (not activate — activation stays an explicit step per
    app/skills/teachable.py) a new taught skill from that pattern.

    Never invents a tool: every step's tool must already be a
    registered tool (TeachableSkillCreate validates this itself), so a
    pattern naming an unknown tool is silently skipped rather than
    raising.
    """

    def __init__(self, experience_store: ExperienceStore, teachable_skills, *, min_repetitions: int = 3):
        self.store = experience_store
        self.teachable_skills = teachable_skills
        self.min_repetitions = min_repetitions

    async def consider(self, *, task_type: str, domain: str, tools_used: list[str]) -> object | None:
        """Returns the newly-created SkillSpec, or None (not enough
        repetitions yet, tool unknown, or an equivalent skill already
        exists)."""
        tools = tuple(t for t in (tools_used or []) if t)
        if not tools or not task_type or task_type == "general":
            return None

        experiences = await self.store._all()
        matches = [
            experience for experience in experiences
            if experience.success
            and experience.task_type == task_type
            and experience.domain == domain
            and tuple(experience.tools_used) == tools
        ]
        if len(matches) < self.min_repetitions:
            return None

        skill_id = skill_id_for(task_type, tools)
        if self.teachable_skills.registry.get(skill_id) is not None:
            return None  # already promoted from this exact pattern

        from app.schemas.approvals import PermissionLevel
        from app.skills.schemas import SkillStep
        from app.skills.teachable import TeachableSkillCreate

        steps = [
            SkillStep(
                id=f"step_{index}",
                action=f"repeat_{tool}",
                capability=f"{tool}.execute",
                tool=tool,
            )
            for index, tool in enumerate(tools)
        ]
        payload = TeachableSkillCreate(
            id=skill_id,
            name=f"Auto-learned: {task_type} via {', '.join(tools)}",
            description=(
                f"Automatically taught after {len(matches)} verified successful runs of the "
                f"same tool sequence ({', '.join(tools)}) for {task_type} tasks in the {domain} domain."
            ),
            category="auto-taught",
            steps=steps,
            verification_checks=["all_steps_succeeded"],
            required_permissions=PermissionLevel.L1,
        )
        try:
            return self.teachable_skills.create(payload, created_by="self-improvement-loop")
        except ValueError:
            # Registry found an equivalent skill by name/description
            # similarity, or the tool is unknown to this process's tool
            # registry — either way, do not create a duplicate/invalid skill.
            return None
