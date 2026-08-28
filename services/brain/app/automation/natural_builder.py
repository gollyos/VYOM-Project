from __future__ import annotations

import re
from typing import Any
from app.automation.workflow_engine import StepType, WorkflowStep


class NaturalAutomationBuilder:
    """Converts natural language user instructions into structured multi-step automations."""

    @staticmethod
    def parse_instruction(prompt: str) -> dict[str, Any]:
        p = prompt.strip().lower()
        
        # Detect trigger
        trigger_type = "manual"
        cron_expr = None
        interval_mins = None

        if "every day" in p or "daily" in p or "har din" in p:
            trigger_type = "recurring"
            cron_expr = "0 9 * * *"  # default 9am daily
        elif "every weekday" in p or "monday to friday" in p or "somwar se shukrawar" in p:
            trigger_type = "recurring"
            cron_expr = "0 9 * * 1-5"
        elif "every hour" in p or "har ghante" in p:
            trigger_type = "recurring"
            interval_mins = 60
        elif "webhook" in p or "when" in p or "jab" in p or "issue opened" in p:
            trigger_type = "webhook"

        # Extract steps
        steps: list[WorkflowStep] = []

        # GitHub detection
        if "github" in p or "issue" in p or "pr" in p:
            steps.append(
                WorkflowStep(
                    name="Fetch GitHub Issues",
                    type=StepType.TOOL_CALL,
                    tool="github.search_issues",
                    input_template={"query": "is:open is:issue", "limit": 5},
                )
            )

        # AI summary step
        if "summarize" in p or "analyze" in p or "classify" in p or "identify" in p or "samjhao" in p:
            steps.append(
                WorkflowStep(
                    name="AI Summary & Triage",
                    type=StepType.AI_STEP,
                    prompt="Summarize the high priority issues and highlight critical bugs.",
                    input_template={"items": "{{steps.step_1.output}}"},
                )
            )

        # Communication step (Slack / Gmail / Telegram)
        if "slack" in p:
            steps.append(
                WorkflowStep(
                    name="Draft Slack Update",
                    type=StepType.TOOL_CALL,
                    tool="slack.create_draft",
                    input_template={"channel": "#engineering", "message": "{{steps.step_2.output.summary}}"},
                )
            )
        elif "email" in p or "gmail" in p:
            steps.append(
                WorkflowStep(
                    name="Prepare Email Draft",
                    type=StepType.TOOL_CALL,
                    tool="gmail.create_draft",
                    input_template={
                        "to": "team@vyom.ai",
                        "subject": "Daily GitHub Triage Digest",
                        "body": "{{steps.step_2.output.summary}}",
                    },
                )
            )
        elif "calendar" in p or "meeting" in p or "schedule" in p:
            steps.append(
                WorkflowStep(
                    name="Schedule Review",
                    type=StepType.TOOL_CALL,
                    tool="google_calendar.create_event",
                    input_template={
                        "summary": "Triage Follow-up",
                        "start_time": "2026-08-29T10:00:00Z",
                        "end_time": "2026-08-29T10:30:00Z",
                    },
                )
            )

        if not steps:
            # General fallback workflow
            steps = [
                WorkflowStep(
                    name="Execute Command",
                    type=StepType.TOOL_CALL,
                    tool="system.run_command",
                    input_template={"command": prompt},
                )
            ]

        name = prompt[:40] + ("..." if len(prompt) > 40 else "")
        return {
            "name": name.title(),
            "description": prompt,
            "trigger_type": trigger_type,
            "cron_expression": cron_expr,
            "interval_minutes": interval_mins,
            "steps": [s.model_dump(mode="json") for s in steps],
        }
