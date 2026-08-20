from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from app.chief_of_staff.orchestrator import ChiefOfStaffContext, ChiefOfStaffOrchestrator
from app.chief_of_staff.priority_engine import PrioritySignal
from app.crm.store import CRMStore
from app.daily_review.evening import EveningReviewInput, EveningReviewService
from app.daily_review.morning import MorningBriefingInput, MorningBriefingService
from app.daily_review.weekly import WeeklyReviewInput, WeeklyReviewService
from app.goals.evaluator import GoalEvaluator
from app.goals.manager import GoalManager
from app.goals.milestones import MilestoneService
from app.goals.progress import GoalEvidence
from app.goals.schemas import GoalStatus
from app.habits.insights import HabitInsightService
from app.habits.schemas import DesiredDirection, HabitEventSource, HabitStatus
from app.habits.store import HabitEventStore, HabitStore
from app.notifications.quiet_hours import QuietModeState
from app.personal.commitments import CommitmentService
from app.personal.context_builder import PersonalContextBuilder
from app.personal.profile import PersonalProfileService
from app.personal.schemas import CommitmentStatus
from app.productivity.focus_sessions import FocusSessionResult, FocusSessionService
from app.productivity.workload import WorkloadCalculator, WorkloadSignals
from app.routines.completion import RoutineCompletionService
from app.routines.manager import RoutineManager
from app.persistence.task_store import TaskStore
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskProfile, TaskStatus

from .extraction import extract_focus_goal, extract_focus_minutes, extract_goal_title, extract_quiet_minutes, infer_goal_category

EventEmitter = Callable[[str, str, dict], Awaitable[None]]


def _frame(x: float, y: float, width: float, layer: int | None = None) -> dict:
    frame = {"x": x, "y": y, "width": width}
    if layer:
        frame["layer"] = layer
    return frame


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Understanding", "Planning", "Executing", "Verifying", "Completed"]
    sequence = []
    for index, item in enumerate(objects):
        sequence.append({"id": f"reveal-{index}", "label": item.get("eyebrow", item["title"]), "atMs": index * 320, "state": states[min(index, len(states) - 1)], "objectIds": [item["id"]]})
    return {"schemaVersion": 1, "id": identifier, "mode": mode, "label": label, "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(), "objects": objects, "sequence": sequence}


class Phase11Engine:
    """Personal Life Operating System and Chief-of-Staff layer. Mirrors
    Phase8Engine/Phase9Engine/Phase10Engine: a deterministic
    intent-to-workflow runtime the Task Runtime delegates to before
    reaching for a paid model (rule 74). This layer consumes the existing
    goal/habit/routine/focus/commitment/CRM/task systems — it never
    bypasses their permission boundaries (rule 26)."""

    INTENTS = {
        "plan_today", "what_now", "evening_review", "weekly_review", "goal_create", "goal_status",
        "habits_status", "bad_habit_query", "commitments_query", "focus_start", "focus_pause",
        "focus_complete", "quiet_mode_start", "routine_run",
    }

    def __init__(
        self,
        *,
        personal_profile_service: PersonalProfileService,
        commitment_service: CommitmentService,
        context_builder: PersonalContextBuilder,
        goal_manager: GoalManager,
        goal_evaluator: GoalEvaluator,
        milestone_service: MilestoneService,
        habit_store: HabitStore,
        habit_event_store: HabitEventStore,
        habit_insight_service: HabitInsightService,
        routine_manager: RoutineManager,
        routine_completion_service: RoutineCompletionService,
        focus_service: FocusSessionService,
        workload_calculator: WorkloadCalculator,
        chief_of_staff: ChiefOfStaffOrchestrator,
        quiet_mode: QuietModeState,
        morning_service: MorningBriefingService,
        evening_service: EveningReviewService,
        weekly_service: WeeklyReviewService,
        crm_store: CRMStore,
        task_store: TaskStore,
    ) -> None:
        self.personal_profile_service = personal_profile_service
        self.commitment_service = commitment_service
        self.context_builder = context_builder
        self.goal_manager = goal_manager
        self.goal_evaluator = goal_evaluator
        self.milestone_service = milestone_service
        self.habit_store = habit_store
        self.habit_event_store = habit_event_store
        self.habit_insight_service = habit_insight_service
        self.routine_manager = routine_manager
        self.routine_completion_service = routine_completion_service
        self.focus_service = focus_service
        self.workload_calculator = workload_calculator
        self.chief_of_staff = chief_of_staff
        self.quiet_mode = quiet_mode
        self.morning_service = morning_service
        self.evening_service = evening_service
        self.weekly_service = weekly_service
        self.crm_store = crm_store
        self.task_store = task_store
        self._last_focus_session: dict[str, str] = {}

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        handlers = {
            "plan_today": self._plan_today, "what_now": self._what_now, "evening_review": self._evening_review,
            "weekly_review": self._weekly_review, "goal_create": self._goal_create, "goal_status": self._goal_status,
            "habits_status": self._habits_status, "bad_habit_query": self._bad_habit_query,
            "commitments_query": self._commitments_query, "focus_start": self._focus_start,
            "focus_pause": self._focus_pause, "focus_complete": self._focus_complete,
            "quiet_mode_start": self._quiet_mode_start, "routine_run": self._routine_run,
        }
        return await handlers[profile.intent](task, emit)

    # -- Shared context assembly ------------------------------------------

    async def _chief_of_staff_context(self) -> ChiefOfStaffContext:
        approvals = await self.task_store.list_by_status({TaskStatus.NEEDS_APPROVAL})
        goals = await self.goal_manager.list(GoalStatus.ACTIVE)
        overdue = [c for c in await self.commitment_service.overdue()]
        open_commitments = [c for c in await self.commitment_service.open_commitments() if c.status == CommitmentStatus.OPEN]
        neglected = [self.goal_evaluator.evaluate(goal) for goal in goals]

        candidate_actions: list[PrioritySignal] = []
        for goal in goals:
            if goal.next_action:
                candidate_actions.append(PrioritySignal(
                    item_id=goal.id, label=f"{goal.next_action} (goal: {goal.title})",
                    importance=0.7, goal_alignment=1.0, urgency=0.3 if goal.target_date else 0.2,
                ))
        for commitment in overdue:
            candidate_actions.append(PrioritySignal(item_id=commitment.id, label=commitment.description, urgency=0.9, importance=0.8, risk=0.6))
        for approval in approvals[:5]:
            candidate_actions.append(PrioritySignal(item_id=approval.id, label=f"Review: {approval.user_request[:80]}", urgency=0.6, importance=0.6, dependency=0.7))

        workload = self.workload_calculator.calculate(WorkloadSignals(pending_approvals=len(approvals)))

        return ChiefOfStaffContext(
            candidate_actions=candidate_actions, workload=workload, open_commitments=open_commitments,
            overdue_commitments=overdue, neglected_goals=neglected, pending_approvals=len(approvals),
            agents_awaiting_approval=[f"Task {a.id[:12]} waiting on approval" for a in approvals[:3]],
        )

    # -- Daily planning / recommendation -----------------------------------

    async def _plan_today(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        context = await self._chief_of_staff_context()
        briefing = self.chief_of_staff.brief(context)
        await emit("daily_plan_created", "Assembled today's plan from real context", {"priority_count": len(briefing.ranked_priorities)})

        conflict = await self._schedule_conflict_warning()

        top_rows = [[score.label, round(score.score, 3), "; ".join(score.reasons)] for score in briefing.ranked_priorities[:6]]
        objects = [
            {"id": "priorities", "type": "daily-plan-timeline", "title": "Today's priorities", "eyebrow": f"{len(briefing.ranked_priorities)} item(s)", "tone": "intelligence", "frame": _frame(4, 12, 50), "rows": top_rows},
            {"id": "risks", "type": "priority-stack", "title": "Needs attention", "eyebrow": f"{len(briefing.needs_attention)} item(s)", "tone": "attention" if briefing.needs_attention else "verified", "frame": _frame(58, 12, 38), "items": [r.description for r in briefing.needs_attention] or ["Nothing at risk right now"]},
        ]
        if briefing.recommendation.primary:
            objects.append({"id": "recommendation", "type": "verified-result", "title": "Recommended next action", "eyebrow": "One strong recommendation", "tone": "verified", "frame": _frame(4, 62, 50), "statement": f"{briefing.recommendation.primary.action}: {briefing.recommendation.primary.reason}", "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()})
        if conflict:
            objects.append({"id": "conflict", "type": "verified-result", "title": "Schedule note", "eyebrow": "Personal preference", "tone": "attention", "frame": _frame(58, 62, 38), "statement": conflict, "evidence": ["personal_profile:work_cutoff_time"], "timestamp": datetime.now(timezone.utc).isoformat()})

        summary = f"Today's plan: {len(briefing.ranked_priorities)} candidate item(s), {len(briefing.needs_attention)} needing attention."
        if briefing.recommendation.primary:
            summary += f" Top recommendation: {briefing.recommendation.primary.action}."
        composition = _composition(f"plan-{task.id}", "brain-context", "Today's plan", summary, objects)
        return ExecutionResult(response=summary, structured_data=briefing.model_dump(mode="json"), ui_composition=composition, evidence=[f"candidate_actions:{len(context.candidate_actions)}"])

    async def _what_now(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        context = await self._chief_of_staff_context()
        briefing = self.chief_of_staff.brief(context)
        if briefing.recommendation.primary is None:
            statement = "No recorded work is currently outstanding."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        rec = briefing.recommendation.primary
        statement = f"{rec.action}. {rec.reason}."
        obj = {"id": "now", "type": "verified-result", "title": "Do this now", "eyebrow": "One recommendation", "tone": "verified", "frame": _frame(16, 18, 48), "statement": statement, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
        composition = _composition(f"now-{task.id}", "brain-context", "What now", statement, [obj])
        return ExecutionResult(response=statement, structured_data=briefing.recommendation.model_dump(mode="json"), ui_composition=composition, evidence=[])

    async def _schedule_conflict_warning(self) -> str | None:
        """Rule 52/59: a stated personal boundary can genuinely conflict
        with current activity; VYOM warns using real evidence (the current
        time relative to the user's own stated cutoff) — never invented,
        and gated so it doesn't repeat every single interaction (the
        caller only calls this from the daily-plan path, not every turn)."""
        cutoff = await self.personal_profile_service.field_value("work_cutoff_time")
        if not cutoff:
            return None
        now = datetime.now(timezone.utc)
        cutoff_hour, cutoff_minute = (int(part) for part in str(cutoff).split(":"))
        cutoff_today = now.replace(hour=cutoff_hour, minute=cutoff_minute, second=0, microsecond=0)
        if now >= cutoff_today and now.hour < 5:
            return f"It's past your stated work cutoff ({cutoff}). You mentioned wanting to avoid working after this time."
        return None

    # -- Goals ---------------------------------------------------------------

    async def _goal_create(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        title = extract_goal_title(task.user_request)
        category = infer_goal_category(task.user_request)
        goal, plan = await self.goal_manager.create(title, category=category)
        await emit("goal_created", f"Created goal: {title}", {"goal_id": goal.id, "category": category.value})
        milestones = await self.milestone_service.list_for_goal(goal.id)

        statement = f"Goal created: {title}. {len(milestones)} starting milestone(s); next action: {goal.next_action or 'none yet'}."
        obj = {
            "id": "goal", "type": "goal-progress-path", "title": title, "eyebrow": f"{category.value} · {goal.status.value}",
            "tone": "intelligence", "frame": _frame(8, 14, 52), "milestones": [{"title": m.title, "status": m.status.value} for m in milestones],
            "nextAction": goal.next_action,
        }
        composition = _composition(f"goal-{task.id}", "brain-context", "New goal", statement, [obj])
        return ExecutionResult(response=statement, structured_data={"goal": goal.model_dump(mode="json"), "plan": plan.model_dump(mode="json")}, ui_composition=composition, evidence=[f"goal_id:{goal.id}"])

    async def _goal_status(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        goals = await self.goal_manager.list()
        if not goals:
            statement = "No goals have been created yet."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        goal = goals[0]
        milestones = await self.milestone_service.list_for_goal(goal.id)

        crm_progress = None
        if goal.category.value == "business":
            counts = await self.crm_store.counts()
            won = counts.get("won", 0)
            total_target = 10  # honest placeholder only used when the goal itself doesn't define a numeric target
            crm_progress = min(1.0, won / total_target) if won else None

        result = await self.goal_manager.record_progress(goal.id, GoalEvidence(crm_progress=crm_progress) if crm_progress is not None else None)
        health = self.goal_evaluator.evaluate(goal)

        statement = f"{goal.title}: "
        statement += f"{result.progress:.0%} ({result.basis})." if result.progress is not None else "no evidence-based progress yet."
        if health.neglected:
            statement += f" {'; '.join(health.reasons)}."
        if goal.next_action:
            statement += f" Next action: {goal.next_action}."

        obj = {
            "id": "goal-status", "type": "goal-progress-path", "title": goal.title, "eyebrow": f"{goal.category.value} · {goal.status.value}",
            "tone": "attention" if health.neglected else "verified", "frame": _frame(8, 14, 52),
            "milestones": [{"title": m.title, "status": m.status.value} for m in milestones], "nextAction": goal.next_action,
            "progress": result.progress,
        }
        composition = _composition(f"goal-status-{task.id}", "brain-context", goal.title, statement, [obj])
        return ExecutionResult(response=statement, structured_data={"goal": goal.model_dump(mode="json"), "progress": result.model_dump(mode="json"), "health": health.model_dump(mode="json")}, ui_composition=composition, evidence=result.sample_evidence)

    # -- Habits ---------------------------------------------------------------

    async def _habits_status(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        habits = await self.habit_store.list(HabitStatus.ACTIVE)
        if not habits:
            statement = "No habits are being tracked yet."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])

        objects = []
        messages = []
        for habit in habits[:5]:
            events = await self.habit_event_store.list_for_habit(habit.id)
            report = self.habit_insight_service.report(habit, events)
            messages.append(report.message)
            if report.insight:
                await emit("habit_pattern_detected", report.insight.statement, {"habit_id": habit.id, "confidence": report.insight.confidence})
            objects.append({
                "id": f"habit-{habit.id}", "type": "habit-trend", "title": habit.name, "eyebrow": habit.desired_direction.value,
                "tone": "verified" if report.sufficient_data else "neutral", "frame": _frame(6 + (len(objects) % 2) * 48, 14 + (len(objects) // 2) * 30, 44),
                "consistencyPct": report.streaks.consistency_trend_pct if report.streaks else None, "message": report.message,
                "intervention": report.intervention.description if report.intervention else None,
            })
        summary = " ".join(messages) if messages else "No habit data yet."
        composition = _composition(f"habits-{task.id}", "brain-context", "Habits", summary, objects)
        return ExecutionResult(response=summary, structured_data={"habits": [h.model_dump(mode="json") for h in habits]}, ui_composition=composition, evidence=[])

    async def _bad_habit_query(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        habits = [h for h in await self.habit_store.list(HabitStatus.ACTIVE) if h.desired_direction in (DesiredDirection.REDUCE, DesiredDirection.AVOID)]
        if not habits:
            statement = "No reduce/avoid habit is currently tracked, so VYOM has no evidence to analyze."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        habit = habits[0]
        events = await self.habit_event_store.list_for_habit(habit.id)

        unfinished_days = {event.timestamp.date() for event in events if event.note and "unfinished" in event.note.lower()}
        report = self.habit_insight_service.bad_habit_analysis(habit, events, unfinished_days, "unfinished work sessions")
        tone = "verified" if report.sufficient_data else "attention"
        if report.insight:
            await emit("habit_insight_created", report.insight.statement, {"habit_id": habit.id})
        obj = {"id": "bad-habit", "type": "habit-trend", "title": habit.name, "eyebrow": "Pattern analysis", "tone": tone, "frame": _frame(10, 16, 50), "message": report.message, "intervention": report.intervention.description if report.intervention else None}
        composition = _composition(f"bad-habit-{task.id}", "brain-context", habit.name, report.message, [obj])
        return ExecutionResult(response=report.message, structured_data=report.model_dump(mode="json"), ui_composition=composition, evidence=[])

    # -- Commitments ------------------------------------------------------------

    async def _commitments_query(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        commitments = await self.commitment_service.open_commitments()
        overdue = [c for c in commitments if c.status == CommitmentStatus.OVERDUE]
        statement = f"You have {len(commitments)} open commitment(s), {len(overdue)} overdue."
        rows = [[c.description, c.recipient or "-", c.deadline.isoformat() if c.deadline else "no deadline", c.status.value] for c in commitments[:8]]
        obj = {"id": "commitments", "type": "comparison-table", "title": "What you owe", "eyebrow": f"{len(commitments)} open", "tone": "attention" if overdue else "neutral", "frame": _frame(8, 14, 56), "headers": ["Commitment", "To", "Deadline", "Status"], "rows": rows or [["Nothing recorded", "-", "-", "-"]]}
        composition = _composition(f"commitments-{task.id}", "brain-context", "Commitments", statement, [obj])
        return ExecutionResult(response=statement, structured_data={"commitments": [c.model_dump(mode="json") for c in commitments]}, ui_composition=composition, evidence=[f"commitment_id:{c.id}" for c in commitments[:5]])

    # -- Focus --------------------------------------------------------------------

    async def _focus_start(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        goal = extract_focus_goal(task.user_request)
        minutes = extract_focus_minutes(task.user_request)
        try:
            session = await self.focus_service.start(goal, planned_minutes=minutes)
        except ValueError as error:
            statement = str(error)
            return ExecutionResult(response=statement, structured_data={"started": False}, evidence=[])
        self._last_focus_session[task.id] = session.id
        await emit("focus_started", f"Focus session started: {goal}", {"session_id": session.id, "planned_minutes": minutes})
        statement = f"Focus session started on '{goal}' for {minutes:.0f} minute(s). Low-priority notifications are suppressed until it ends."
        obj = {"id": "focus", "type": "focus-mission", "title": goal, "eyebrow": f"{minutes:.0f} min planned", "tone": "intelligence", "frame": _frame(16, 18, 48), "sessionId": session.id, "status": "active"}
        composition = _composition(f"focus-{task.id}", "brain-context", "Focus session", statement, [obj])
        return ExecutionResult(response=statement, structured_data=session.model_dump(mode="json"), ui_composition=composition, evidence=[f"session_id:{session.id}"])

    async def _focus_pause(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        active = await self.focus_service.store.active()
        if active is None:
            return ExecutionResult(response="No focus session is currently active.", structured_data={"paused": False}, evidence=[])
        session = await self.focus_service.pause(active.id)
        await emit("focus_paused", "Focus session paused", {"session_id": session.id})
        statement = f"Focus session on '{session.goal}' paused."
        return ExecutionResult(response=statement, structured_data=session.model_dump(mode="json"), evidence=[f"session_id:{session.id}"])

    async def _focus_complete(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        active = await self.focus_service.store.active()
        if active is None:
            return ExecutionResult(response="No focus session is currently active to complete.", structured_data={"completed": False}, evidence=[])
        result = FocusSessionResult.COMPLETED if active.interruptions == 0 else FocusSessionResult.PARTIAL
        session = await self.focus_service.complete(active.id, result=result)
        await emit("focus_completed", f"Focus session completed: {session.goal}", {"session_id": session.id, "duration_minutes": session.duration_minutes})
        statement = f"Focus session on '{session.goal}' completed: {session.duration_minutes:.1f} minute(s), {session.interruptions} interruption(s)."
        obj = {"id": "focus-complete", "type": "verified-result", "title": "Focus session complete", "eyebrow": session.result.value if session.result else "completed", "tone": "verified", "frame": _frame(16, 18, 48), "statement": statement, "evidence": [f"duration_minutes:{session.duration_minutes}"], "timestamp": datetime.now(timezone.utc).isoformat()}
        composition = _composition(f"focus-complete-{task.id}", "brain-context", "Focus complete", statement, [obj])
        return ExecutionResult(response=statement, structured_data=session.model_dump(mode="json"), ui_composition=composition, evidence=[f"session_id:{session.id}"])

    # -- Routines -------------------------------------------------------------------

    async def _routine_run(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        routines = await self.routine_manager.list()
        if not routines:
            return ExecutionResult(response="No routine is defined yet.", structured_data={"available": False}, evidence=[])
        routine = routines[0]
        await emit("routine_started", f"Running routine: {routine.name}", {"routine_id": routine.id})
        run = await self.routine_completion_service.run(routine)
        event_type = "routine_completed" if run.status.value == "completed" else "routine_missed"
        await emit(event_type, f"Routine run finished: {run.status.value}", {"routine_id": routine.id, "run_id": run.id})
        statement = f"Routine '{routine.name}' finished with status {run.status.value} ({len(run.step_results)} step(s))."
        obj = {"id": "routine", "type": "routine-sequence", "title": routine.name, "eyebrow": run.status.value, "tone": "verified" if run.status.value == "completed" else "attention", "frame": _frame(10, 16, 50), "steps": [{"type": r.type.value, "status": r.status.value, "detail": r.detail} for r in run.step_results]}
        composition = _composition(f"routine-{task.id}", "brain-context", routine.name, statement, [obj])
        return ExecutionResult(response=statement, structured_data=run.model_dump(mode="json"), ui_composition=composition, evidence=[f"run_id:{run.id}"])

    # -- Reviews ---------------------------------------------------------------------

    async def _evening_review(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        now = datetime.now(timezone.utc)
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)
        completed_tasks = await self.task_store.list_by_status({TaskStatus.COMPLETED})
        today_tasks = [t for t in completed_tasks if t.completed_at and t.completed_at >= since]

        sessions = await self.focus_service.store.list(limit=20)
        today_sessions = [s for s in sessions if s.start >= since and s.status.value == "completed"]
        focus_minutes = sum(s.duration_minutes or 0 for s in today_sessions)
        best_window = None
        if today_sessions:
            longest = max(today_sessions, key=lambda s: s.duration_minutes or 0)
            if longest.duration_minutes and longest.end:
                best_window = f"{longest.start.strftime('%H:%M')}–{longest.end.strftime('%H:%M')}"

        overdue = await self.commitment_service.overdue()
        open_commitments = [c for c in await self.commitment_service.open_commitments() if c.status == CommitmentStatus.OPEN]

        review = self.evening_service.build(EveningReviewInput(
            tasks_completed=[t.goal for t in today_tasks], commitments_open=[c.description for c in open_commitments],
            focus_session_minutes=focus_minutes, best_focus_window=best_window,
            missed_priorities=[c.description for c in overdue],
        ))
        await emit("evening_review_ready", review.summary, {"completed_count": len(review.completed)})
        obj = {"id": "evening", "type": "verified-result", "title": "Evening review", "eyebrow": "From real recorded events", "tone": "verified", "frame": _frame(10, 16, 56), "statement": review.summary, "evidence": review.completed[:5], "timestamp": now.isoformat()}
        composition = _composition(f"evening-{task.id}", "brain-context", "Evening review", review.summary, [obj])
        return ExecutionResult(response=review.summary, structured_data=review.model_dump(mode="json"), ui_composition=composition, evidence=review.completed[:5])

    async def _weekly_review(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        overdue = await self.commitment_service.overdue()
        goals = await self.goal_manager.list(GoalStatus.ACTIVE)
        goal_notes = []
        for goal in goals[:5]:
            result = await self.goal_manager.record_progress(goal.id)
            if result.progress is not None:
                goal_notes.append(f"{goal.title}: {result.progress:.0%}")
        counts = await self.crm_store.counts()
        client_notes = [f"{state}: {count}" for state, count in counts.items() if count]

        review = self.weekly_service.build(WeeklyReviewInput(
            unfinished_commitments=[c.description for c in overdue], goal_progress_notes=goal_notes,
            client_status_notes=client_notes, next_week_priorities=[g.next_action for g in goals if g.next_action][:3],
        ))
        await emit("weekly_review_ready", review.summary, {"section_count": len(review.sections)})
        rows = [[key.replace("_", " ").title(), "; ".join(values[:3])] for key, values in review.sections.items()]
        obj = {"id": "weekly", "type": "comparison-table", "title": "Weekly review", "eyebrow": review.summary, "tone": "intelligence", "frame": _frame(8, 14, 56), "headers": ["Area", "Notes"], "rows": rows or [["No recorded activity", "-"]]}
        composition = _composition(f"weekly-{task.id}", "brain-context", "Weekly review", review.summary, [obj])
        return ExecutionResult(response=review.summary, structured_data=review.model_dump(mode="json"), ui_composition=composition, evidence=[])

    # -- Notifications ----------------------------------------------------------------

    async def _quiet_mode_start(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        minutes = extract_quiet_minutes(task.user_request)
        until = self.quiet_mode.start(minutes)
        await emit("quiet_mode_started", f"Quiet mode active for {minutes:.0f} minute(s)", {"until": until.isoformat()})
        statement = f"Quiet mode on for {minutes:.0f} minute(s), until {until.strftime('%H:%M')}. Critical notifications will still come through."
        return ExecutionResult(response=statement, structured_data={"until": until.isoformat()}, evidence=[])
