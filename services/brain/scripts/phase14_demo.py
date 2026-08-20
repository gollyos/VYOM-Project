"""Phase 14 adaptive-intelligence demos (real components, temp database).

Demo 1  same coding task twice -> second run retrieves the verified
        experience and gets a REUSE decision
Demo 2  Tool A fails / Tool B succeeds -> evidence-based tool preference
Demo 3  explicit user correction -> applied on the repeat task
Demo 4  two market regimes -> momentum NOT selected in its weak regime
Demo 5  strategy degradation -> evolution proposal -> evidence gate
Demo 6  unknown task -> replan decision (research path, not failure)
"""
from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from app.adaptive import (
    AdaptiveConfig,
    AdaptiveLearner,
    ExperienceStore,
    StrategyEngine,
    StrategyRecord,
    StrategyStatus,
    fingerprint,
    normalize_failure_signature,
)
from app.adaptive.context import AdaptiveContextService
from app.persistence.database import Database


def make_experience(goal, *, domain="coding", success=True, verification=0.9,
                    environment=None, tools=None, conditions=None, failure=None):
    from app.adaptive import Experience

    return Experience(
        goal=goal, domain=domain, success=success, verification_score=verification,
        task_fingerprint=fingerprint(goal), environment=environment or {"project": "vyom"},
        tools_used=tools or [], conditions=conditions or {}, failure_reason=failure,
        failure_signature=normalize_failure_signature(failure) if failure else None,
    )


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vyom-p14-", ignore_cleanup_errors=True) as root:
        database = Database(Path(root) / "demo.db")
        await database.connect()
        store = ExperienceStore(database)
        strategies = StrategyEngine(database, AdaptiveConfig(minimum_strategy_sample=5))
        learner = AdaptiveLearner(store, strategies)
        context_service = AdaptiveContextService(store)

        # -- Demo 1: same coding task twice -----------------------------
        first = make_experience("Build the VYOM desktop application with Tauri and Vite",
                                verification=0.95)
        await store.record(first)
        build_strategy = await strategies.save(StrategyRecord(
            domain="coding", name="tauri-vite-build",
            conditions={"task_type": "desktop_build"},
            actions=["verify env", "npm install", "cargo build"],
        ))
        for _ in range(6):
            await strategies.record_outcome(
                build_strategy.strategy_id,
                success=True, conditions={"task_type": "desktop_build"},
            )
        built = await context_service.build_experience_context(
            "Add a new desktop workflow to the VYOM application", "coding",
            {"project": "vyom"}, {"task_type": "desktop_build"}, strategies,
        )
        assert built.similar_experiences, "previous experience not retrieved"
        assert built.reuse_decision.action.value == "reuse", built.reuse_decision
        print(f"demo1 reuse: OK -> retrieved '{built.similar_experiences[0]['goal'][:40]}...' "
              f"decision={built.reuse_decision.action.value} "
              f"confidence={built.reuse_decision.confidence:.2f}")

        # -- Demo 2: tool A fails, tool B succeeds ------------------------
        for _ in range(3):
            await store.record(make_experience("Extract pricing page data", domain="research",
                                               tools=["defuddle"], conditions={"site_type": "js_heavy"},
                                               success=False, failure="defuddle returned empty body"))
        for _ in range(3):
            await store.record(make_experience("Extract pricing page data", domain="research",
                                               tools=["playwright"], conditions={"site_type": "js_heavy"},
                                               success=True))
        preferred, evidence = await learner.preferred_tool(
            ["defuddle", "playwright"], {"site_type": "js_heavy"},
        )
        assert preferred == "playwright"
        print(f"demo2 tool learning: OK -> {preferred} ({evidence})")

        # -- Demo 3: user correction applied on repeat ---------------------
        await learner.record_user_correction(
            goal="Summarize client research for Finora", domain="research",
            correction="Do not use provider X for sensitive client tasks",
        )
        repeat = await store.retrieve_similar("Summarize the client research for Finora", domain="research")
        applied = next((e for e, _ in repeat if e.user_correction), None)
        assert applied is not None and applied.source == "user_instruction"
        print(f"demo3 correction: OK -> '{applied.user_correction}' (priority source={applied.source})")

        # -- Demo 4: two regimes --------------------------------------------
        momentum = await strategies.save(StrategyRecord(domain="trading", name="momentum",
                                                         status=StrategyStatus.ACTIVE))
        for _ in range(8):
            await strategies.record_outcome(momentum.strategy_id, success=True, conditions={"regime": "trending_up"})
        for _ in range(6):
            await strategies.record_outcome(momentum.strategy_id, success=False, conditions={"regime": "range"})
        fade = await strategies.save(StrategyRecord(domain="trading", name="range-fade"))
        for _ in range(8):
            await strategies.record_outcome(fade.strategy_id, success=True, conditions={"regime": "range"})
        pick_trending = await strategies.select("trading", {"regime": "trending_up"})
        pick_range = await strategies.select("trading", {"regime": "range"})
        assert pick_trending["strategy_id"] == momentum.strategy_id
        assert pick_range["strategy_id"] == fade.strategy_id, "momentum must not be picked in its weak regime"
        print(f"demo4 regimes: OK -> trending={pick_trending['name']} "
              f"range={pick_range['name']} (momentum range rate="
              f"{pick_trending['by_regime']['range']['rate'] if pick_trending['strategy_id'] == momentum.strategy_id else strategies.evaluate(momentum, {'regime': 'range'})['by_regime']['range']['rate']})")

        # -- Demo 5: strategy evolution with evidence gate --------------------
        for _ in range(5):
            await strategies.record_outcome(momentum.strategy_id, success=False,
                                            conditions={"regime": "high_volatility"})
        reviewed = await strategies.review_status(momentum.strategy_id)
        proposal = await strategies.propose_evolution(
            momentum.strategy_id, "drawdown in high volatility", {"recent_loss_rate": 1.0},
        )
        weak = StrategyEngine.evaluate_proposal(
            proposal.model_copy(), backtest={"current_metric": 1.1, "candidate_metric": 0.9},
            validation={"current_metric": 1.0, "candidate_metric": 0.95},
        )
        strong = StrategyEngine.evaluate_proposal(
            proposal.model_copy(), backtest={"current_metric": 1.0, "candidate_metric": 1.4},
            validation={"current_metric": 1.0, "candidate_metric": 1.3},
        )
        assert weak.state == "rejected" and strong.state == "promotable"
        assert strong.approved_by_user is False  # promotion still needs the user
        print(f"demo5 evolution: OK -> status={reviewed.status.value} "
              f"proposal {proposal.from_version}->{proposal.to_version} "
              f"weak={weak.state} strong={strong.state} (user approval still required)")

        # -- Demo 6: unknown task -----------------------------------------------
        unknown = await context_service.build_experience_context(
            "Transcribe piano audio into sheet music", "creative", {}, {}, strategies,
        )
        assert unknown.reuse_decision.action.value == "replan"
        assert unknown.similar_experiences == []
        print("demo6 unknown task: OK -> replan decision, no fabricated experience; "
              "routes to capability search + research instead of failing")

        await database.close()
    print("\nPhase 14 demos: ALL PASSED")


if __name__ == "__main__":
    asyncio.run(main())
