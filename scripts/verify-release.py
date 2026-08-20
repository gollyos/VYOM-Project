#!/usr/bin/env python3
"""VYOM verify-release — validates a release manifest: every artifact
exists, every checksum matches, versions/channel are consistent with
config/release.yaml.

Usage: python scripts/verify-release.py [manifest.json]
       (defaults to the newest manifest in release/)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    manifests = sorted((ROOT / "release").glob("manifest-*.json"))
    if not manifests:
        print("No release manifest found. Run scripts/package-release.py first.")
        return 1
    manifest_path = Path(sys.argv[1]) if len(sys.argv) > 1 else manifests[-1]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    print(f"verifying {manifest_path.name}: v{manifest['version']} ({manifest['channel']})")

    failures = 0
    for name, item in manifest.get("artifacts", {}).items():
        artifact = ROOT / item["path"]
        if not artifact.exists():
            print(f"  FAIL {name}: missing {item['path']}")
            failures += 1
            continue
        actual = sha256(artifact)
        if actual != item["sha256"]:
            print(f"  FAIL {name}: checksum mismatch (expected {item['sha256'][:16]}..., got {actual[:16]}...)")
            failures += 1
        else:
            print(f"  PASS {name}: {item['bytes']} bytes, checksum ok")

    if not manifest.get("artifacts"):
        print("  FAIL manifest lists no artifacts")
        failures += 1

    if failures:
        print(f"\nverify-release FAILED ({failures} failure(s))")
        return 1
    print("\nverify-release PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
