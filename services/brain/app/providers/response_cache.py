"""Disk cache for identical provider requests.

The Brain re-asks the same things: the same summarisation prompt after a
replayed task, the same introspection questions, the same short
conversational follow-ups after a reconnect. Each was a fresh, quota-
consuming generateContent call. Identical (provider, model, prompt,
tools-shape, parameters) requests now hit a bounded on-disk cache first.

Only successful text/structured responses are cached - never
tool-calling missions (live actions must observe live reality, and the
planner's history makes those keys unique anyway). The default TTL is
deliberately SHORT (minutes, not hours): the waste this removes is the
burst-repeat pattern (retries, reconnects, duplicate missions re-asking
the same thing within a short window). A long TTL would happily serve a
day-stale answer to "what is my status today".
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from .base import ProviderResponse, ProviderRequest

DEFAULT_TTL_SECONDS = 5 * 60
DEFAULT_MAX_ENTRIES = 300


def _now() -> float:
    return time.time()


class ResponseCache:
    def __init__(
        self,
        directory: Path | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
    ):
        self.directory = directory
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries

    @property
    def enabled(self) -> bool:
        return self.directory is not None and os.getenv("VYOM_RESPONSE_CACHE", "1") != "0"

    def _key(self, request: ProviderRequest) -> str:
        material = json.dumps(
            {
                "provider_context": request.system_instruction,
                "model": request.model,
                "user_request": request.user_request,
                "temperature": getattr(request, "temperature", None),
                "flags": getattr(request, "cache_flags", None),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / f"{key}.json"

    def get(self, request: ProviderRequest) -> ProviderResponse | None:
        if not self.enabled:
            return None
        path = self._path(self._key(request))
        if path is None or not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if _now() - float(entry.get("stored_at", 0)) > self.ttl_seconds:
            try:
                path.unlink()
            except OSError:
                pass
            return None
        try:
            return ProviderResponse.model_validate(entry["response"])
        except (KeyError, ValueError):
            return None

    def put(self, request: ProviderRequest, response: ProviderResponse) -> None:
        path = self._path(self._key(request))
        if path is None:
            return
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"stored_at": _now(), "response": response.model_dump(mode="json")}),
                encoding="utf-8",
            )
            self._prune()
        except OSError:
            # A cache must never fail the call it was trying to save.
            pass

    def _prune(self) -> None:
        assert self.directory is not None
        try:
            entries = [p for p in self.directory.glob("*.json") if p.is_file()]
            if len(entries) <= self.max_entries:
                return
            entries.sort(key=lambda p: p.stat().st_mtime)
            for stale in entries[: len(entries) - self.max_entries]:
                stale.unlink(missing_ok=True)
        except OSError:
            pass
