from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[4]
BRAIN_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BRAIN_ROOT / ".env", override=False)


@dataclass(frozen=True, slots=True)
class Settings:
    host: str = os.getenv("VYOM_BRAIN_HOST", "127.0.0.1")
    port: int = int(os.getenv("VYOM_BRAIN_PORT", "7788"))
    database_path: Path = Path(
        os.getenv("VYOM_BRAIN_DATABASE", str(BRAIN_ROOT / "data" / "vyom-brain.db"))
    ).resolve()
    model_registry_path: Path = Path(
        os.getenv("VYOM_MODEL_REGISTRY", str(PROJECT_ROOT / "config" / "models.yaml"))
    ).resolve()
    tool_registry_path: Path = Path(
        os.getenv("VYOM_TOOL_REGISTRY", str(PROJECT_ROOT / "config" / "tools.yaml"))
    ).resolve()
    memory_config_path: Path = Path(
        os.getenv("VYOM_MEMORY_CONFIG", str(PROJECT_ROOT / "config" / "memory.yaml"))
    ).resolve()
    agent_config_path: Path = Path(
        os.getenv("VYOM_AGENT_CONFIG", str(PROJECT_ROOT / "config" / "agents.yaml"))
    ).resolve()
    integration_config_path: Path = Path(
        os.getenv("VYOM_INTEGRATION_CONFIG", str(PROJECT_ROOT / "config" / "integrations.yaml"))
    ).resolve()
    automation_config_path: Path = Path(
        os.getenv("VYOM_AUTOMATION_CONFIG", str(PROJECT_ROOT / "config" / "automations.yaml"))
    ).resolve()
    research_config_path: Path = Path(
        os.getenv("VYOM_RESEARCH_CONFIG", str(PROJECT_ROOT / "config" / "research.yaml"))
    ).resolve()
    artifacts_root: Path = Path(
        os.getenv("VYOM_ARTIFACTS_ROOT", str(PROJECT_ROOT / "data" / "artifacts"))
    ).resolve()
    secret_store_path: Path = Path(
        os.getenv("VYOM_SECRET_STORE", str(BRAIN_ROOT / "data" / "secrets"))
    ).resolve()
    skills_root: Path = Path(
        os.getenv("VYOM_SKILLS_ROOT", str(PROJECT_ROOT / "data" / "skills"))
    ).resolve()
    agents_root: Path = Path(
        os.getenv("VYOM_AGENTS_ROOT", str(PROJECT_ROOT / "data" / "agents"))
    ).resolve()
    audit_log_path: Path = Path(
        os.getenv("VYOM_TOOL_AUDIT_LOG", str(BRAIN_ROOT / "data" / "tool-audit.jsonl"))
    ).resolve()
    backup_root: Path = Path(
        os.getenv("VYOM_BACKUP_ROOT", str(PROJECT_ROOT / "data" / "backups"))
    ).resolve()
    planning_complexity_threshold: int = int(
        os.getenv("VYOM_PLANNING_COMPLEXITY_THRESHOLD", "3")
    )
    max_fallbacks: int = int(os.getenv("VYOM_MAX_FALLBACKS", "2"))
    provider_timeout_seconds: float = float(os.getenv("VYOM_PROVIDER_TIMEOUT_SECONDS", "35"))

    @property
    def allowed_roots(self) -> list[Path]:
        configured = os.getenv("VYOM_ALLOWED_ROOTS")
        if not configured:
            return [PROJECT_ROOT.resolve()]
        return [Path(value).resolve() for value in configured.split(os.pathsep) if value.strip()]


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")


def expand_environment(value: object) -> object:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2) or ""
            # A variable that is present but EMPTY (`GOOGLE_BRAIN_MODEL_ID=`
            # in .env) must fall back to the declared default, exactly like
            # an unset one. Without this, `os.getenv(name, default)` returns
            # "" and the model is silently dropped by
            # ModelRegistry.enabled(), leaving only fallback providers
            # routable - which is how the real app ended up with no usable
            # cloud model at all.
            return os.getenv(name) or default

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, list):
        return [expand_environment(item) for item in value]
    if isinstance(value, dict):
        return {key: expand_environment(item) for key, item in value.items()}
    return value


def get_settings() -> Settings:
    return Settings()
