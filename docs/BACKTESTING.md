# VYOM Backtesting

## Principle

Backtesting is deterministic historical simulation, never a paid-model
estimate of "how would this have done." `BacktestEngine`
(`services/brain/app/backtesting/engine.py`) runs: validate strategy
structure -> fetch historical candles -> bar-by-bar simulation -> metrics
-> integrity notes -> `BacktestResult`. Results are never presented as
guaranteed future performance (`docs/TRADING_RISK_POLICY.md`).

## Structured strategies only

A `StrategySpec` (`services/brain/app/strategies/schemas.py`) is entirely
declarative: `entry_rules`/`exit_rules`/`filters` are lists of
`IndicatorRule` (`field`, `operator`, `value` or `compare_field`). There
is no "buy whenever the AI feels bullish" execution path — `StrategyEvaluator`
(`services/brain/app/strategies/evaluator.py`) only evaluates these
structured comparisons against indicator fields computed in code. A
strategy with no `entry_rules`/`exit_rules`/`universe` fails
`validate_structure()` and is rejected before a backtest runs.

## Lookahead prevention

The concrete mechanism (`services/brain/app/strategies/evaluator.py:compute_fields`,
`services/brain/app/backtesting/simulator.py:BarSimulator`):

1. At bar `i`, every indicator field is computed only from
   `candles[0:i+1]` — no future bar is ever visible to the strategy.
2. A signal generated while evaluating bar `i` fills at bar `i+1`'s
   **open** price, never at bar `i`'s own close.

`tests/test_phase10_finance.py::test_lookahead_protection_field_computation_ignores_future_bars`
proves this directly: mutating a candle beyond the evaluation index never
changes the fields computed at that index.

## Data and execution assumptions

Every `BacktestResult` documents its own `integrity_notes`: indicator
timing, execution timing, the data provider/freshness used, and the
fees/slippage assumptions applied. It also notes a survivorship
limitation — the market-data layer does not model delisted/renamed
symbols, so a backtest over a fixed symbol list can overstate returns
relative to the true historical universe.

## Metrics

`compute_metrics` (`services/brain/app/backtesting/metrics.py`) computes
`win_rate_pct`, `profit_factor`, `average_win`/`average_loss`,
`expectancy`, `total_return_pct`, `max_drawdown_pct`, `exposure_pct`, and
Sharpe-like/Sortino-like ratios — each only when the underlying trade
sample actually supports it; an unsupported metric is left `None`, never
fabricated.

## Train/validation/out-of-sample and walk-forward

`WalkForwardEvaluator` (`services/brain/app/backtesting/walk_forward.py`)
splits history into development/validation/out-of-sample ranges
(`config/strategies.yaml: walk_forward`) and runs the same engine on each
split independently — a strategy is never judged on the exact data it was
tuned against. It flags a simple overfitting signal when out-of-sample
return is far weaker than development return. This is a foundation, not a
parameter-optimization search; VYOM does not auto-tune strategy
parameters against backtest results in Phase 10.

## Strategy comparison

Comparing multiple strategies surfaces return, drawdown, trade count,
expectancy, and stability side by side; a strategy is never selected as
"the winner" solely by raw return.

## Learning from results

VYOM may learn which strategy performed well in which regime, common
failure patterns, and model/data-provider reliability — subject to the
Phase 6 Learning Policy's evidence requirements
(`docs/VYOM_PROJECT_MEMORY.md`). A single losing backtest or paper trade
never becomes a generalized "this strategy is permanently bad" lesson.
