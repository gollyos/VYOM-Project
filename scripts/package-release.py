#!/usr/bin/env python3
"""VYOM package-release — reproducible release pipeline.

clean -> tests -> frontend build -> Tauri build + NSIS package ->
release manifest (version, channel, timestamps, checksums, schema).

A failed required step stops the release. The manifest is written to
`release/manifest-<version>-<channel>.json` with sha256 checksums of
every artifact. Update signing is architecture-only until signing keys
exist (documented UNVERIFIED in docs/RELEASE_ENGINEERING.md).

Usage: python scripts/package-release.py [--skip-installer]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRAIN = ROOT / "services" / "brain"
RELEASE_DIR = ROOT / "release"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def step(name: str, command: list[str], cwd: Path) -> None:
    print(f"\n=== {name} ===")
    import shutil

    command = [shutil.which(command[0]) or command[0], *command[1:]]
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(f"RELEASE STOPPED: required step '{name}' failed (exit {result.returncode})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-installer", action="store_true")
    args = parser.parse_args()

    import yaml

    release_config = yaml.safe_load((ROOT / "config" / "release.yaml").read_text(encoding="utf-8"))
    version = str(release_config.get("app_version", "0.2.0"))
    channel = str(release_config.get("channel", "alpha"))

    print(f"VYOM package-release {version} ({channel})")

    BRAIN.mkdir(parents=True, exist_ok=True)
    (BRAIN / ".pytest-tmp").mkdir(parents=True, exist_ok=True)
    step("brain_tests", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                         "--basetemp=.pytest-tmp/release"], BRAIN)
    step("frontend_build", ["npm", "run", "build"], ROOT)
    if not args.skip_installer:
        step("tauri_build", ["npm", "run", "desktop:build"], ROOT)

    artifacts: dict[str, dict] = {}
    exe = ROOT / "src-tauri" / "target" / "release" / "vyom.exe"
    if exe.exists():
        artifacts["vyom.exe"] = {"path": str(exe.relative_to(ROOT)), "sha256": sha256(exe), "bytes": exe.stat().st_size}
    installer = ROOT / "src-tauri" / "target" / "release" / "bundle" / "nsis" / f"VYOM_{version}_x64-setup.exe"
    if installer.exists():
        artifacts["installer"] = {"path": str(installer.relative_to(ROOT)), "sha256": sha256(installer), "bytes": installer.stat().st_size}

    manifest = {
        "version": version,
        "channel": channel,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "brain_version": str(release_config.get("brain_version", version)),
        "schema_version": int(release_config.get("schema_version", 1)),
        "protocol_version": int(release_config.get("protocol_version", 1)),
        "included_migrations": ["baseline_schema_v0"],
        "updater_artifacts": "signed-updater artifacts not produced (no signing keys configured)",
        "artifacts": artifacts,
    }
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RELEASE_DIR / f"manifest-{version}-{channel}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nrelease manifest written: {manifest_path}")
    for name, item in artifacts.items():
        print(f"  {name}: {item['bytes']} bytes sha256={item['sha256'][:16]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
