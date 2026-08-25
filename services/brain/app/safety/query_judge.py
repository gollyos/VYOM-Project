from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


class JudgeResult(BaseModel):
    """The judge's verdict on whether a generated query is safe to run.

    `safe` is the decision; `reason` is the human-readable justification
    (the LLM's comments, or the deterministic marker that tripped it)."""

    safe: bool
    reason: str


class QuerySafetyJudge:
    """VYOM's 'AI-as-a-judge' query-safety gate (the pattern taught in the
    LangGraph agentic data-agent tutorial).

    Before executing a model-generated SQL/query, it decides whether that
    query is SAFE to run: it must be read-only retrieval and must not
    modify the database (INSERT / UPDATE / DELETE / DROP / ALTER /
    TRUNCATE) nor the schema. This is a two-layer gate:

      1. Deterministic pre-check: a regex over destructive SQL keywords
         (a `DROP TABLE`, a `DELETE FROM`, a `; DROP` injection) is
         rejected immediately WITHOUT spending an LLM call. Never trust
         the model's own claim of safety.
      2. LLM judge: for anything that isn't an obvious destructive
         statement, ask the configured LLM (bound to a strict
         JudgeResult schema + a read-only-enforcing prompt) whether the
         query is safe. The prompt explicitly forbids executing anything
         that modifies data/structure, and the model is constrained to
         answer yes/no.

    It is deliberately CONSERVATIVE (fail-to-unsafe): if the LLM call
    fails, the output can't be parsed, or the answer is ambiguous, the
    query is treated as unsafe rather than silently allowed — a wrong
    judgment here is far more costly than a false rejection. This is the
    same honesty the rest of VYOM's integration layer follows."""

    #: SQL keywords (word-boundary, case-insensitive) that mutate data or
    #: schema. Any occurrence marks the query unsafe deterministically,
    #: BEFORE any LLM call — these are non-negotiable.
    DESTRUCTIVE_KEYWORDS = (
        r"\binsert\b", r"\bupdate\b", r"\bdelete\b", r"\bdrop\b",
        r"\balter\b", r"\btruncate\b", r"\bmerge\b", r"\breplace\b",
        r"\bcreate\b", r"\bgrant\b", r"\brevoke\b", r"\bexec\b",
        r"\bexecute\b", r"\bcommit\b", r"\brollback\b", r"\bvacuum\b",
    )
    #: A ';' followed by another statement is a classic injection vector
    #: for appending a destructive statement after a read-only one.
    SEMICOLON_INJECTION = r";\s*(?:--|#|\s)*\s*(?:[a-z]+\s+)*\s*(?:drop|delete|update|insert|alter|truncate|grant|revoke)\b"

    _detectives = [re.compile(p, re.IGNORECASE) for p in (*DESTRUCTIVE_KEYWORDS, SEMICOLON_INJECTION)]

    def __init__(self, llm_call: Callable[[str], Awaitable[str]] | None = None) -> None:
        """`llm_call` is an async callable(prompt) -> str used for the
        judge pass. If omitted, a default that calls the configured Google
        (Gemini) provider is lazily built so the gate always has SOME real
        model behind it when `judge()` is invoked."""
        self._llm_call = llm_call

    @staticmethod
    def _default_llm_call() -> Callable[[str], Awaitable[str]]:
        from app.providers.google import GoogleProvider
        from app.providers.base import ProviderRequest
        from app.schemas.tasks import TaskDomain, TaskProfile

        proto = GoogleProvider(timeout_seconds=30.0)

        async def _call(prompt: str) -> str:
            if not proto.configured:
                raise RuntimeError("No LLM is configured for the query-safety judge")
            response = await proto.generate(
                ProviderRequest(
                    model="gemini-3.1-flash-lite",
                    user_request=prompt,
                    system_instruction=(
                        "You are a strict SQL/query safety judge. Answer only with a "
                        "JSON object. Never run or suggest running anything destructive."
                    ),
                    profile=TaskProfile(domain=TaskDomain.GENERAL, complexity=1, deterministic=True, intent="query_safety_judge"),
                )
            )
            return response.text

        return _call

    @property
    def llm_call(self) -> Callable[[str], Awaitable[str]]:
        if self._llm_call is None:
            self._llm_call = self._default_llm_call()
        return self._llm_call

    def _deterministic_check(self, query: str) -> str | None:
        """Return the reason the query is UNSAFE if a deterministic
        destructive marker matches, else None. No LLM is involved."""
        if not query or not query.strip():
            return "empty query provided"
        for pattern in self._detectives:
            if pattern.search(query):
                match = pattern.search(query)
                return f"query contains a destructive SQL keyword/statement: '{match.group(0)[:40]}'"
        # A SELECT is the only safe retrieval form.
        if not re.search(r"\bselect\b", query, re.IGNORECASE):
            return "query does not appear to be a read-only SELECT"
        return None

    def _judge_prompt(self, query: str) -> str:
        return (
            "You are a strict SQL query safety judge. Determine whether the following "
            "query is SAFE to run.\n\n"
            "A safe query: (a) only RETRIEVES data (SELECT), (b) does NOT modify the "
            "database in any way (no INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, "
            "GRANT, REVOKE, EXEC, MERGE), and (c) does NOT change the schema/structure.\n\n"
            "Answer with ONLY a JSON object of the form "
            '{"safe": true|false, "reason": "one short sentence"}. '
            'Set "safe" to false for anything destructive, ambiguous, or that you cannot '
            "verify. Do not include any other text.\n\n"
            f"QUERY TO JUDGE:\n{query}"
        )

    def _parse_verdict(self, text: str) -> JudgeResult:
        """Parse the judge LLM's text into a JudgeResult, tolerating fenced /
        extra prose but NEVER defaulting ambiguous output to safe."""
        cleaned = text.strip()
        # strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE).strip()
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return JudgeResult(safe=False, reason="judge returned no parsable verdict")
        try:
            data = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError:
            return JudgeResult(safe=False, reason="judge returned malformed JSON")
        raw = data.get("safe")
        if not isinstance(raw, bool):
            # A string yes/no/no-token is rejected as unsafe — only an
            # explicit boolean true is accepted.
            return JudgeResult(safe=False, reason="judge did not give an explicit boolean verdict")
        reason = str(data.get("reason") or "judge provided no reason").strip()
        return JudgeResult(safe=raw, reason=reason)

    async def judge(self, query: str) -> JudgeResult:
        """Two-layer safety gate. Returns the verdict; never raises for an
        'unsafe' verdict (the caller decides how to react)."""
        # 1) Deterministic pre-check (no LLM cost).
        deterministic = self._deterministic_check(query)
        if deterministic is not None:
            return JudgeResult(safe=False, reason=deterministic)
        # 2) LLM judge pass.
        try:
            text = await self.llm_call(self._judge_prompt(query))
        except Exception as error:
            return JudgeResult(safe=False, reason=f"query-safety judge could not run: {error}"[:300])
        return self._parse_verdict(text)
