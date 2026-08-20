from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from .interventions import InterventionEngine, InterventionSuggestion
from .pattern_analyzer import HabitPatternAnalyzer
from .schemas import DesiredDirection, Habit, HabitEvent, PatternInsight
from .streaks import StreakCalculator, StreakResult


class HabitInsightReport(BaseModel):
    habit_id: str
    habit_name: str
    event_count: int
    streaks: StreakResult | None = None
    insight: PatternInsight | None = None
    intervention: InterventionSuggestion | None = None
    sufficient_data: bool
    message: str


class HabitInsightService:
    """Orchestrates pattern analysis + streaks + interventions into one
    honest report. When evidence is insufficient it says so explicitly
    rather than inventing a psychological explanation (rule 59)."""

    def __init__(self, analyzer: HabitPatternAnalyzer | None = None, streak_calculator: StreakCalculator | None = None, intervention_engine: InterventionEngine | None = None):
        self.analyzer = analyzer or HabitPatternAnalyzer()
        self.streak_calculator = streak_calculator or StreakCalculator()
        self.intervention_engine = intervention_engine or InterventionEngine()

    def report(self, habit: Habit, events: list[HabitEvent], *, lookback_days: int = 42) -> HabitInsightReport:
        if len(events) < self.analyzer.minimum_sample_size:
            return HabitInsightReport(
                habit_id=habit.id, habit_name=habit.name, event_count=len(events), sufficient_data=False,
                message=f"Not enough recorded events for '{habit.name}' yet ({len(events)} so far; at least {self.analyzer.minimum_sample_size} needed for a reliable pattern).",
            )
        streaks = self.streak_calculator.compute(events, lookback_days=lookback_days)
        insight = self.analyzer.dominant_time_insight(events, habit.name, time_range=f"last {lookback_days} days")
        intervention = self.intervention_engine.suggest(habit.name, habit.desired_direction, insight)
        message = f"'{habit.name}': {streaks.consistency_trend_pct}% consistency over the last {lookback_days} day(s)."
        if insight:
            message += f" {insight.statement}."
        return HabitInsightReport(habit_id=habit.id, habit_name=habit.name, event_count=len(events), streaks=streaks, insight=insight, intervention=intervention, sufficient_data=True, message=message)

    def bad_habit_analysis(self, habit: Habit, events: list[HabitEvent], context_days: set[date], context_label: str, *, lookback_days: int = 42) -> HabitInsightReport:
        if len(events) < self.analyzer.minimum_sample_size or not context_days:
            return HabitInsightReport(
                habit_id=habit.id, habit_name=habit.name, event_count=len(events), sufficient_data=False,
                message="There isn't enough recorded evidence to explain this pattern yet — VYOM will not guess at a psychological cause.",
            )
        insight = self.analyzer.correlate_with_context_days(events, context_days, habit_name=habit.name, context_label=context_label, time_range=f"last {lookback_days} days")
        if insight is None:
            return HabitInsightReport(
                habit_id=habit.id, habit_name=habit.name, event_count=len(events), sufficient_data=False,
                message=f"No statistically meaningful correlation was found between '{habit.name}' and '{context_label}' in the recorded data.",
            )
        intervention = self.intervention_engine.suggest(habit.name, habit.desired_direction, insight)
        message = f"{insight.statement}."
        return HabitInsightReport(habit_id=habit.id, habit_name=habit.name, event_count=len(events), insight=insight, intervention=intervention, sufficient_data=True, message=message)
