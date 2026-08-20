# VYOM Trading Risk Policy

## Principle

Trading risk extends the existing L0–L3 Autonomy Policy; it does not
weaken it. Every proposed trade still passes through the strict Risk
Engine before any simulated order is placed, and every risk limit comes
exclusively from `config/risk.yaml` — never from a scattered constant in
source code, and never adjustable by an agent, skill, or model.

## Permission levels (extends `docs/AUTONOMY_POLICY.md`)

| Level | Finance/trading examples |
| --- | --- |
| L0 | Market analysis ("Analyze BTC"), portfolio risk read, backtest results, watchlist show/show-agency-equivalent queries |
| L1 | Watchlist add, create a PAPER trade setup/thesis (planning only, no order), create/run a backtest, draft a StrategySpec |
| L2 | Place/close/cancel a PAPER order, enable a named paper-trading strategy automation, resume paper trading after a pause |
| L3 | Real trading, real money transfer, real brokerage credential entry — no execution path exists in this codebase (see "What is never implemented" below) |

The Permission Engine checks paper-trading phrasing (`"paper" and
("trade"/"order"/"position")`) **before** its general "trade "/"buy
stock" markers, so `"create a paper trade setup"` is never misclassified
as the real-money L3 action those markers exist to catch
(`services/brain/app/security/permission_engine.py`).

## Risk rules

`RiskRules` (`services/brain/app/risk/rules.py`) loads immutable limits
from `config/risk.yaml`: `max_risk_per_trade_pct`, `max_daily_loss_pct`,
`max_open_positions`, `max_total_exposure_pct`,
`max_single_symbol_exposure_pct`, `max_sector_exposure_pct`,
`max_correlated_exposure_pct`, `max_drawdown_pct`. Execution assumptions
(`default_slippage_bps`, `default_fee_bps`) and the default paper-approval
mode also live there. Changing this file is itself a risk-policy
modification and goes through the normal Permission Engine / user action
— no agent or skill can edit it, and nothing in this codebase raises these
limits automatically.

## Risk decision flow

```text
TradeSetup + PositionSizingResult
  -> RiskEngine.evaluate()
  -> trade-level check (risk % of equity, symbol exposure, open-position count)
  -> portfolio-level check (total exposure, sector concentration, drawdown)
  -> PASS | REDUCE | REJECT (with reasons)
```

- **REJECT** covers any hard limit breach that cannot be fixed by sizing
  alone (too many open positions, symbol/sector concentration, portfolio
  drawdown, an active kill switch). Reasons are always returned; example:
  *"Opening this position would exceed max_open_positions (8)."*
- **REDUCE** covers the one reducible case: only the per-trade
  risk-percentage limit was breached. The engine returns a scaled
  `adjusted_position_size`; the caller decides whether to proceed at the
  reduced size.
- **PASS** means every check cleared.

No agent, model, or automation can bypass a REJECT or silently accept a
REDUCE at the original size — see `docs/AUTONOMY_POLICY.md` rule 33
(Risk Agent cannot relax configured hard limits).

## Kill switches

- `RiskKillSwitch` (`services/brain/app/risk/kill_switch.py`)
  automatically pauses new PAPER entries when daily loss, drawdown, stale
  market data, or a strategy anomaly breaches the configured limit. It
  never raises/relaxes a limit — it only ever adds a block. Resuming
  requires an explicit separate call (`resume()`); nothing in this module
  calls it automatically.
- `PaperKillSwitch` is the emergency stop for the paper-trading subsystem
  only: `pause_all`, `cancel_pending`, `close_simulated_positions`. A
  voice/API "stop paper trading" (`POST /api/paper-trading/kill-switch/pause`)
  executes immediately, bypassing the normal task/approval flow, mirroring
  `/api/desktop/emergency-pause` (`docs/DESKTOP_SECURITY.md`). It affects
  only PAPER records.

## No guaranteed-outcome language

Generated financial analysis, thesis, and backtest summaries must not use
language like "guaranteed", "can't lose", or "certain profit". Confidence
is always expressed as a bounded score with rationale, never certainty.

## What is never implemented

Autonomous real-money trading, live broker order placement, withdrawals,
deposits, money transfers, leverage changes, autonomous options/futures
execution, autonomous crypto transfers, wallet/private-key handling, and
AI-driven risk-limit increases. If a user asks VYOM to place a real
order, VYOM reports that live execution is disabled in the current
architecture — it never simulates a live confirmation.
