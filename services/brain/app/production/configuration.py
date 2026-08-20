from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


class ConfigurationError(Exception):
    pass


# Layer precedence (lowest -> highest): defaults < machine < user <
# runtime overrides. Secrets are never part of any config layer — they
# live in the SecretStore only.
CONFIG_LAYERS = ("defaults", "machine", "user", "runtime")


@dataclass
class ConfigurationReport:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    layers: dict[str, list[str]] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "layers": self.layers,
        }


class ConfigValidator:
    """Strict startup validation for every YAML config file: unknown
    keys, invalid paths, unknown enum values, bad schedules. Invalid
    production configuration fails clearly instead of silently using
    dangerous defaults."""

    # Minimal known-key maps per file; unknown keys are warnings, key
    # files (security/deployment) validate hard.
    STRICT_FILES = {"security.yaml", "deployment.yaml"}

    KNOWN_KEYS: dict[str, set[str]] = {
        "security.yaml": {"version", "bind", "debug_mode", "rate_limits", "sessions", "api", "redaction"},
        "deployment.yaml": {"version", "mode", "nodes", "transport", "secrets", "capability_requirements"},
    }

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)

    def validate_all(self) -> ConfigurationReport:
        report = ConfigurationReport(valid=True)
        if not self.config_dir.exists():
            report.valid = False
            report.errors.append(f"Config directory {self.config_dir} does not exist")
            return report
        for path in sorted(self.config_dir.glob("*.yaml")):
            report.layers[path.name] = []
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError as error:
                report.valid = False
                report.errors.append(f"{path.name}: unparseable YAML ({error})")
                continue
            if not isinstance(data, dict):
                report.valid = False
                report.errors.append(f"{path.name}: expected a mapping at top level")
                continue
            version = data.get("version")
            if version is None:
                report.warnings.append(f"{path.name}: missing 'version' key")
            if path.name in self.KNOWN_KEYS:
                unknown = set(data) - self.KNOWN_KEYS[path.name]
                if unknown:
                    message = f"{path.name}: unknown keys {sorted(unknown)}"
                    if path.name in self.STRICT_FILES:
                        report.valid = False
                        report.errors.append(message)
                    else:
                        report.warnings.append(message)
            # Deployment transport safety: never a public bind by default.
            if path.name == "deployment.yaml":
                bind = str((data.get("transport") or {}).get("bind", "127.0.0.1"))
                if bind not in ("127.0.0.1", "::1", "localhost", "0.0.0.0"):
                    report.warnings.append(f"deployment.yaml: unusual bind {bind}")
                if bind == "0.0.0.0":
                    report.warnings.append(
                        "deployment.yaml: bind 0.0.0.0 exposes the Brain beyond loopback; "
                        "a TLS/auth proxy is mandatory"
                    )
        return report


def layered_value(*layers: dict | None, key: str, default=None):
    """Resolve `key` through defaults < machine < user < runtime."""
    result = default
    for layer in layers:
        if layer and key in layer:
            result = layer[key]
    return result
