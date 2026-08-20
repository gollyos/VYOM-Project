from __future__ import annotations

from ..security.redaction import contains_secret_shape
from .system_checks import CheckResult

SEVERITIES = ("critical", "high", "medium", "low", "informational")


class SecurityAudit:
    """"VYOM, run security audit." Audits the live process posture:
    network listeners, secret locations, unsafe config, debug flags,
    session hygiene, log hygiene — each finding with severity and
    evidence."""

    def __init__(self, *, database, settings_paths: list, log_files: list, security_config: dict,
                 device_registry=None, session_security=None, mcp_registry=None):
        self.database = database
        self.settings_paths = settings_paths
        self.log_files = log_files
        self.security_config = security_config
        self.device_registry = device_registry
        self.session_security = session_security
        self.mcp_registry = mcp_registry

    def _finding(self, severity: str, area: str, evidence: str) -> dict:
        return {"severity": severity, "area": area, "evidence": evidence}

    def run(self) -> dict:
        findings: list[dict] = []

        # 1) Bind posture: the Brain must not listen on non-loopback.
        host = str(self.security_config.get("bind", "127.0.0.1"))
        if host not in ("127.0.0.1", "::1", "localhost"):
            findings.append(self._finding(
                "critical", "network_listener",
                f"Brain binds {host}; remote access requires explicit secure transport",
            ))
        else:
            findings.append(self._finding("informational", "network_listener", f"Brain binds loopback only ({host})"))

        # 2) Secret locations: no secret-shaped values in config files.
        for path in self.settings_paths:
            if path and path.exists():
                text = path.read_text(encoding="utf-8", errors="ignore")
                if contains_secret_shape(text):
                    findings.append(self._finding(
                        "high", "secret_location",
                        f"Secret-shaped value found in config file {path.name}; move it to the SecretStore",
                    ))

        # 3) Secret-shaped values must not exist in normal app tables.
        try:
            import sqlite3

            connection = sqlite3.connect(self.database.path)
            rows = connection.execute(
                "SELECT task_json FROM tasks ORDER BY updated_at DESC LIMIT 50"
            ).fetchall()
            connection.close()
            leaked = sum(1 for row in rows if contains_secret_shape(row[0]))
            if leaked:
                findings.append(self._finding("high", "secret_location", f"{leaked} recent task record(s) contain secret-shaped text"))
        except Exception:
            findings.append(self._finding("medium", "secret_location", "Could not scan task records for secret-shaped values"))

        # 4) Logs must be free of raw secrets.
        for log_file in self.log_files:
            if log_file and log_file.exists():
                tail = log_file.read_text(encoding="utf-8", errors="ignore")[-200_000:]
                if contains_secret_shape(tail):
                    findings.append(self._finding("critical", "sensitive_logs", f"Secret-shaped value present in {log_file.name}"))

        # 5) Debug mode.
        if self.security_config.get("debug_mode", False):
            findings.append(self._finding("medium", "debug_mode", "Debug mode is enabled; disable for production use"))

        # 6) Untrusted/revoked device nodes still trusted?
        if self.device_registry is not None:
            pending = [n for n in self.device_registry.list() if n.trust_level.value in ("unpaired", "pending")]
            if pending:
                findings.append(self._finding("medium", "device_nodes", f"{len(pending)} node(s) not fully paired: {[n.name for n in pending]}"))
            stale_sessions = []
            if self.session_security is not None:
                for session in self.session_security.active_sessions():
                    import datetime as _dt

                    age_h = (_dt.datetime.now(_dt.timezone.utc) - session.created_at).total_seconds() / 3600
                    if age_h > 24:
                        stale_sessions.append(session.session_id)
                if stale_sessions:
                    findings.append(self._finding("low", "sessions", f"{len(stale_sessions)} long-lived remote session(s); consider revoking"))

        # 7) MCP trust.
        if self.mcp_registry is not None:
            servers = list(getattr(self.mcp_registry, "servers", {}) or {})
            untrusted = [name for name in servers if "restricted" in str(getattr(self.mcp_registry, "trust_levels", {}).get(name, "restricted")).lower()]
            if untrusted:
                findings.append(self._finding("low", "mcp", f"{len(untrusted)} MCP server(s) remain restricted-trust (safe default)"))

        findings.sort(key=lambda item: SEVERITIES.index(item["severity"]))
        counts = {severity: sum(1 for f in findings if f["severity"] == severity) for severity in SEVERITIES}
        overall = "critical" if counts["critical"] else "high" if counts["high"] else "medium" if counts["medium"] else "low" if counts["low"] else "informational"
        return {"overall": overall, "counts": counts, "findings": findings}
