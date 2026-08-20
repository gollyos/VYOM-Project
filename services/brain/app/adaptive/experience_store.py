from __future__ import annotations

import re
from collections import Counter

from app.devices.schemas import utc_now

from .schemas import Experience

STOP_WORDS = {"the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "with", "is", "my", "me", "this", "that", "it", "from", "into"}


def fingerprint(text: str, limit: int = 12) -> list[str]:
    """Deterministic token fingerprint for similarity matching."""
    tokens = re.findall(r"[a-z0-9_.-]+", text.lower())
    return [token for token in tokens if token not in STOP_WORDS][:limit]


def similarity(a: list[str], b: list[str]) -> float:
    """Jaccard-style token overlap in [0, 1]."""
    left, right = set(a), set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def normalize_failure_signature(error: str) -> str:
    """Normalized failure pattern: lowercase alphanumerics of the
    dominant error tokens (e.g. `vite-build-env-missing`)."""
    tokens = re.findall(r"[a-z0-9]+", (error or "").lower())
    meaningful = [token for token in tokens if token not in STOP_WORDS]
    return "-".join(meaningful[:6]) or "unknown-failure"


class ExperienceStore:
    """Experiences live in the existing SQLite database (two tables
    added through the Phase 13 migration framework — no new database).
    Retrieval returns a small ranked set: relevance (fingerprint
    similarity) + environment match + success/failure relevance +
    recency decay + verification — never a dump of history."""

    def __init__(self, database, *, max_retrieved: int = 5, decay_half_life_days: float = 90.0):
        self.database = database
        self.max_retrieved = max_retrieved
        self.decay_half_life_days = decay_half_life_days

    async def record(self, experience: Experience) -> Experience:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO experiences (experience_id, task_id, domain, task_type, success,
               failure_signature, strategy_id, experience_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(experience_id) DO UPDATE SET experience_json = excluded.experience_json""",
            (experience.experience_id, experience.task_id, experience.domain, experience.task_type,
             int(experience.success), experience.failure_signature, experience.strategy_used,
             experience.model_dump_json(), experience.created_at.isoformat()),
        )
        await connection.commit()
        return experience

    async def get(self, experience_id: str) -> Experience | None:
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT experience_json FROM experiences WHERE experience_id = ?", (experience_id,))
        row = await cursor.fetchone()
        return Experience.model_validate_json(row["experience_json"]) if row else None

    async def _all(self) -> list[Experience]:
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT experience_json FROM experiences ORDER BY created_at DESC")
        rows = await cursor.fetchall()
        return [Experience.model_validate_json(row["experience_json"]) for row in rows]

    def _recency_weight(self, experience: Experience) -> float:
        age_days = max((utc_now() - experience.created_at).total_seconds() / 86400.0, 0.0)
        return 0.5 ** (age_days / self.decay_half_life_days)

    def _score(self, experience: Experience, task_fp: list[str], context_fp: list[str],
               environment: dict[str, str], prefer_failures: bool) -> float:
        goal_similarity = similarity(experience.task_fingerprint, task_fp)
        context_similarity = similarity(experience.context_fingerprint, context_fp)
        env_match = sum(1 for key, value in environment.items()
                        if experience.environment.get(key) == value) / max(len(environment), 1)
        relevance = 0.55 * goal_similarity + 0.2 * context_similarity + 0.25 * env_match
        outcome = (0.0 if experience.success else 1.0) if prefer_failures else (1.0 if experience.success else 0.35)
        verification = experience.verification_score
        recency = self._recency_weight(experience)
        return relevance * (0.5 + 0.3 * outcome + 0.2 * verification) * (0.6 + 0.4 * recency)

    #: Strategies recorded BEFORE the native-backend policy. VYOM
    #: succeeded at desktop and system goals by driving a shell, so those
    #: runs were stored as good experience and would keep teaching it to
    #: reach for PowerShell first. They are not deleted - the history is
    #: real and still useful for diagnosis - but they are no longer
    #: eligible for automatic reuse on semantic PC actions, which now have
    #: native capabilities that a shell can only imitate badly.
    _SHELL_STRATEGY_MARKERS = (
        "powershell", "pwsh", "cmd.exe", "cmd /c", "get-process", "get-date",
        "get-childitem", "get-content", "get-volume", "taskkill", "start-process",
    )
    #: Goal families that must never be satisfied by a shell strategy.
    _NATIVE_ONLY_DOMAINS = {"system", "desktop"}

    @classmethod
    def prohibited_for_auto_reuse(cls, experience) -> bool:
        """Is this experience incompatible with the native-backend policy?"""
        if experience.domain not in cls._NATIVE_ONLY_DOMAINS:
            return False
        blob = " ".join(str(value) for value in (
            experience.goal, experience.result_summary,
            getattr(experience, "strategy_used", "") or "",
            experience.conditions,
        )).lower()
        return any(marker in blob for marker in cls._SHELL_STRATEGY_MARKERS)

    async def retrieve_similar(
        self, goal: str, *, domain: str | None = None, context_fingerprint: list[str] | None = None,
        environment: dict[str, str] | None = None, prefer_failures: bool = False,
    ) -> list[tuple[Experience, float]]:
        task_fp = fingerprint(goal)
        context_fp = context_fingerprint or []
        environment = environment or {}
        candidates = []
        for experience in await self._all():
            if domain and experience.domain != domain:
                continue
            # A past success achieved through a shell is not a template for
            # a desktop action any more. Kept in the store, withheld from
            # reuse. A FAILURE is still worth surfacing - knowing that the
            # shell route failed is exactly the lesson worth keeping.
            if not experience.success and prefer_failures:
                pass
            elif self.prohibited_for_auto_reuse(experience):
                continue
            score = self._score(experience, task_fp, context_fp, environment, prefer_failures)
            if score <= 0.02:
                continue  # irrelevant experience rejection
            candidates.append((experience, round(score, 4)))
        candidates.sort(key=lambda pair: pair[1], reverse=True)
        return candidates[: self.max_retrieved]

    async def retrieve_failures(self, goal: str, domain: str | None = None) -> list[tuple[Experience, float]]:
        return await self.retrieve_similar(goal, domain=domain, prefer_failures=True)

    async def known_entity(self, name: str) -> Experience | None:
        """Memory-before-question: is there verified knowledge about this
        project/client/topic already?"""
        token = name.strip().lower()
        for experience in await self._all():
            if token and token in " ".join(experience.task_fingerprint):
                return experience
        return None

    async def consolidate(self, threshold: int = 5) -> list[dict]:
        """Experience compression: many similar successes/failures
        collapse into a generalized lesson + statistics; originals stay
        available in storage."""
        groups: dict[tuple, list[Experience]] = {}
        for experience in await self._all():
            key = (experience.domain, experience.task_type, experience.success,
                   experience.failure_signature or "")
            groups.setdefault(key, []).append(experience)
        summaries = []
        for key, members in groups.items():
            if len(members) < threshold:
                continue
            summaries.append({
                "domain": key[0], "task_type": key[1], "success": key[2],
                "failure_signature": key[3] or None,
                "sample_size": len(members),
                "success_rate": sum(1 for m in members if m.success) / len(members),
                "avg_verification": round(sum(m.verification_score for m in members) / len(members), 3),
                "avg_latency_ms": round(sum(m.latency_ms for m in members) / len(members), 1),
                "avg_cost": round(sum(m.cost for m in members) / len(members), 6),
                "representative": members[0].experience_id,
                "generalized_lesson": (
                    f"For {key[1]} in {key[0]}: {len(members)} experiences, "
                    f"{sum(1 for m in members if m.success)} succeeded; "
                    + (f"recurring failure {key[3]} — apply its lesson first." if key[3] else "approach is reliable under matching conditions.")
                ),
            })
        return summaries
