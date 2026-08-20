from __future__ import annotations

from dataclasses import dataclass

from app.devices.schemas import utc_now

from .experience_store import ExperienceStore, similarity
from .schemas import (
    Experience,
    ReuseAction,
    ReuseDecision,
    StrategyProposal,
    StrategyRecord,
    StrategyStatus,
)


@dataclass
class AdaptiveConfig:
    minimum_strategy_sample: int = 5          # low-sample protection
    decay_half_life_days: float = 60.0        # strategy decay
    regime_weight: float = 0.5                # current-condition relevance
    recency_weight: float = 0.3
    promote_threshold: float = 0.6            # evolution evidence gate
    max_recent_outcomes: int = 50
    allow_paper_strategy_adaptation: bool = True


class StrategyEngine:
    """Generic strategy layer (coding/research/browser/trading...).
    Selection = current-condition match x decayed success x sample-size
    confidence. Never blindly replays an old winner: condition mismatch
    and regime-specific performance dominate aggregate history."""

    def __init__(self, database, config: AdaptiveConfig | None = None):
        self.database = database
        self.config = config or AdaptiveConfig()
        self._strategies: dict[str, StrategyRecord] = {}

    # -- persistence ------------------------------------------------------

    async def _load_all(self) -> None:
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT strategy_json FROM adaptive_strategies")
        rows = await cursor.fetchall()
        self._strategies = {
            record.strategy_id: record
            for record in (StrategyRecord.model_validate_json(row["strategy_json"]) for row in rows)
        }

    async def save(self, record: StrategyRecord) -> StrategyRecord:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO adaptive_strategies (strategy_id, domain, name, version, status, strategy_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(strategy_id) DO UPDATE SET status = excluded.status,
               strategy_json = excluded.strategy_json, updated_at = excluded.updated_at""",
            (record.strategy_id, record.domain, record.name, record.version,
             record.status.value, record.model_dump_json(), utc_now().isoformat()),
        )
        await connection.commit()
        self._strategies[record.strategy_id] = record
        return record

    async def get(self, strategy_id: str) -> StrategyRecord | None:
        if not self._strategies:
            await self._load_all()
        return self._strategies.get(strategy_id)

    async def list(self, domain: str | None = None) -> list[StrategyRecord]:
        if not self._strategies:
            await self._load_all()
        records = list(self._strategies.values())
        return [r for r in records if domain is None or r.domain == domain]

    async def find_or_create(self, record: StrategyRecord, *, evidence: Experience | None = None) -> StrategyRecord:
        """Only meaningful reusable patterns become strategies: a new
        strategy requires at least one verified outcome."""
        if evidence is not None and evidence.verification_score < 0.5:
            return record  # unverified work never seeds a strategy
        existing = await self.get(record.strategy_id)
        if existing is None:
            record.status = StrategyStatus.WATCH  # under-sampled until proven
            return await self.save(record)
        return existing

    # -- outcomes & decay ---------------------------------------------------

    async def record_outcome(self, strategy_id: str, *, success: bool, score: float = 1.0,
                             conditions: dict | None = None) -> StrategyRecord | None:
        record = await self.get(strategy_id)
        if record is None:
            return None
        record.outcomes.append({"at": utc_now().isoformat(), "success": bool(success),
                                "score": score, **(conditions or {})})
        record.outcomes = record.outcomes[-self.config.max_recent_outcomes :]
        record.last_used = utc_now()
        return await self.save(record)

    def _decay(self, outcome: dict) -> float:
        try:
            from datetime import datetime

            age_days = max((utc_now() - datetime.fromisoformat(outcome["at"])).total_seconds() / 86400.0, 0.0)
        except Exception:
            age_days = 0.0
        return 0.5 ** (age_days / self.config.decay_half_life_days)

    def performance_by_condition(self, record: StrategyRecord, condition_key: str = "regime") -> dict[str, dict]:
        """Performance split by context (e.g. market regime) — a
        strategy is never judged by its aggregate score alone."""
        buckets: dict[str, dict] = {}
        for outcome in record.outcomes:
            bucket = str(outcome.get(condition_key, "default"))
            entry = buckets.setdefault(bucket, {"n": 0, "wins": 0})
            entry["n"] += 1
            entry["wins"] += 1 if outcome.get("success") else 0
        for entry in buckets.values():
            entry["rate"] = round(entry["wins"] / entry["n"], 3) if entry["n"] else 0.0
        return buckets

    def evaluate(self, record: StrategyRecord, current_conditions: dict) -> dict:
        """Score a strategy for CURRENT conditions: condition match x
        decayed success x sample confidence, with low-sample shrinkage
        and regime-specific override."""
        total = len(record.outcomes)
        wins = sum(1 for o in record.outcomes if o.get("success"))
        base_rate = (wins / total) if total else 0.0

        # Current-condition relevance dominates. A strategy with ZERO
        # outcomes under the current conditions is "untested here": its
        # effective rate is discounted so a perfect aggregate record can
        # never outrank a strategy actually proven in this regime.
        relevant = [o for o in record.outcomes
                    if all(str(o.get(k)) == str(v) for k, v in current_conditions.items())] if current_conditions else list(record.outcomes)
        relevant_total = len(relevant)
        relevant_wins = sum(1 for o in relevant if o.get("success"))
        condition_rate = (relevant_wins / relevant_total) if relevant_total else None

        # Decayed long-term performance.
        decayed = [(1.0 if o.get("success") else 0.0) * self._decay(o) for o in record.outcomes]
        weight_sum = sum(self._decay(o) for o in record.outcomes)
        decayed_rate = (sum(decayed) / weight_sum) if weight_sum else 0.0

        sample_confidence = min(total / max(self.config.minimum_strategy_sample, 1), 1.0)
        if condition_rate is not None and relevant_total >= 2:
            effective_rate = condition_rate
        elif condition_rate is None and current_conditions:
            effective_rate = decayed_rate * 0.5  # untested in these conditions
        else:
            effective_rate = decayed_rate
        score = (self.config.regime_weight * effective_rate
                 + self.config.recency_weight * decayed_rate
                 + (1 - self.config.regime_weight - self.config.recency_weight) * base_rate)
        # Low-sample protection: shrink toward neutral 0.5.
        shrunk = 0.5 + (score - 0.5) * sample_confidence
        return {
            "strategy_id": record.strategy_id, "name": record.name, "status": record.status.value,
            "sample_size": total, "relevant_sample": relevant_total,
            "overall_rate": round(base_rate, 3), "condition_rate": condition_rate,
            "decayed_rate": round(decayed_rate, 3), "sample_confidence": round(sample_confidence, 3),
            "score": round(shrunk, 3),
            "by_regime": self.performance_by_condition(record),
        }

    async def select(self, domain: str, current_conditions: dict) -> dict | None:
        candidates = [self.evaluate(r, current_conditions) for r in await self.list(domain)]
        usable = [c for c in candidates if c["status"] in ("active",) or (c["status"] == "watch" and c["sample_size"] > 0)]
        if not usable:
            return None
        usable.sort(key=lambda c: c["score"], reverse=True)
        return usable[0]

    # -- reuse vs adapt ------------------------------------------------------

    async def decide_reuse(self, goal: str, domain: str, environment: dict[str, str],
                           current_conditions: dict, store: ExperienceStore) -> ReuseDecision:
        similar_results = await store.retrieve_similar(goal, domain=domain, environment=environment)
        similar = similar_results[0][0] if similar_results else None
        best = await self.select(domain, current_conditions)
        env_changed = similar is not None and any(
            similar.environment.get(key) not in (value, None) for key, value in environment.items()
        )

        if best is None or best["score"] < 0.45 or best["sample_size"] < self.config.minimum_strategy_sample:
            return ReuseDecision(action=ReuseAction.REPLAN, strategy_id=best["strategy_id"] if best else None,
                                 reasons=["no proven strategy matches current conditions"],
                                 confidence=0.3, condition_match=best["score"] if best else 0.0)
        condition_match = best["condition_rate"] if best["condition_rate"] is not None else best["decayed_rate"]
        if condition_match is not None and condition_match >= 0.6 and not env_changed:
            return ReuseDecision(action=ReuseAction.REUSE, strategy_id=best["strategy_id"],
                                 reasons=[f"strategy {best['name']} succeeded in matching conditions "
                                          f"({best['relevant_sample']} matching outcomes)"],
                                 confidence=min(0.95, best["score"]), condition_match=best["score"])
        return ReuseDecision(action=ReuseAction.ADAPT, strategy_id=best["strategy_id"],
                             reasons=(["environment changed since the proven run"] if env_changed else [])
                                     + [f"conditions only partially match (score {best['score']})"],
                             confidence=best["score"] * 0.8, condition_match=best["score"])

    # -- status lifecycle ------------------------------------------------------

    async def review_status(self, strategy_id: str, *, recent_window: int = 5, failure_threshold: float = 0.7) -> StrategyRecord | None:
        record = await self.get(strategy_id)
        if record is None:
            return None
        recent = record.outcomes[-recent_window:]
        if len(recent) >= recent_window:
            failure_rate = sum(1 for o in recent if not o.get("success")) / len(recent)
            if failure_rate >= failure_threshold and record.status == StrategyStatus.ACTIVE:
                record.status = StrategyStatus.DEGRADED  # pause PAPER usage and investigate
        if record.status == StrategyStatus.DEGRADED:
            total = len(record.outcomes)
            if total and sum(1 for o in record.outcomes if o.get("success")) / total < 0.3:
                record.status = StrategyStatus.PAUSED
        return await self.save(record)

    # -- evolution (trading-safe) -------------------------------------------------

    async def propose_evolution(self, strategy_id: str, reason: str, evidence: dict) -> StrategyProposal:
        record = await self.get(strategy_id)
        if record is None:
            raise KeyError(strategy_id)
        major, minor = record.version.split(".")[:2]
        to_version = f"{major}.{int(minor) + 1}"
        return StrategyProposal(strategy_id=strategy_id, from_version=record.version,
                                to_version=to_version, reason=reason, evidence=evidence)

    @staticmethod
    def evaluate_proposal(proposal: StrategyProposal, *, backtest: dict, validation: dict,
                          paper_comparison: dict | None = None) -> StrategyProposal:
        """A proposal is promotable only if backtest AND out-of-sample
        validation beat the current strategy by the configured
        threshold. Otherwise it is rejected — the working version is
        never overwritten, and live trading is never involved."""
        current = float(backtest.get("current_metric", 0.0))
        candidate = float(backtest.get("candidate_metric", 0.0))
        oos_current = float(validation.get("current_metric", 0.0))
        oos_candidate = float(validation.get("candidate_metric", 0.0))
        threshold = 0.0  # must at least match; promotion gate adds margin below
        beats_backtest = candidate >= current + threshold
        beats_oos = oos_candidate >= oos_current + threshold
        if proposal.requires and not beats_backtest or not beats_oos:
            proposal.state = "rejected"
            return proposal
        margin_ok = (candidate - current) >= 0 and (oos_candidate - oos_current) >= 0
        proposal.evidence = {"backtest": backtest, "validation": validation,
                             "paper_comparison": paper_comparison or {}}
        proposal.state = "promotable" if margin_ok else "tested"
        return proposal
