from __future__ import annotations

from pydantic import BaseModel, Field


class MorningBriefingInput(BaseModel):
    """Every field is real, already-fetched data (rule 37) — nothing is
    invented here, and a missing/disconnected source is simply omitted
    rather than estimated."""

    calendar_meeting_count: int | None = None
    important_email_count: int | None = None
    pending_approvals: int = 0
    client_risk_notes: list[str] = Field(default_factory=list)
    active_agent_summaries: list[str] = Field(default_factory=list)
    automation_notes: list[str] = Field(default_factory=list)
    personal_priorities: list[str] = Field(default_factory=list)
    habit_reminder: str | None = None
    goal_reminder: str | None = None
    market_alert_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    #: Work that was interrupted - failed/paused tasks from before the
    #: last restart. The user's requirement: "kabhi kuch kaam reh jaye to
    #: PC dobara khulne pe yaad rahe". These lead the briefing because
    #: they are yesterday's unfinished promises, not new information.
    pending_task_notes: list[str] = Field(default_factory=list)


class MorningBriefing(BaseModel):
    summary: str
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    ask_prepare_plan: bool = True
    #: Failed/paused tasks worth retrying today (id + what it was), so the
    #: UI can offer one-tap retry instead of making the user remember.
    retry_candidates: list[dict] = Field(default_factory=list)
    audio_path: str | None = None


class MorningBriefingService:
    """Morning Briefing 2.0 (rule 37/38): prioritizes rather than reading
    every available source. Bounded to a small set of highlights — never
    30 metrics — then asks whether to prepare today's plan."""

    def __init__(self, *, max_highlights: int = 6):
        self.max_highlights = max_highlights

    def build(self, data: MorningBriefingInput) -> MorningBriefing:
        highlights: list[str] = []
        # Unfinished work leads: it is the thing the user asked for
        # yesterday and never got. The note arrives as "task_id|what" -
        # the id is machine structure for retry_candidates, the HUMAN
        # highlight shows only the what.
        for note in data.pending_task_notes[:3]:
            what = note.split("|", 1)[1] if "|" in note else note
            highlights.append(f"Unfinished: {what}")
        if data.pending_approvals:
            highlights.append(f"{data.pending_approvals} task(s) need your approval")
        if data.calendar_meeting_count:
            highlights.append(f"{data.calendar_meeting_count} meeting(s) today")
        if data.important_email_count:
            highlights.append(f"{data.important_email_count} important email(s)")
        highlights.extend(data.client_risk_notes[:2])
        highlights.extend(data.active_agent_summaries[:2])
        highlights.extend(data.automation_notes[:1])
        if data.goal_reminder:
            highlights.append(data.goal_reminder)
        if data.habit_reminder:
            highlights.append(data.habit_reminder)
        highlights.extend(data.market_alert_notes[:1])
        highlights.extend(data.personal_priorities[:2])
        highlights = highlights[: self.max_highlights]

        summary = "Good morning Boss. " + (" ".join(f"{item}." for item in highlights) if highlights else "Nothing urgent is recorded right now.")
        return MorningBriefing(
            summary=summary, highlights=highlights, risks=data.risks,
            ask_prepare_plan=True,
            # Parsed from the notes so the caller can offer retry without
            # re-querying the task store: [{"task_id": ..., "what": ...}].
            retry_candidates=[
                {"task_id": note.split("|", 1)[0], "what": note.split("|", 1)[1]}
                for note in data.pending_task_notes[:5] if "|" in note
            ],
        )

    async def build_with_audio(self, data: MorningBriefingInput, *, output_path: str | None = None) -> MorningBriefing:
        """Builds briefing and synthesizes high-quality in-process voice narration."""
        briefing = self.build(data)
        from app.tools_builtin.edge_tts_tool import EdgeTTSTool
        tts = EdgeTTSTool()
        res = await tts.execute({"action": "synthesize", "text": briefing.summary, "output_path": output_path})
        if res.success and res.structured_output:
            briefing.audio_path = res.structured_output.get("path")
        return briefing
