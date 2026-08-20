from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.artifacts.schemas import ArtifactRecord, ArtifactStatus

from .manifest import DeliveryManifest

SECRET_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in (
    r"api[_-]?key\s*[:=]", r"secret\s*[:=]", r"password\s*[:=]", r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)]
PLACEHOLDER_PATTERNS = [re.compile(pattern, re.IGNORECASE) for pattern in (
    r"lorem ipsum", r"\btodo\b", r"\btbd\b", r"\[insert", r"placeholder text",
)]
TEMP_FILE_SUFFIXES = (".tmp", ".draft", ".bak", "~")
SCANNABLE_SUFFIXES = {".md", ".txt", ".csv", ".json", ".mmd"}


@dataclass
class QualityGateReport:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)


class QualityGate:
    """Before client delivery: correct client, correct project, all
    required files, latest approved versions, no temp/debug files, no
    secrets, no obvious placeholders, verification passed."""

    def check(
        self,
        *,
        client: str,
        project: str,
        expected_client: str,
        expected_project: str,
        required_deliverables: list[str],
        artifacts: list[ArtifactRecord],
        manifest: DeliveryManifest,
    ) -> QualityGateReport:
        checks: dict[str, bool] = {}
        issues: list[str] = []

        checks["correct_client"] = client == expected_client
        if not checks["correct_client"]:
            issues.append(f"Client mismatch: {client} != {expected_client}")

        checks["correct_project"] = project == expected_project
        if not checks["correct_project"]:
            issues.append(f"Project mismatch: {project} != {expected_project}")

        manifest_deliverables = {entry.deliverable for entry in manifest.entries}
        missing = set(required_deliverables) - manifest_deliverables
        checks["all_required_files_present"] = not missing
        if missing:
            issues.append(f"Missing required deliverable(s): {sorted(missing)}")

        checks["latest_approved_versions"] = all(
            artifact.version == "final" or artifact.status == ArtifactStatus.VALIDATED for artifact in artifacts
        )
        if not checks["latest_approved_versions"]:
            issues.append("One or more artifacts are not the latest validated/final version")

        temp_files = [entry.file for entry in manifest.entries if entry.file.endswith(TEMP_FILE_SUFFIXES)]
        checks["no_temporary_files"] = not temp_files
        if temp_files:
            issues.append(f"Temporary/debug file(s) present: {temp_files}")

        secret_hits = self._scan(manifest, SECRET_PATTERNS)
        checks["no_secrets"] = not secret_hits
        if secret_hits:
            issues.append(f"Possible secret content detected in: {secret_hits}")

        placeholder_hits = self._scan(manifest, PLACEHOLDER_PATTERNS)
        checks["no_placeholders"] = not placeholder_hits
        if placeholder_hits:
            issues.append(f"Placeholder content detected in: {placeholder_hits}")

        checks["verification_passed"] = manifest.all_verified
        if not checks["verification_passed"]:
            issues.append("Not every manifest entry is verified")

        return QualityGateReport(passed=all(checks.values()), checks=checks, issues=issues)

    @staticmethod
    def _scan(manifest: DeliveryManifest, patterns: list[re.Pattern]) -> list[str]:
        hits: list[str] = []
        for entry in manifest.entries:
            path = Path(entry.file) if entry.file else None
            if not path or not path.exists() or path.suffix.lower() not in SCANNABLE_SUFFIXES:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(pattern.search(text) for pattern in patterns):
                hits.append(entry.file)
        return hits
