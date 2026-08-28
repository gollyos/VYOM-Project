from __future__ import annotations

from typing import Any
from app.connectors.base import (
    BaseConnector,
    ConnectorAuthType,
    ConnectorCategory,
    ConnectorDefinition,
    ConnectorStatus,
    RiskLevel,
    ToolDefinition,
)


class CalendarConnector(BaseConnector):
    """Google Calendar connector for events, scheduling, and availability."""

    def __init__(self):
        defn = ConnectorDefinition(
            id="google_calendar",
            name="Google Calendar",
            slug="google-calendar",
            description="Manage your calendar, schedule appointments, search events, and inspect real-time availability.",
            icon="calendar",
            category=ConnectorCategory.PRODUCTIVITY,
            auth_type=ConnectorAuthType.OAUTH2,
            capabilities=["events", "availability", "scheduling"],
            permissions=["calendar.readonly", "calendar.events"],
            tools=[
                ToolDefinition(
                    id="google_calendar.search_events",
                    connector_id="google_calendar",
                    name="search_events",
                    display_name="Search Calendar Events",
                    description="Search for calendar events matching a query or date window.",
                    category="productivity",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search keyword or attendee"},
                            "time_min": {"type": "string", "description": "ISO start date/time"},
                            "time_max": {"type": "string", "description": "ISO end date/time"},
                        },
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="google_calendar.get_availability",
                    connector_id="google_calendar",
                    name="get_availability",
                    display_name="Check Availability",
                    description="Check free/busy time slots for a given day or date range.",
                    category="productivity",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                        },
                        "required": ["date"],
                    },
                    risk_level=RiskLevel.LOW,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="google_calendar.create_event",
                    connector_id="google_calendar",
                    name="create_event",
                    display_name="Create Calendar Event",
                    description="Create a new event or meeting on your primary calendar.",
                    category="productivity",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "summary": {"type": "string", "description": "Event title"},
                            "start_time": {"type": "string", "description": "ISO start timestamp"},
                            "end_time": {"type": "string", "description": "ISO end timestamp"},
                            "attendees": {"type": "array", "items": {"type": "string"}, "description": "List of attendee emails"},
                            "description": {"type": "string", "description": "Optional notes or agenda"},
                        },
                        "required": ["summary", "start_time", "end_time"],
                    },
                    risk_level=RiskLevel.MEDIUM,
                    requires_approval=False,
                ),
                ToolDefinition(
                    id="google_calendar.delete_event",
                    connector_id="google_calendar",
                    name="delete_event",
                    display_name="Delete Calendar Event",
                    description="Delete an event from your calendar. (High Risk - Requires Approval)",
                    category="productivity",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "event_id": {"type": "string", "description": "Event ID to delete"},
                        },
                        "required": ["event_id"],
                    },
                    risk_level=RiskLevel.HIGH,
                    requires_approval=True,
                ),
            ],
        )
        super().__init__(defn)
        self._events: list[dict[str, Any]] = [
            {
                "id": "evt_101",
                "summary": "AI Architecture & Connector Sync",
                "start": "2026-08-28T18:00:00+05:30",
                "end": "2026-08-28T19:00:00+05:30",
                "attendees": ["gunjan@vyom.ai", "team@vyom.ai"],
                "status": "confirmed",
            }
        ]

    async def connect(self, credentials: dict[str, Any]) -> dict[str, Any]:
        self.status = ConnectorStatus.CONNECTED
        return {"status": "connected"}

    async def disconnect(self) -> None:
        self.status = ConnectorStatus.DISCONNECTED

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        self.validate_input(tool_name, arguments)
        if tool_name == "search_events":
            query = (arguments.get("query") or "").lower()
            if query:
                return [e for e in self._events if query in e["summary"].lower()]
            return self._events
        elif tool_name == "get_availability":
            return {
                "date": arguments["date"],
                "free_slots": ["09:00 - 11:00", "14:00 - 16:30", "19:00 - 21:00"],
                "busy_events": self._events,
            }
        elif tool_name == "create_event":
            new_evt = {
                "id": f"evt_{len(self._events) + 102}",
                "summary": arguments["summary"],
                "start": arguments["start_time"],
                "end": arguments["end_time"],
                "attendees": arguments.get("attendees", []),
                "description": arguments.get("description", ""),
                "status": "confirmed",
            }
            self._events.append(new_evt)
            return new_evt
        elif tool_name == "delete_event":
            self._events = [e for e in self._events if e["id"] != arguments["event_id"]]
            return {"deleted": True, "event_id": arguments["event_id"]}
        raise NotImplementedError(f"Tool {tool_name} not implemented")
