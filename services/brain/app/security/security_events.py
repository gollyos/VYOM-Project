from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .redaction import redact_mapping

# Security/consequential actions that must leave a durable audit trail.
SECURITY_ACTIONS = {
    "permission_changed", "device_paired", "device_revoked",
    "secret_changed", "secret_rotated", "secret_deleted",
    "external_email_sent", "automation_enabled", "automation_disabled",
    "l3_action_approved", "risk_configuration_changed", "update_installed",
    "session_opened", "session_revoked", "remote_command_rejected",
    "login_failed", "rate_limited",
}


class SecurityEventLog:
    """Durable, append-only audit log for security and consequential
    actions. Entries are redacted before persistence — raw secrets
    never reach this file."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def record(self, action: str, *, actor: str = "system", **details) -> dict:
        if action not in SECURITY_ACTIONS:
            raise ValueError(f"Unknown security action {action!r}")
        entry = {
            "id": f"sec_{uuid4().hex}",
            "action": action,
            "actor": actor,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **redact_mapping(details),
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def recent(self, limit: int = 100) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(entries))
