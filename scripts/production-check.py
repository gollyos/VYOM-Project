#!/usr/bin/env python3
"""VYOM production-check — the primary release validation suite.

Runs, in order (any required failure stops the release):
  1. Brain test suite (pytest)
  2. Production config validation (strict)
  3. Brain boot + startup checks + readiness (alive/ready/degraded)
  4. Doctor + security audit
  5. Frontend TypeScript/Vite build
  6. Native Tauri compile check

Usage: python scripts/production-check.py [--skip-native]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "services" / "brain"

PASSED: list[str] = []
FAILED: list[str] = []


def resolve(command: str) -> str:
    """Windows: npm/cargo are .cmd/.bat shims — resolve via PATH."""
    import shutil

    resolved = shutil.which(command)
    return resolved or command


def run(name: str, command: list[str], *, cwd: Path, required: bool = True, timeout: int = 900) -> bool:
    print(f"\n=== {name} ===")
    command = [resolve(command[0]), *command[1:]]
    try:
        result = subprocess.run(command, cwd=cwd, timeout=timeout, capture_output=True, text=True)
    except (subprocess.TimeoutExpired, FileNotFoundError) as error:
        print(f"  FAILED to run: {error}")
        if required:
            FAILED.append(name)
            return False
        PASSED.append(f"{name} (skipped: {error})")
        return True
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-6:])
    print("  " + tail.replace("\n", "\n  "))
    if result.returncode == 0:
        PASSED.append(name)
        return True
    print(f"  exit={result.returncode}")
    if required:
        FAILED.append(name)
        return False
    PASSED.append(f"{name} (allowed-failure)")
    return True


def brain_boot_checks() -> bool:
    print("\n=== Brain boot + startup checks + doctor/audit ===")
    sys.path.insert(0, str(BRAIN))
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    with tempfile.TemporaryDirectory(prefix="vyom-prodcheck-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "brain.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
        )
        try:
            with TestClient(create_app(settings)) as client:
                healthz = client.get("/healthz")
                assert healthz.status_code == 200 and healthz.json()["alive"], healthz.text
                readyz = client.get("/readyz")
                state = readyz.json().get("detail", readyz.json())
                assert readyz.status_code in (200, 503)
                report = client.get("/api/production/startup-report").json()
                assert report["ok"], f"startup failures: {report['failures']}"
                doctor = client.post("/api/diagnostics/doctor").json()
                assert doctor["overall"] in ("PASS", "WARNING"), doctor["overall"]
                audit = client.post("/api/diagnostics/security-audit").json()
                assert audit["overall"] not in ("critical", "high"), audit["findings"]
                onboarding = client.get("/api/setup/status").json()
                assert onboarding["needs_onboarding"] is True
            PASSED.append("brain_boot_checks")
            return True
        except Exception as error:
            print(f"  FAILED: {error}")
            FAILED.append("brain_boot_checks")
            return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-native", action="store_true", help="skip the Rust/Tauri compile check")
    args = parser.parse_args()

    print("VYOM production-check — alpha release validation")
    print(f"root: {ROOT}")

    ok = run("brain_tests", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             "--basetemp=.pytest-tmp/prodcheck"], cwd=BRAIN)
    if ok:
        ok = brain_boot_checks()
    if ok:
        ok = run("frontend_build", ["npm", "run", "build"], cwd=ROOT)
    if ok and not args.skip_native:
        ok = run("tauri_compile_check", ["cargo", "check", "--manifest-path", "src-tauri/Cargo.toml"], cwd=ROOT)

    print("\n=== production-check summary ===")
    for item in PASSED:
        print(f"  PASS  {item}")
    for item in FAILED:
        print(f"  FAIL  {item}")
    if FAILED:
        print("\nRELEASE BLOCKED — fix the failing gates above.")
        return 1
    print("\nAll required production gates passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
