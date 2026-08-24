from __future__ import annotations

import json
import secrets
from pathlib import Path


class PairingStore:
    """Durable pairing token for the Chrome extension bridge.

    Generated once and persisted to disk so an already-paired extension
    keeps working across Brain restarts without re-pairing. Served only to
    whoever can already reach this machine's own local API - the same
    trust boundary as every other local VYOM endpoint - and compared with
    a constant-time check so a network observer timing the response cannot
    learn it byte by byte."""

    def __init__(self, path: Path):
        self._path = path

    def get_or_create(self) -> str:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                token = data.get("token")
                if isinstance(token, str) and token:
                    return token
            except (ValueError, OSError):
                pass
        return self._generate()

    def reset(self) -> str:
        return self._generate()

    def verify(self, candidate: str | None) -> bool:
        if not candidate:
            return False
        return secrets.compare_digest(candidate, self.get_or_create())

    def _generate(self) -> str:
        token = secrets.token_urlsafe(32)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"token": token}), encoding="utf-8")
        return token
