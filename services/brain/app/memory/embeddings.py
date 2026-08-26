from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    name = "abstract"
    available = False

    @abstractmethod
    async def embed(self, text: str) -> list[float] | None:
        raise NotImplementedError


class DisabledEmbeddingProvider(EmbeddingProvider):
    name = "disabled"

    async def embed(self, text: str) -> None:
        return None


class LocalHashEmbeddingProvider(EmbeddingProvider):
    name = "local-hash-v1"
    available = True

    SYNONYMS = {
        "builds": "build", "built": "build", "compile": "build", "compiles": "build",
        "meeting": "meet", "meetings": "meet", "appointment": "meet",
        "repository": "project", "repo": "project", "codebase": "project",
        "preference": "prefer", "preferred": "prefer", "likes": "prefer",
        "failed": "failure", "fails": "failure", "error": "failure",
    }

    def __init__(self, dimensions: int = 96):
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = re.findall(r"[a-z0-9_]+", text.lower())
        for token in tokens:
            normalized = self.SYNONYMS.get(token, token)
            digest = hashlib.blake2b(normalized.encode(), digest_size=8).digest()
            bucket = int.from_bytes(digest[:4], "little") % self.dimensions
            sign = 1.0 if digest[4] & 1 else -1.0
            vector[bucket] += sign
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return max(0.0, sum(a * b for a, b in zip(left, right)))


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Real semantic embeddings from Google's free embedding endpoint.

    The local hash provider is keyword equivalence wearing a vector
    costume - it can never match "ghar ka budget" to "household
    expenses". Real embeddings can. Uses the same GEMINI_API_KEY as the
    Brain; on any failure (no key, network, quota) it falls back to the
    local provider, so availability never regresses."""

    name = "gemini-embedding-001"
    available = True

    def __init__(self, api_key: str | None, model: str = "gemini-embedding-001",
                 fallback: EmbeddingProvider | None = None):
        self._api_key = api_key
        self._model = model
        self._fallback = fallback

    async def embed(self, text: str) -> list[float] | None:
        if not self._api_key or not text.strip():
            return await self._fallback.embed(text) if self._fallback else None
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:embedContent",
                    headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                    json={"content": {"parts": [{"text": text[:8000]}]}},
                )
            if response.status_code != 200:
                raise OSError(f"embedding HTTP {response.status_code}")
            values = response.json()["embedding"]["values"]
            return [float(value) for value in values]
        except Exception:
            return await self._fallback.embed(text) if self._fallback else None


class CachedEmbeddingProvider(EmbeddingProvider):
    """Wraps a provider with a per-memory vector cache in SQLite.

    Retrieval re-embedded every candidate on every search - fine for a
    hundred rows, ruinous for a decade of them. Vectors are cached keyed
    by memory id AND content hash, so an edited memory is re-embedded but
    an untouched ten-year-old one is read from the cache."""

    def __init__(self, database, inner: EmbeddingProvider):
        self._database = database
        self._inner = inner
        self.name = f"cached({inner.name})"

    @property
    def available(self) -> bool:
        return self._inner.available

    async def embed(self, text: str) -> list[float] | None:
        return await self._inner.embed(text)

    async def embed_memory(self, memory, text: str) -> list[float] | None:
        import json as _json
        from datetime import datetime, timezone

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        connection = self._database.require_connection()
        cursor = await connection.execute(
            "SELECT content_hash, vector_json FROM memory_embeddings "
            "WHERE memory_id = ? AND provider = ?",
            (memory.id, self._inner.name),
        )
        row = await cursor.fetchone()
        if row is not None and row["content_hash"] == content_hash:
            return _json.loads(row["vector_json"])
        vector = await self._inner.embed(text)
        if vector:
            try:
                await connection.execute(
                    "INSERT INTO memory_embeddings(memory_id, provider, content_hash, vector_json, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(memory_id, provider) DO UPDATE SET "
                    "content_hash=excluded.content_hash, vector_json=excluded.vector_json, "
                    "updated_at=excluded.updated_at",
                    (memory.id, self._inner.name, content_hash,
                     _json.dumps(vector), datetime.now(timezone.utc).isoformat()),
                )
                await connection.commit()
            except Exception:
                pass  # a cache write failure must not fail the search
        return vector
