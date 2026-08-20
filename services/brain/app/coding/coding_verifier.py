from __future__ import annotations

from typing import Any


class CodingVerifier:
    def verify_build(self, result: dict[str, Any]) -> dict[str, Any]:
        exit_code = result.get("exit_code")
        return {
            "passed": exit_code == 0,
            "summary": "Build passed" if exit_code == 0 else f"Build failed with exit code {exit_code}",
            "evidence": [f"Exit code: {exit_code}", "Real command output captured"],
        }

    def verify_file(self, metadata: dict[str, Any]) -> dict[str, Any]:
        passed = bool(metadata.get("exists")) and metadata.get("kind") == "file"
        return {
            "passed": passed,
            "summary": "Created file exists" if passed else "Created file verification failed",
            "evidence": [f"Path: {metadata.get('path')}", f"Size: {metadata.get('size', 0)} bytes"],
        }
