# VYOM Financial Data Model

## Instrument

`Instrument` (`services/brain/app/finance/schemas.py`): `symbol`, `name`,
`type` (`equity`/`etf`/`index`/`crypto`/`forex`/`commodity`), `exchange`,
`currency`, `sector`, `industry`, `timezone`, `provider_ids`. Symbols are
normalized to uppercase for comparison/lookup.

## Watchlist

`Watchlist` holds `WatchlistItem` entries: `instrument`, `reason`, `tags`,
`added_at`, `alerts`, `notes`, `thesis`. Watchlists persist in SQLite
(`watchlists` table) keyed by name.

## Portfolio and Position

`Portfolio`: `id`, `name`, `kind` (`manual` | `paper`), `base_currency`,
`cash`, `positions`, `realized_pnl`, `unrealized_pnl` (derived),
`created_at`/`updated_at`. `kind=manual` represents a real portfolio
entered for analytics only — VYOM never executes a real order against it.
`kind=paper` is a fully simulated portfolio owned by `PaperBroker`.

`Position`: `instrument`, `quantity`, `average_price`, `current_price`,
`opened_at`, with `cost_basis`/`market_value`/`unrealized_pnl` derived
properties. A position without a current price never fabricates a P&L
figure — it is counted separately (`PnLSummary.unpriced_positions`).

Both persist in SQLite as JSON-blob records (`portfolios` table),
matching the existing `booking_requests`/`artifacts`/`delivery_packages`
persistence pattern used since Phase 8.

## Trade thesis and setup

`TradeThesis` (`services/brain/app/trading/schemas.py`): `instrument`,
`direction`, `time_horizon`, `thesis`, `supporting_evidence`,
`contradicting_evidence`, `catalysts`, `risks`, `invalidation`,
`confidence`, `data_timestamp`. `ThesisBuilder` refuses to construct one
from price movement alone — see `docs/TRADING_RISK_POLICY.md`.

`TradeSetup`: `instrument`, `direction`, `entry_zone`, `stop`, `targets`,
`risk_reward`, `time_horizon`, `thesis_id`, `invalidation`, `max_risk`,
`confidence`, `status` (`idea` -> `watching` -> `ready_for_paper` ->
`paper_open` -> `paper_closed` | `invalidated` | `expired`).

## Paper order and journal

`PaperOrder`: `order_id`, `label="PAPER"`, `portfolio_id`, `setup_id`,
`symbol`, `side`, `quantity`, `order_type`, `requested_price`,
`fill_price`, `slippage_assumption_bps`, `fee_assumption_bps`/`fees_paid`,
`status`, `timestamp`/`filled_at`. Persisted in `paper_orders`.

`JournalEntry`: `setup_id`, `thesis_id`, `portfolio_id`, `symbol`,
`direction`, `entry_price`/`entry_time`, `exit_price`/`exit_time`,
`risk_amount`, `result`, `pnl`, `duration_seconds`, `models_involved`,
`sources`, `mistakes`, `what_worked`, `lesson`. Persisted in
`trade_journal`.

## Strategy

`StrategySpec`: `id`, `name`, `version`, `universe`, `timeframe`,
`entry_rules`/`exit_rules`/`filters` (`IndicatorRule` lists), `risk_rules`,
`parameters`, `status`, `changelog`. Persisted in `strategies`, uniquely
keyed by `(name, version)`.

## Backtest result

`BacktestResult` (`services/brain/app/backtesting/engine.py`):
`strategy_name`/`strategy_version`, `symbol`, `timeframe`, `bar_count`,
`initial_capital`, `fees_bps`, `slippage_bps`, `data_provider`,
`data_freshness`, `trades`, `equity_curve`, `metrics`, `integrity_notes`.
Persisted in `backtest_results`.

## Alert

`Alert`: `name`, `instrument`, `condition` (`AlertCondition`: `type`,
`symbol`, `threshold`, `field`, `operator`, `portfolio_id`, `keyword`),
`schedule`, `status`, `cooldown_seconds`, `last_checked`,
`last_triggered`, `trigger_count`. Persisted in `market_alerts`.

## Sensitivity

Portfolio/account data defaults to `sensitive`
(`config/finance.yaml: sensitivity.portfolio_default_sensitivity`),
matching `docs/MEMORY_ARCHITECTURE.md`'s sensitivity model; only the
minimum relevant fields are included in any model-routed prompt. PAPER
trade data defaults to `normal` sensitivity since it carries no real
financial exposure.
