# VYOM Paper Trading

## Principle

`PaperBroker` (`services/brain/app/trading/paper_broker.py`) is a fully
local, simulated broker. Every record it produces — orders, fills,
positions — carries `label="PAPER"` and is stored separately from any
future real-broker integration. There is no method on `PaperBroker`,
`OrderSimulator`, or `TradeManager` that places a real order; a structural
regression test (`tests/test_phase10_finance.py::test_no_live_execution_methods_exist_on_paper_broker`)
guards against one ever being added silently.

## Lifecycle

```text
idea (TradeThesis)
  -> setup (TradeSetup via SetupBuilder)
  -> position sizing (deterministic risk-based calculator)
  -> risk validation (RiskEngine: PASS/REDUCE/REJECT)
  -> paper approval (manual by default; see below)
  -> paper order (PaperBroker.place_order)
  -> simulated fill (OrderSimulator)
  -> monitor (PaperBroker.recheck_pending for limit/stop orders)
  -> exit
  -> journal entry (JournalService)
  -> performance evaluation (strategy/paper analytics)
```

`TradeManager.propose()` (`services/brain/app/trading/trade_manager.py`)
implements the setup -> sizing -> risk -> approval steps; it stops at
`PENDING_APPROVAL` unless the caller already has explicit approval for
this specific trade (`approved=True`).

## Approval policy

Two policy modes exist: `manual` (default) and `paper_auto`. Manual
approval is the default for every simulated order
(`config/risk.yaml: paper_trading.default_approval_mode`). A user may
later explicitly enable `paper_auto` for a **named strategy** — this
authorization is scoped to that strategy's paper simulation and never
implies live-trading permission of any kind.

## Order types and simulated execution

`OrderSimulator` (`services/brain/app/trading/order_simulator.py`)
handles `market`, `limit`, and `stop` orders:

- **Market** always fills immediately at the current quote, adjusted by
  the configured slippage assumption.
- **Limit** fills only once the quote satisfies the limit price (buy:
  quote <= limit; sell: quote >= limit); otherwise it stays `pending`
  until a later `recheck_pending` call re-evaluates it against a fresh
  quote.
- **Stop** triggers similarly once the quote crosses the stop price, then
  fills as a market order.

Every `PaperOrder` records `order_id`, `symbol`, `side`, `quantity`,
`order_type`, `requested_price`, `fill_price`,
`slippage_assumption_bps`, `fee_assumption_bps`/`fees_paid`, `timestamp`,
and `status`. Slippage and fees are configurable assumptions
(`config/risk.yaml: execution_assumptions`), never a hidden constant.

## Cash and position accounting

`PaperBroker` maintains cash and positions directly on a `Portfolio` with
`kind=paper`. A buy that would exceed available paper cash is rejected
(`OrderStatus.REJECTED`, with a reason) rather than allowing negative
cash. A sell larger than the held quantity is rejected the same way.
Realized P&L is booked on every sell fill.

## Kill switch

See `docs/TRADING_RISK_POLICY.md` for `PaperKillSwitch`
(`pause_all`/`cancel_pending`/`close_simulated_positions`) and
`RiskKillSwitch` (automatic pause on daily-loss/drawdown/stale-data/
strategy-anomaly breach).

## Journal

Every simulated trade produces a `JournalEntry`
(`services/brain/app/trading/journal.py`): setup/thesis linkage, entry/exit
price and time, risk amount, result (`win`/`loss`/`breakeven`/`open`),
P&L, duration, sources, models involved, mistakes, what worked, and an
optional lesson. A loss is never automatically treated as proof the
underlying strategy is bad — see the Learning Policy note in
`docs/BACKTESTING.md` and `docs/VYOM_PROJECT_MEMORY.md`.
