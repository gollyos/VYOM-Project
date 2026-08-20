from __future__ import annotations

# Recommendations map to actually detected issues — never generic advice.
REPAIR_RULES: dict[str, dict] = {
    "database": {
        "FAIL": {"action": "restore_backup", "explanation": "The Brain database failed its integrity check. Restore the newest valid backup (see docs/BACKUP_RECOVERY.md)."},
    },
    "database_migrations": {
        "FAIL": {"action": "repair_migrations", "explanation": "Migration state is unreadable; run the migration repair path or restore a backup."},
        "WARNING": {"action": "apply_migrations", "explanation": "Pending migrations exist; apply them on the next startup."},
    },
    "disk_space": {
        "FAIL": {"action": "free_disk_space", "explanation": "Free disk space on the data volume; VYOM pauses safely when storage is critical."},
        "WARNING": {"action": "free_disk_space", "explanation": "Disk space is getting low; consider pruning old backups/logs."},
    },
    "data_directories": {
        "FAIL": {"action": "create_directories", "explanation": "Recreate the missing data directories or re-run the installer."},
    },
    "temp_artifacts": {
        "WARNING": {"action": "clean_temp", "explanation": "Safe cleanup of stale temporary files is available."},
    },
    "mcp_servers": {
        "WARNING": {"action": "review_mcp_trust", "explanation": "Review configured MCP servers; trust stays restricted until explicitly granted."},
    },
}

PROVIDER_FIX = {
    "FAIL": {"action": "reconnect_provider", "explanation": "Reconnect this provider in setup — the stored credential failed authentication."},
    "WARNING": {"action": "check_network_or_credentials", "explanation": "The provider health check could not complete; check network/credentials in setup."},
}


class RepairAdvisor:
    """Maps failing doctor checks to concrete, issue-specific
    recommendations. Never invents actions for passing checks."""

    def recommend(self, checks: list[dict]) -> list[dict]:
        recommendations: list[dict] = []
        for check in checks:
            name, status = check.get("name", ""), check.get("status", "")
            rule = REPAIR_RULES.get(name, {}).get(status)
            if rule is None and name.startswith("provider:"):
                rule = PROVIDER_FIX.get(status)
            if rule is not None:
                recommendations.append({
                    "check": name,
                    "status": status,
                    "action": rule["action"],
                    "explanation": rule["explanation"],
                    "check_explanation": check.get("explanation", ""),
                })
        return recommendations
