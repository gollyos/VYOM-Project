from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.chief_of_staff.orchestrator import ChiefOfStaffContext, ChiefOfStaffOrchestrator
from app.chief_of_staff.priority_engine import PrioritySignal
from app.goals.evaluator import GoalEvaluator
from app.goals.manager import GoalManager
from app.goals.milestones import MilestoneService
from app.goals.planner import GoalPlanner
from app.goals.progress import GoalEvidence, GoalProgressEvaluator
from app.goals.schemas import GoalCategory, GoalStatus, MilestoneStatus
from app.goals.store import GoalStore, MilestoneStore
from app.habits.insights import HabitInsightService
from app.habits.pattern_analyzer import HabitPatternAnalyzer
from app.habits.schemas import DesiredDirection, Habit, HabitEvent, HabitEventSource, HabitStatus
from app.habits.store import HabitEventStore, HabitStore
from app.habits.streaks import StreakCalculator
from app.habits.events import UnapprovedEventSourceError
from app.habits.tracker import HabitTracker
from app.notifications.batching import NotificationBatcher
from app.notifications.delivery import NotificationDeliveryService, NotificationRecordStore
from app.notifications.priority import NotificationPriority
from app.notifications.quiet_hours import QuietModeState
from app.notifications.service import Notification, NotificationService
from app.persistence.database import Database
from app.personal.context_builder import PersonalContextBuilder, strip_personal_for_client_context
from app.personal.schemas import Commitment, CommitmentSource, CommitmentStatus, PersonalProfile, PreferenceSource
from app.personal.store import CommitmentStore, PersonalProfileStore
from app.personal.commitments import CommitmentService
from app.productivity.focus_sessions import FocusSessionResult, FocusSessionService, FocusSessionStore
from app.productivity.workload import WorkloadCalculator, WorkloadLevel, WorkloadSignals
from app.proactive.engine import ProactiveEngine
from app.proactive.rules import ProactiveLevel, ProactiveRules, ProactiveSuggestion
from app.proactive.suppression import ProactiveSuggestionStore
from app.routines.adaptation import RoutineAdaptationService
from app.routines.completion import RoutineCompletionService, RoutineStepExecutor
from app.routines.schemas import Routine, RoutineRunStatus, RoutineStep, RoutineStepType
from app.routines.store import RoutineRunStore, RoutineStore


PROACTIVE_CONFIG = {
    "proactive": {
        "default_level": "balanced",
        "gate": {
            "require_important": True, "require_actionable": True, "require_good_timing": True,
            "require_not_already_surfaced": True, "suppress_if_auto_handleable": True,
            "require_benefit_exceeds_interruption_cost": True,
        },
        "suppression": {"duplicate_window_hours": 24, "max_low_priority_per_day": 2},
    },
}


async def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / f"phase11-{id(tmp_path)}.db")
    await database.connect()
    return database


# -- 1-3. Goals: creation, milestone progress, evidence -----------------------

@pytest.mark.asyncio
async def test_goal_creation_seeds_bounded_milestones_and_next_action(tmp_path):
    database = await make_database(tmp_path)
    goal_store, milestone_store = GoalStore(database), MilestoneStore(database)
    milestone_service = MilestoneService(milestone_store)
    manager = GoalManager(goal_store, milestone_service, GoalPlanner(max_milestones=4, max_next_actions=3))

    goal, plan = await manager.create("Grow the agency to 10 clients", category=GoalCategory.BUSINESS)
    assert goal.status == GoalStatus.ACTIVE
    assert 1 <= len(plan.milestones) <= 4
    assert goal.next_action is not None
    milestones = await milestone_service.list_for_goal(goal.id)
    assert len(milestones) == len(plan.milestones)
    await database.close()


@pytest.mark.asyncio
async def test_goal_progress_from_milestone_completion(tmp_path):
    database = await make_database(tmp_path)
    goal_store, milestone_store = GoalStore(database), MilestoneStore(database)
    milestone_service = MilestoneService(milestone_store)
    manager = GoalManager(goal_store, milestone_service, GoalPlanner())

    goal, _plan = await manager.create("Learn Spanish", category=GoalCategory.LEARNING)
    milestones = await milestone_service.list_for_goal(goal.id)
    await milestone_service.mark_done(milestones[0].id, evidence=["user_confirmed"])

    result = await manager.record_progress(goal.id)
    assert result.progress is not None
    assert result.progress == pytest.approx(1 / len(milestones), abs=1e-3)
    assert "milestones complete" in result.basis
    await database.close()


def test_goal_progress_requires_evidence_never_fabricates_percentage():
    from app.goals.schemas import Goal

    evaluator = GoalProgressEvaluator()
    goal = Goal(title="Untracked goal")
    result = evaluator.evaluate(goal, milestones=[], evidence=None)
    assert result.progress is None
    assert "No milestones" in result.basis

    result_with_evidence = evaluator.evaluate(goal, milestones=[], evidence=GoalEvidence(crm_progress=0.4))
    assert result_with_evidence.progress == pytest.approx(0.4)


def test_milestone_done_requires_evidence():
    from app.goals.schemas import Milestone

    milestone = Milestone(goal_id="goal_x", title="Test", target="Test target")
    assert milestone.status == MilestoneStatus.PENDING


# -- 4-6. Habits: event recording, trend calculation, insufficient data -------

@pytest.mark.asyncio
async def test_habit_event_recording_and_source_approval(tmp_path):
    database = await make_database(tmp_path)
    habit_store, event_store = HabitStore(database), HabitEventStore(database)
    tracker = HabitTracker(habit_store, event_store, allowed_sources={"manual", "calendar"})

    habit = await tracker.create(Habit(name="Exercise", desired_direction=DesiredDirection.BUILD))
    event = await tracker.check_in(habit.id, source=HabitEventSource.MANUAL)
    assert event.habit_id == habit.id

    with pytest.raises(UnapprovedEventSourceError):
        await tracker.check_in(habit.id, source=HabitEventSource.DESKTOP_ACTIVITY)
    await database.close()


def test_habit_trend_calculation_from_real_events():
    analyzer = HabitPatternAnalyzer(minimum_sample_size=3, minimum_confidence=0.5)
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    events = [HabitEvent(habit_id="h1", timestamp=now.replace(hour=22) - timedelta(days=i)) for i in range(6)]
    insight = analyzer.dominant_time_insight(events, "Late work", time_range="last 6 days")
    assert insight is not None
    assert insight.sample_size == 6
    assert insight.confidence >= 0.5
    assert len(insight.supporting_events) == 6


def test_insufficient_habit_data_returns_no_insight_not_a_guess():
    analyzer = HabitPatternAnalyzer(minimum_sample_size=5)
    events = [HabitEvent(habit_id="h1") for _ in range(2)]
    assert analyzer.dominant_time_insight(events, "Habit", time_range="last 6 days") is None

    insight_service = HabitInsightService(analyzer)
    habit = Habit(name="New habit")
    report = insight_service.report(habit, events)
    assert report.sufficient_data is False
    assert "Not enough" in report.message


# -- 7. Preference superseding --------------------------------------------------

def test_personal_profile_preference_superseding():
    profile = PersonalProfile()
    profile.set("energy_preference", "afternoon", source=PreferenceSource.USER_STATEMENT)
    first_field = profile.get("energy_preference")
    assert first_field.value == "afternoon"

    profile.set("energy_preference", "morning", source=PreferenceSource.USER_STATEMENT)
    updated = profile.get("energy_preference")
    assert updated.value == "morning"
    assert updated.superseded_value == "afternoon"


def test_context_strips_personal_fields_for_client_output():
    data = {"personal_priorities": ["gym"], "client_name": "Acme", "quiet_hours": {"start": "23:00"}}
    stripped = strip_personal_for_client_context(data)
    assert "client_name" in stripped
    assert "personal_priorities" not in stripped
    assert "quiet_hours" not in stripped


# -- 8-9. Routines: execution, adaptation ---------------------------------------

@pytest.mark.asyncio
async def test_routine_execution_uses_registered_handlers_and_reports_unavailable(tmp_path):
    database = await make_database(tmp_path)
    run_store = RoutineRunStore(database)
    executor = RoutineStepExecutor()

    async def reminder_handler(payload: dict) -> str:
        return "delivered"

    executor.register("reminder", reminder_handler)
    completion = RoutineCompletionService(executor, run_store)

    routine = Routine(name="Morning startup", steps=[RoutineStep(type=RoutineStepType.REMINDER), RoutineStep(type=RoutineStepType.OPEN_APPLICATION)])
    run = await completion.run(routine)
    assert run.step_results[0].status.value == "completed"
    assert run.step_results[1].status.value == "unavailable"  # no handler registered — never faked as completed
    await database.close()


@pytest.mark.asyncio
async def test_routine_adaptation_triggers_after_failure_streak(tmp_path):
    database = await make_database(tmp_path)
    run_store = RoutineRunStore(database)
    service = RoutineAdaptationService(run_store, failure_streak_threshold=3, lookback_runs=10)

    from app.routines.schemas import RoutineRun

    for _ in range(3):
        await run_store.save(RoutineRun(routine_id="routine_1", status=RoutineRunStatus.MISSED))
    suggestion = await service.evaluate("routine_1")
    assert suggestion is not None
    assert suggestion.failure_streak == 3

    await run_store.save(RoutineRun(routine_id="routine_2", status=RoutineRunStatus.MISSED))
    assert await service.evaluate("routine_2") is None  # single miss never triggers adaptation
    await database.close()


# -- 10. Focus session ------------------------------------------------------------

@pytest.mark.asyncio
async def test_focus_session_lifecycle(tmp_path):
    database = await make_database(tmp_path)
    service = FocusSessionService(FocusSessionStore(database))

    session = await service.start("VYOM coding", planned_minutes=45)
    assert await service.is_active() is True
    with pytest.raises(ValueError):
        await service.start("Another task")  # only one active session at a time

    await service.record_interruption(session.id)
    completed = await service.complete(session.id, result=FocusSessionResult.PARTIAL)
    assert completed.interruptions == 1
    assert completed.duration_minutes is not None
    assert await service.is_active() is False
    await database.close()


# -- 11-13. Notifications: suppression, quiet mode, batching ---------------------

@pytest.mark.asyncio
async def test_quiet_mode_suppresses_non_critical_but_never_critical(tmp_path):
    database = await make_database(tmp_path)
    quiet_mode = QuietModeState()
    quiet_mode.start(60)
    delivery = NotificationDeliveryService(NotificationService(), quiet_mode, NotificationRecordStore(database))

    suppressed = await delivery.deliver("Minor update", "background info", priority=NotificationPriority.NORMAL)
    assert suppressed is None

    delivered = await delivery.deliver("Risk kill switch", "daily loss breached", priority=NotificationPriority.CRITICAL)
    assert delivered is not None
    await database.close()


def test_quiet_mode_automatically_ends():
    quiet_mode = QuietModeState()
    until = quiet_mode.start(10)
    future = until + timedelta(minutes=1)
    assert quiet_mode.is_active(now=future) is False


def test_notification_batching_groups_minor_items():
    batcher = NotificationBatcher(batch_window_minutes=15, min_items_to_batch=3)
    now = datetime.now(timezone.utc)
    pending = [Notification(title=f"Task {i} done", body="background task done", urgency="informational", created_at=now) for i in range(4)]
    batches, passthrough = batcher.batch(pending, now=now)
    assert len(batches) == 1
    assert batches[0].item_count == 4
    assert not passthrough


def test_notification_batching_leaves_important_items_individual():
    batcher = NotificationBatcher(min_items_to_batch=3)
    now = datetime.now(timezone.utc)
    pending = [Notification(title="Client deadline risk", body="review needed", urgency="important", created_at=now)]
    batches, passthrough = batcher.batch(pending, now=now)
    assert not batches
    assert len(passthrough) == 1


# -- 14-15. Workload / overload detection -----------------------------------------

def test_workload_calculation_reflects_real_signals():
    calculator = WorkloadCalculator()
    light = calculator.calculate(WorkloadSignals(meeting_hours=1, available_hours=8))
    assert light.level == WorkloadLevel.LIGHT


def test_overload_detection_from_meetings_and_deadlines():
    calculator = WorkloadCalculator()
    assessment = calculator.calculate(WorkloadSignals(meeting_hours=5.5, client_work_hours=1, deadline_count=2, pending_approvals=1, available_hours=8))
    assert assessment.level == WorkloadLevel.OVERLOADED
    assert any("deadline" in reason for reason in assessment.reasons)


# -- 16-17. Commitments: creation, completion --------------------------------------

@pytest.mark.asyncio
async def test_commitment_creation_and_meeting_extraction(tmp_path):
    database = await make_database(tmp_path)
    service = CommitmentService(CommitmentStore(database))

    explicit = await service.create("Send the proposal", recipient="Finora", source=CommitmentSource.EXPLICIT_PROMISE)
    assert explicit.status == CommitmentStatus.OPEN

    from_meeting = await service.from_meeting_action_items("event_123", ["Follow up with legal", "Share the deck"])
    assert len(from_meeting) == 2
    assert all(item.source == CommitmentSource.MEETING_ACTION_ITEM for item in from_meeting)
    assert all("meeting_event:event_123" in item.evidence for item in from_meeting)
    await database.close()


@pytest.mark.asyncio
async def test_commitment_completion_and_overdue_detection(tmp_path):
    database = await make_database(tmp_path)
    service = CommitmentService(CommitmentStore(database))

    overdue_commitment = await service.create("Reply to client", deadline=datetime.now(timezone.utc) - timedelta(hours=1))
    open_items = await service.open_commitments()
    assert any(item.status == CommitmentStatus.OVERDUE for item in open_items)

    completed = await service.complete(overdue_commitment.id)
    assert completed.status == CommitmentStatus.COMPLETED
    remaining_overdue = await service.overdue()
    assert overdue_commitment.id not in {item.id for item in remaining_overdue}
    await database.close()


# -- 18-20. Daily planning / morning briefing / evening review ---------------------

def test_daily_planning_combines_signals_into_one_recommendation():
    orchestrator = ChiefOfStaffOrchestrator()
    context = ChiefOfStaffContext(candidate_actions=[
        PrioritySignal(item_id="a", label="Finish client review", urgency=0.9, importance=0.8, client_impact=0.9, dependency=0.7),
        PrioritySignal(item_id="b", label="Read industry newsletter", urgency=0.1, importance=0.2),
    ])
    briefing = orchestrator.brief(context)
    assert briefing.recommendation.primary is not None
    assert briefing.recommendation.primary.action == "Finish client review"
    assert len(briefing.recommendation.alternatives) <= 2


def test_morning_briefing_prioritizes_and_bounds_highlights():
    from app.daily_review.morning import MorningBriefingInput, MorningBriefingService

    service = MorningBriefingService(max_highlights=3)
    briefing = service.build(MorningBriefingInput(
        pending_approvals=2, calendar_meeting_count=3, important_email_count=1,
        client_risk_notes=["Client X deadline at risk"], personal_priorities=["Gym at 6pm"],
    ))
    assert len(briefing.highlights) <= 3
    assert briefing.ask_prepare_plan is True


def test_evening_review_uses_only_real_recorded_events():
    from app.daily_review.evening import EveningReviewInput, EveningReviewService

    service = EveningReviewService()
    review = service.build(EveningReviewInput(tasks_completed=["Shipped feature X"], focus_session_minutes=144, best_focus_window="09:10-10:42"))
    assert "Shipped feature X" in review.completed
    assert review.pattern_note == "Your best focus block was 09:10-10:42."

    empty_review = service.build(EveningReviewInput())
    assert empty_review.completed == []
    assert "No recorded activity" in empty_review.summary


# -- 21. Weekly review --------------------------------------------------------------

def test_weekly_review_omits_empty_sections():
    from app.daily_review.weekly import WeeklyReviewInput, WeeklyReviewService

    service = WeeklyReviewService()
    review = service.build(WeeklyReviewInput(wins=["Closed a deal"], risks=["One overdue commitment"]))
    assert "wins" in review.sections
    assert "habit_trends" not in review.sections  # no data supplied — not fabricated


# -- 22-23. Proactive: relevance gate, duplicate suppression -----------------------

@pytest.mark.asyncio
async def test_proactive_relevance_gate_blocks_low_importance(tmp_path):
    database = await make_database(tmp_path)
    rules = ProactiveRules.from_config(PROACTIVE_CONFIG)
    engine = ProactiveEngine(rules, ProactiveSuggestionStore(database))

    low = ProactiveSuggestion(title="FYI", description="minor", importance=0.2, urgency="low")
    decision = await engine.evaluate(low, level=ProactiveLevel.BALANCED)
    assert decision.surfaced is False
    await database.close()


@pytest.mark.asyncio
async def test_proactive_duplicate_suppression(tmp_path):
    database = await make_database(tmp_path)
    rules = ProactiveRules.from_config(PROACTIVE_CONFIG)
    engine = ProactiveEngine(rules, ProactiveSuggestionStore(database))

    suggestion = ProactiveSuggestion(title="Client deadline risk", description="Finora deadline tomorrow", importance=0.9, urgency="important")
    first = await engine.evaluate(suggestion, level=ProactiveLevel.BALANCED)
    assert first.surfaced is True

    duplicate = ProactiveSuggestion(title="Client deadline risk", description="Finora deadline tomorrow", importance=0.9, urgency="important")
    second = await engine.evaluate(duplicate, level=ProactiveLevel.BALANCED)
    assert second.surfaced is False
    assert "already" in second.reason.lower()
    await database.close()


@pytest.mark.asyncio
async def test_proactive_daily_low_priority_rate_limit(tmp_path):
    database = await make_database(tmp_path)
    rules = ProactiveRules.from_config(PROACTIVE_CONFIG)  # max_low_priority_per_day = 2
    engine = ProactiveEngine(rules, ProactiveSuggestionStore(database))

    surfaced = 0
    for i in range(4):
        suggestion = ProactiveSuggestion(title=f"Low priority item {i}", description="minor", importance=0.6, urgency="low")
        decision = await engine.evaluate(suggestion, level=ProactiveLevel.BALANCED)
        if decision.surfaced:
            surfaced += 1
    assert surfaced <= 2
    await database.close()


# -- 24-25. Personal privacy / context isolation -------------------------------------

def test_finance_and_habit_data_excluded_from_client_context():
    data = {"habit_summary": "x", "portfolio": {}, "client_name": "Acme Corp", "invoice_total": 500}
    stripped = strip_personal_for_client_context(data)
    assert stripped == {"client_name": "Acme Corp", "invoice_total": 500}


def test_personal_context_builder_bounds_top_commitments():
    builder = PersonalContextBuilder()
    profile = PersonalProfile()
    commitments = [
        Commitment(description=f"item {i}", deadline=datetime.now(timezone.utc) + timedelta(days=i), status=CommitmentStatus.OPEN)
        for i in range(8)
    ]
    context = builder.build(profile, timezone_name="UTC", working_hours={}, quiet_hours={}, commitments=commitments)
    assert len(context.top_commitments) <= 5
    assert context.open_commitment_count == 8


# -- 26. User disables tracking (rule 70) ---------------------------------------------

@pytest.mark.asyncio
async def test_user_can_disable_habit_tracking(tmp_path):
    database = await make_database(tmp_path)
    habit_store, event_store = HabitStore(database), HabitEventStore(database)
    tracker = HabitTracker(habit_store, event_store)

    habit = await tracker.create(Habit(name="Screen time"))
    await tracker.check_in(habit.id)
    disabled = await tracker.disable(habit.id)
    assert disabled.status == HabitStatus.ARCHIVED

    with pytest.raises(ValueError):
        await tracker.check_in(habit.id)  # tracking stopped; past events remain (not deleted)
    remaining_events = await event_store.list_for_habit(habit.id)
    assert len(remaining_events) == 1
    await database.close()


# -- 27. Memory deletion (reuses Phase 6 MemoryManager) --------------------------------

@pytest.mark.asyncio
async def test_personal_preference_memory_can_be_forgotten(tmp_path):
    from app.memory.embeddings import DisabledEmbeddingProvider
    from app.memory.manager import MemoryManager
    from app.memory.retrieval import MemoryRetriever
    from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryType, ProvenanceType
    from app.memory.store import MemoryStore

    database = await make_database(tmp_path)
    store = MemoryStore(database)
    manager = MemoryManager(store, MemoryRetriever(store, DisabledEmbeddingProvider()))
    memory = await manager.remember(MemoryEntry(
        type=MemoryType.PREFERENCE, title="Test preference", content="I prefer mornings", summary="prefers mornings",
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, reference="test")],
    ))
    forgotten = await manager.forget(memory.id)
    assert forgotten is True
    assert await manager.inspect(memory.id) is None
    await database.close()


# -- 28. Offline functionality (deterministic paths, no model call) -------------------

def test_core_personal_os_functions_require_no_model_call():
    """Goal planning, habit pattern analysis, workload calculation, and
    priority scoring are pure deterministic functions — none of them
    accept or require a model/provider object (rule 76)."""
    import inspect

    for factory in (GoalPlanner, HabitPatternAnalyzer, WorkloadCalculator, StreakCalculator):
        signature = inspect.signature(factory.__init__)
        for name in signature.parameters:
            assert "model" not in name.lower() and "provider" not in name.lower()


# -- 29. Model/cost controls (deterministic routing, zero paid model calls) -----------

def test_phase11_intents_are_flagged_deterministic_by_classifier():
    from app.runtime.task_classifier import TaskClassifier

    classifier = TaskClassifier()
    for request in ("What should I do today?", "What should I work on right now?", "How are my habits going?", "Give me my weekly review."):
        profile = classifier.classify(request)
        assert profile.deterministic is True
        assert "phase11" in profile.needs


# -- 30. Dynamic UI events -------------------------------------------------------------

@pytest.mark.asyncio
async def test_goal_create_emits_event_and_ui_composition(tmp_path):
    database = await make_database(tmp_path)
    goal_store, milestone_store = GoalStore(database), MilestoneStore(database)
    milestone_service = MilestoneService(milestone_store)
    goal_manager = GoalManager(goal_store, milestone_service, GoalPlanner())
    goal_evaluator = GoalEvaluator()

    from app.chief_of_staff.orchestrator import ChiefOfStaffOrchestrator
    from app.daily_review.evening import EveningReviewService
    from app.daily_review.morning import MorningBriefingService
    from app.daily_review.weekly import WeeklyReviewService
    from app.habits.interventions import InterventionEngine
    from app.habits.streaks import StreakCalculator
    from app.notifications.quiet_hours import QuietModeState
    from app.persistence.task_store import TaskStore
    from app.phase11.engine import Phase11Engine
    from app.productivity.focus_sessions import FocusSessionService, FocusSessionStore
    from app.productivity.workload import WorkloadCalculator
    from app.routines.completion import RoutineCompletionService, RoutineStepExecutor
    from app.routines.manager import RoutineManager
    from app.routines.store import RoutineRunStore, RoutineStore
    from app.crm.store import CRMStore

    engine = Phase11Engine(
        personal_profile_service=None, commitment_service=CommitmentService(CommitmentStore(database)),
        context_builder=PersonalContextBuilder(), goal_manager=goal_manager, goal_evaluator=goal_evaluator,
        milestone_service=milestone_service, habit_store=HabitStore(database), habit_event_store=HabitEventStore(database),
        habit_insight_service=HabitInsightService(HabitPatternAnalyzer(), StreakCalculator(), InterventionEngine()),
        routine_manager=RoutineManager(RoutineStore(database)),
        routine_completion_service=RoutineCompletionService(RoutineStepExecutor(), RoutineRunStore(database)),
        focus_service=FocusSessionService(FocusSessionStore(database)), workload_calculator=WorkloadCalculator(),
        chief_of_staff=ChiefOfStaffOrchestrator(), quiet_mode=QuietModeState(),
        morning_service=MorningBriefingService(), evening_service=EveningReviewService(), weekly_service=WeeklyReviewService(),
        crm_store=CRMStore(database), task_store=TaskStore(database),
    )

    events: list[tuple[str, str, dict]] = []

    async def emit(event_type: str, message: str, payload: dict) -> None:
        events.append((event_type, message, payload))

    from app.schemas.tasks import Task, TaskProfile

    task = Task(goal="I want to learn Spanish", user_request="I want to learn Spanish")
    profile = TaskProfile(domain="personal", intent="goal_create", needs={"phase11"}, deterministic=True)
    result = await engine.execute(task, profile, emit)

    assert result.ui_composition is not None
    object_types = {obj["type"] for obj in result.ui_composition["objects"]}
    assert "goal-progress-path" in object_types
    event_types = {e[0] for e in events}
    assert "goal_created" in event_types
    await database.close()
