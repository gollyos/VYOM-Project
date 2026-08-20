#!/usr/bin/env python3
"""VYOM security-check — runs the security regression suites and a live
security audit against a real (temporary) Brain instance.

Usage: python scripts/security-check.py
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "services" / "brain"

SECURITY_SUITES = [
    "tests/test_phase13_security.py",
]


def main() -> int:
    print("VYOM security-check")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "--basetemp=.pytest-tmp/seccheck", *SECURITY_SUITES],
        cwd=BRAIN,
    )
    if result.returncode != 0:
        print("\nsecurity regression tests FAILED")
        return 1

    sys.path.insert(0, str(BRAIN))
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    print("\nlive security audit (temporary instance)...")
    with tempfile.TemporaryDirectory(prefix="vyom-seccheck-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
        )
        with TestClient(create_app(settings)) as client:
            audit = client.post("/api/diagnostics/security-audit").json()
            print(f"  overall: {audit['overall']}")
            for finding in audit["findings"]:
                print(f"  [{finding['severity']:13s}] {finding['area']}: {finding['evidence']}")
            if audit["overall"] in ("critical", "high"):
                print("\nsecurity-check FAILED — critical/high findings present")
                return 1
    print("\nsecurity-check PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
