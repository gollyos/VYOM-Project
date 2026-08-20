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
