from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

REDACTED_KEYS = {"password", "secret", "token", "api_key", "otp", "mfa_code", "credit_card", "cvv"}
EXECUTABLE_SUFFIXES = {".exe", ".msi", ".bat", ".cmd", ".ps1", ".sh", ".scr", ".vbs", ".js", ".jar", ".dll"}


def _redact(inputs: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***" if key.lower() in REDACTED_KEYS else value) for key, value in inputs.items()}


@dataclass
class DownloadRecord:
    """A file downloaded from a website is untrusted. VYOM records
    metadata only; it never automatically executes a downloaded file."""

    source: str
    filename: str
    content_type: str
    size_bytes: int
    downloaded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def is_potentially_executable(self) -> bool:
        lowered = self.filename.lower()
        return any(lowered.endswith(suffix) for suffix in EXECUTABLE_SUFFIXES)


@dataclass
class SessionMemory:
    """Within-task browser memory. Credentials are never stored here;
    redacted keys are replaced before anything is recorded."""

    max_completed_actions: int = 50
    max_navigation_history: int = 25
    current_url: str | None = None
    page_purpose: str | None = None
    important_elements: list[str] = field(default_factory=list)
    completed_actions: list[dict[str, Any]] = field(default_factory=list)
    form_state: dict[str, Any] = field(default_factory=dict)
    navigation_history: list[str] = field(default_factory=list)
    login_state: str = "unknown"
    errors: list[str] = field(default_factory=list)
    downloads: list[DownloadRecord] = field(default_factory=list)

    def record_download(self, record: DownloadRecord) -> DownloadRecord:
        """Records download metadata only. Callers must never pass a
        downloaded file to a terminal/execution tool based solely on this
        record; execution requires its own explicit, approved workflow."""
        self.downloads.append(record)
        if record.is_potentially_executable:
            self.record_error(f"Untrusted executable-type download recorded, not executed: {record.filename}")
        return record

    def record_navigation(self, url: str) -> None:
        self.current_url = url
        self.navigation_history.append(url)
        self.navigation_history = self.navigation_history[-self.max_navigation_history:]

    def record_action(self, action: str, inputs: dict[str, Any], success: bool) -> None:
        self.completed_actions.append({"action": action, "inputs": _redact(inputs), "success": success})
        self.completed_actions = self.completed_actions[-self.max_completed_actions:]

    def record_form_field(self, field_name: str, value: Any) -> None:
        if field_name.lower() in REDACTED_KEYS:
            return
        self.form_state[field_name] = value

    def record_error(self, message: str) -> None:
        self.errors.append(message)

    def snapshot(self) -> dict[str, Any]:
        return {
            "current_url": self.current_url,
            "page_purpose": self.page_purpose,
            "important_elements": list(self.important_elements),
            "completed_actions": list(self.completed_actions),
            "form_state": dict(self.form_state),
            "navigation_history": list(self.navigation_history),
            "login_state": self.login_state,
            "errors": list(self.errors),
            "downloads": [record.__dict__ for record in self.downloads],
        }
