# VYOM Finance Architecture

## Purpose and scope

Phase 10 adds financial intelligence, portfolio analytics, strategy
research, backtesting, and controlled **paper** trading. It is explicitly
**research + analytics + simulation + paper trading**, not unrestricted
live-money execution. No code path in this repository places a real
brokerage order, transfers funds, or handles brokerage credentials — see
`docs/TRADING_RISK_POLICY.md` and `docs/PAPER_TRADING.md`.

## Runtime shape

```text
Task Runtime
  -> Phase10Engine (mirrors BusinessEngine/Phase8Engine/Phase9Engine)
  -> market_data (provider-independent quotes/candles/fundamentals + freshness)
  -> finance (Instrument/Watchlist/Portfolio/Position + P&L/exposure/metrics)
  -> market_intelligence (technical analysis, regime, catalysts, sentiment, thesis)
  -> trading (setup builder, position sizing, paper broker, journal)
  -> risk (rules from config/risk.yaml, PASS/REDUCE/REJECT engine, kill switch)
  -> strategies (structured StrategySpec, versioned, evaluator)
  -> backtesting (deterministic historical simulation, walk-forward)
  -> alerts (deterministic condition checking, cooldown)
  -> Phase 10 events + contextual Composer objects over the Living Core
```

`Phase10Engine` (`services/brain/app/phase10/engine.py`) is the Task
Runtime delegate for finance/trading intents, exactly like
`Phase8Engine`/`Phase9Engine`. All orchestration here is deterministic —
no paid model call is required to resolve an instrument, fetch data,
compute an indicator, size a position, or run a risk check. This matches
the Omni Model Router principle of using the cheapest reliable path
(`docs/MODEL_ROUTING.md`); a model may still be used for prose in a
briefing, but never for the indicator math or the risk decision.

## Module layout

`services/brain/app/`:

- `market_data/` — provider abstraction, registry, quotes, candles,
  fundamentals, freshness, cache. See `docs/MARKET_DATA_POLICY.md`.
- `finance/` — `Instrument`, `Watchlist`, `Portfolio`, `Position` schemas
  plus P&L, exposure, and metrics calculators. See
  `docs/FINANCIAL_DATA_MODEL.md`.
- `market_intelligence/` — deterministic technical analysis, rule-based
  regime classification, catalyst research (reusing the Phase 8
  `DeepResearchTask`), a heuristic sentiment reader, and thesis
  construction.
- `trading/` — `TradeThesis`/`TradeSetup` schemas, position sizing, the
  local `PaperBroker`, order simulation, trade lifecycle management, and
  the trade journal. See `docs/PAPER_TRADING.md`.
- `risk/` — `RiskRules` (loaded only from `config/risk.yaml`), trade-level
  and portfolio-level risk checks, the `RiskEngine`, and kill switches. See
  `docs/TRADING_RISK_POLICY.md`.
- `strategies/` — structured `StrategySpec`, the rule evaluator, registry,
  and versioning.
- `backtesting/` — bar-by-bar simulator, metrics, walk-forward evaluator,
  and reports. See `docs/BACKTESTING.md`.
- `alerts/` — alert schemas, deterministic condition evaluation, and the
  cooldown-aware alert engine.
- `api/finance.py`, `api/markets.py`, `api/paper_trading.py`,
  `api/backtesting.py`, `api/alerts.py` — thin FastAPI routers over the
  services above.

## Fact vs. analysis separation

Every Phase 10 result keeps facts (quote, candles, computed indicator
values) separate from analysis/inference (regime label, sentiment,
thesis). A `MarketAnalysis` always carries both, and a thesis is never
built from price movement alone — see rule 11 in
`docs/TRADING_RISK_POLICY.md` and `ThesisBuilder`
(`app/market_intelligence/thesis_builder.py`).

## Cost tracking

Research, backtest compute, and any model calls used for prose stay
observable through the existing `UsageTracker`/performance-store
mechanism; `config/finance.yaml` documents which categories are tracked.
Nothing here introduces a second, hidden cost-tracking path.

## What Phase 10 explicitly does not do

No autonomous real-money trading, live broker order placement,
withdrawals, deposits, money transfers, leverage changes, autonomous
options/futures/crypto execution, wallet/private-key handling, or
AI-driven increases to risk limits. See `docs/TRADING_RISK_POLICY.md` for
the enforced boundary.
