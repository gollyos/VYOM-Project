from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.alerts.conditions import AlertContext, ConditionEvaluator
from app.alerts.engine import AlertEngine
from app.alerts.schemas import Alert, AlertCondition, AlertConditionType
from app.alerts.store import AlertStore
from app.backtesting.engine import BacktestEngine
from app.backtesting.simulator import BarSimulator
from app.backtesting.strategy import StrategyValidationError, validate_for_backtest
from app.finance.exposure import compute_exposure
from app.finance.schemas import Instrument, InstrumentType, Portfolio, PortfolioKind, Position
from app.finance.store import PortfolioStore
from app.market_data.candles import CandleService
from app.market_data.freshness import FreshnessPolicy
from app.market_data.provider import DisconnectedMarketDataProvider, LocalFixtureMarketDataProvider, MarketDataProvider
from app.market_data.quotes import QuoteService
from app.market_data.registry import ProviderRegistry
from app.market_data.schemas import Candle, DataFreshness, MarketState, MarketStatus, MarketType, ProviderCapabilityInfo, ProviderStatus, Quote
from app.market_intelligence.technical_analysis import TechnicalAnalysisEngine, atr, ema, macd, rsi, sma
from app.persistence.database import Database
from app.risk.engine import RiskDecisionType, RiskEngine
from app.risk.kill_switch import PaperKillSwitch, RiskKillSwitch
from app.risk.rules import RiskRules
from app.risk.trade_risk import evaluate_trade_risk
from app.runtime.task_classifier import TaskClassifier
from app.security.permission_engine import PermissionEngine
from app.schemas.approvals import PermissionLevel
from app.strategies.evaluator import StrategyEvaluator, compute_fields
from app.strategies.registry import ActiveStrategyImmutableError, StrategyRegistry
from app.strategies.schemas import IndicatorRule, RuleOperator, StrategySpec, StrategyStatus
from app.strategies.versioning import new_version
from app.trading.journal import JournalService
from app.trading.order_simulator import OrderSimulator
from app.trading.paper_broker import PaperBroker
from app.trading.position_sizing import InvalidStopError, PositionSizingInput, calculate_position_size
from app.trading.schemas import OrderSide, OrderStatus, OrderType, PaperOrder, TradeDirection
from app.trading.store import JournalStore, PaperOrderStore


RISK_CONFIG = {
    "default_paper_account": {"starting_cash": 100_000.0, "base_currency": "USD"},
    "limits": {
        "max_risk_per_trade_pct": 1.0, "max_daily_loss_pct": 3.0, "max_open_positions": 2,
        "max_total_exposure_pct": 100.0, "max_single_symbol_exposure_pct": 20.0,
        "max_sector_exposure_pct": 35.0, "max_correlated_exposure_pct": 45.0, "max_drawdown_pct": 15.0,
    },
    "execution_assumptions": {"default_slippage_bps": 5, "default_fee_bps": 2},
    "paper_trading": {"default_approval_mode": "manual"},
    "kill_switch": {
        "pause_on_daily_loss_breach": True, "pause_on_drawdown_breach": True,
        "pause_on_stale_data": True, "pause_on_strategy_anomaly": True,
    },
}


def risk_rules() -> RiskRules:
    return RiskRules.from_config(RISK_CONFIG)


class FakeQuoteProvider(MarketDataProvider):
    """Test-only provider with a controllable price, used where the
    fully-deterministic LocalFixtureMarketDataProvider can't exercise a
    specific price-crossing scenario (e.g. limit/stop fills)."""

    provider_id = "test-fake"

    def __init__(self, price: float = 100.0):
        self.price = price

    async def capability_info(self) -> ProviderCapabilityInfo:
        return ProviderCapabilityInfo(provider_id=self.provider_id, status=ProviderStatus.AVAILABLE)

    async def get_quote(self, symbol: str) -> Quote:
        return Quote(symbol=symbol.upper(), provider=self.provider_id, freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=self.price)

    async def get_candles(self, symbol: str, timeframe: str, lookback: int) -> None:
        raise NotImplementedError

    async def get_fundamentals(self, symbol: str) -> None:
        raise NotImplementedError

    async def get_market_status(self, market: MarketType) -> MarketStatus:
        return MarketStatus(market=market, state=MarketState.OPEN, provider=self.provider_id)


async def make_database(tmp_path: Path) -> Database:
    database = Database(tmp_path / f"phase10-{id(tmp_path)}.db")
    await database.connect()
    return database


def make_candles(closes: list[float], *, highs=None, lows=None, opens=None, volume=1000.0) -> list[Candle]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for i, close in enumerate(closes):
        open_price = opens[i] if opens else (closes[i - 1] if i > 0 else close)
        high = highs[i] if highs else max(open_price, close) * 1.001
        low = lows[i] if lows else min(open_price, close) * 0.999
        candles.append(Candle(timestamp=start + timedelta(days=i), open=open_price, high=high, low=low, close=close, volume=volume))
    return candles


# -- 1. Provider registry -------------------------------------------------

def test_provider_registry_exposes_local_fixture_by_default():
    registry = ProviderRegistry.from_config({"providers": {"local_fixture": {"enabled": True}}, "default_provider": "local-fixture"})
    provider = registry.default()
    assert provider.provider_id == "local-fixture"


def test_provider_registry_falls_back_to_disconnected_when_empty():
    registry = ProviderRegistry({}, default_provider_id=None)
    provider = registry.default()
    assert isinstance(provider, DisconnectedMarketDataProvider)


# -- 2. Stale market data ---------------------------------------------------

def test_freshness_policy_classifies_stale_data_as_historical():
    policy = FreshnessPolicy(live_max_age_seconds=15, delayed_max_age_seconds=900, cached_max_age_seconds=86400)
    old_timestamp = datetime.now(timezone.utc) - timedelta(days=2)
    assert policy.classify(old_timestamp) == DataFreshness.HISTORICAL


def test_freshness_policy_mock_never_reported_as_live():
    policy = FreshnessPolicy(live_max_age_seconds=15, delayed_max_age_seconds=900, cached_max_age_seconds=86400)
    assert policy.classify(datetime.now(timezone.utc), provider_is_mock=True) == DataFreshness.MOCK


def test_is_stale_for_decision_flags_old_envelope():
    from app.market_data.schemas import MarketDataEnvelope

    policy = FreshnessPolicy(15, 900, 86400)
    envelope = MarketDataEnvelope(symbol="AAPL", provider="test", retrieved_at=datetime.now(timezone.utc) - timedelta(hours=2))
    assert policy.is_stale_for_decision(envelope, max_age_seconds=1800) is True


# -- 3. Quote parsing / provenance -------------------------------------------

@pytest.mark.asyncio
async def test_local_fixture_quote_is_deterministic_and_labeled_mock():
    provider = LocalFixtureMarketDataProvider()
    quote_a = await provider.get_quote("AAPL")
    quote_b = await provider.get_quote("AAPL")
    assert quote_a.price == quote_b.price
    assert quote_a.provider == "local-fixture"
    assert quote_a.freshness == DataFreshness.MOCK


# -- 4. Candle parsing --------------------------------------------------------

@pytest.mark.asyncio
async def test_local_fixture_candles_are_ordered_and_bounded():
    provider = LocalFixtureMarketDataProvider()
    series = await provider.get_candles("MSFT", "1d", 50)
    assert len(series.candles) == 50
    timestamps = [c.timestamp for c in series.candles]
    assert timestamps == sorted(timestamps)
    assert all(c.high >= c.low for c in series.candles)


# -- 5. Indicator calculations ------------------------------------------------

def test_sma_and_ema_basic_values():
    values = [10, 11, 12, 13, 14]
    assert sma(values, 5) == 12.0
    assert sma(values, 6) is None
    assert ema(values, 3) is not None


def test_rsi_is_100_for_strictly_increasing_series():
    values = [float(i) for i in range(1, 20)]
    assert rsi(values, 14) == 100.0


def test_atr_requires_enough_candles():
    candles = make_candles([100, 101, 102])
    assert atr(candles, 14) is None
    candles = make_candles([100 + i for i in range(20)])
    assert atr(candles, 14) is not None


def test_macd_returns_none_without_enough_history():
    assert macd([1.0, 2.0, 3.0]) is None


def test_technical_engine_reports_insufficient_data_honestly():
    engine = TechnicalAnalysisEngine()
    candles = make_candles([100, 101, 99, 102, 103])
    snapshot = engine.analyze("TEST", "1d", candles)
    assert "sma_200" in snapshot.insufficient_data_for
    assert snapshot.sma_200 is None  # never fabricated


# -- 6. Position sizing --------------------------------------------------------

def test_position_sizing_computes_expected_quantity():
    result = calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=1.0, entry=100.0, stop=95.0))
    assert result.risk_amount == 1000.0
    assert result.distance_to_stop == 5.0
    assert result.position_size == 200.0  # 1000 / 5
    assert "account_size" in result.assumptions


def test_position_sizing_rejects_zero_distance_stop():
    with pytest.raises(InvalidStopError):
        calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=1.0, entry=100.0, stop=100.0))


# -- 7. Risk per trade ----------------------------------------------------------

def test_trade_risk_flags_oversized_risk_percentage():
    from app.trading.schemas import SetupStatus, TradeSetup

    rules = risk_rules()
    portfolio = Portfolio(name="Test", kind=PortfolioKind.PAPER, cash=100_000)
    setup = TradeSetup(instrument="AAPL", direction=TradeDirection.LONG, entry_zone=[100, 101], stop=90, invalidation="close below 90")
    sizing = calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=5.0, entry=100.0, stop=90.0))
    check = evaluate_trade_risk(setup, sizing, portfolio, rules)
    assert check.passed is False
    assert any("risk per trade" in reason.lower() for reason in check.reasons)


# -- 8. Portfolio exposure --------------------------------------------------------

def test_portfolio_exposure_computes_percentages():
    portfolio = Portfolio(name="Test", kind=PortfolioKind.MANUAL, cash=0)
    portfolio.positions.append(Position(instrument=Instrument(symbol="AAPL", sector="Technology"), quantity=10, average_price=100, current_price=100))
    portfolio.positions.append(Position(instrument=Instrument(symbol="XOM", sector="Energy"), quantity=10, average_price=100, current_price=100))
    exposure = compute_exposure(portfolio)
    assert exposure.total_value == 2000.0
    assert exposure.by_instrument["AAPL"] == 50.0
    assert exposure.by_sector["Technology"] == 50.0


# -- 9. Risk rejection (hard reasons never bypassable) -----------------------

def test_risk_engine_rejects_when_max_open_positions_exceeded():
    from app.trading.schemas import TradeSetup

    rules = risk_rules()  # max_open_positions = 2
    engine = RiskEngine(rules)
    portfolio = Portfolio(name="Test", kind=PortfolioKind.PAPER, cash=100_000)
    portfolio.positions.append(Position(instrument=Instrument(symbol="AAPL"), quantity=1, average_price=100, current_price=100))
    portfolio.positions.append(Position(instrument=Instrument(symbol="MSFT"), quantity=1, average_price=100, current_price=100))
    setup = _setup("GOOGL", 100, 95)
    sizing = calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=1.0, entry=100.0, stop=95.0))
    decision = engine.evaluate(setup, sizing, portfolio)
    assert decision.decision == RiskDecisionType.REJECT
    assert any("max_open_positions" in reason for reason in decision.reasons)


def test_risk_engine_reduces_oversized_but_otherwise_fine_trade():
    # A wide stop keeps the resulting position value well under the
    # single-symbol concentration limit, so only the risk-percentage rule
    # is breached — the reducible case, not a hard reject.
    rules = risk_rules()
    engine = RiskEngine(rules)
    portfolio = Portfolio(name="Test", kind=PortfolioKind.PAPER, cash=100_000)
    setup = _setup("GOOGL", 100, 50)
    sizing = calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=2.0, entry=100.0, stop=50.0))
    decision = engine.evaluate(setup, sizing, portfolio)
    assert decision.decision == RiskDecisionType.REDUCE
    assert decision.adjusted_position_size is not None
    assert decision.adjusted_position_size < sizing.position_size


def _setup(symbol: str, entry: float, stop: float):
    from app.trading.schemas import TradeSetup

    return TradeSetup(instrument=symbol, direction=TradeDirection.LONG, entry_zone=[entry, entry + 1], stop=stop, invalidation=f"close below {stop}")


# -- 10-14. Paper broker: market/limit/stop, cancellation, fills, fees/slippage --

@pytest.mark.asyncio
async def test_paper_market_order_fills_immediately_and_moves_cash(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)

    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)
    order = await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 10, OrderType.MARKET)

    assert order.status == OrderStatus.FILLED
    assert order.label == "PAPER"
    assert order.fill_price is not None and order.fill_price > 100.0  # buy slippage pushes price up
    assert portfolio.cash < 10_000
    position = portfolio.find_position("AAPL")
    assert position is not None and position.quantity == 10
    await database.close()


@pytest.mark.asyncio
async def test_paper_limit_order_stays_pending_until_price_condition_met(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    # ttl=0 so the deliberately-mutated test price below is never masked by
    # QuoteService's cache (which exists to avoid unnecessary re-fetching
    # per rule 58, but would hide the price change this test simulates).
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)

    # Buy limit below current price never fills immediately.
    order = await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 5, OrderType.LIMIT, requested_price=90.0)
    assert order.status == OrderStatus.PENDING

    provider.price = 88.0  # price drops through the limit
    quote_service.cache.clear()  # bypass the freshness cache to simulate a later price update
    filled = await broker.recheck_pending(portfolio)
    assert len(filled) == 1
    assert filled[0].status == OrderStatus.FILLED
    await database.close()


def test_stop_order_simulator_triggers_on_crossing_price():
    simulator = OrderSimulator()
    order = PaperOrder(portfolio_id="p1", symbol="AAPL", side=OrderSide.SELL, quantity=1, order_type=OrderType.STOP, requested_price=95.0)
    quote_above = Quote(symbol="AAPL", provider="test", freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=100.0)
    assert simulator.try_fill(order, quote_above) is False
    quote_below = Quote(symbol="AAPL", provider="test", freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=94.0)
    assert simulator.try_fill(order, quote_below) is True
    assert order.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_pending_order_can_be_cancelled_but_not_a_filled_one(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)

    pending = await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 5, OrderType.LIMIT, requested_price=50.0)
    cancelled = await broker.cancel_order(pending.order_id)
    assert cancelled.status == OrderStatus.CANCELLED

    filled = await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 1, OrderType.MARKET)
    with pytest.raises(ValueError):
        await broker.cancel_order(filled.order_id)
    await database.close()


@pytest.mark.asyncio
async def test_fees_and_slippage_are_applied_and_configurable(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)

    order = await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 10, OrderType.MARKET, slippage_bps=100, fee_bps=50)
    assert order.fill_price == pytest.approx(101.0)  # 100 * (1 + 100bps)
    assert order.fees_paid == pytest.approx(101.0 * 10 * 0.005)
    await database.close()


# -- 15. P&L ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_realized_pnl_updates_on_sell(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)

    await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 10, OrderType.MARKET, slippage_bps=0, fee_bps=0)
    provider.price = 110.0
    quote_service.cache.clear()
    await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.SELL, 10, OrderType.MARKET, slippage_bps=0, fee_bps=0)
    assert portfolio.realized_pnl == pytest.approx(100.0)  # (110-100)*10
    await database.close()


# -- 17. Paper/live separation --------------------------------------------------

@pytest.mark.asyncio
async def test_paper_broker_refuses_non_paper_portfolio(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    manual_portfolio = Portfolio(name="Real", kind=PortfolioKind.MANUAL, cash=1000)
    with pytest.raises(ValueError):
        await broker.place_order(manual_portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 1, OrderType.MARKET)
    await database.close()


def test_no_live_execution_methods_exist_on_paper_broker():
    """Structural guard: PaperBroker must never grow a live/real execution
    path (rule 19/66)."""
    forbidden = {"place_live_order", "execute_live", "send_to_broker", "real_order"}
    assert forbidden.isdisjoint(dir(PaperBroker))


# -- 18. Paper kill switch ------------------------------------------------------

@pytest.mark.asyncio
async def test_paper_kill_switch_cancels_pending_orders(tmp_path):
    database = await make_database(tmp_path)
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    provider = FakeQuoteProvider(price=100.0)
    quote_service = QuoteService(ProviderRegistry({"test-fake": provider}, default_provider_id="test-fake"), FreshnessPolicy(15, 900, 86400))
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    portfolio = await broker.get_or_create_portfolio(starting_cash=10_000)
    await broker.place_order(portfolio, Instrument(symbol="AAPL"), OrderSide.BUY, 5, OrderType.LIMIT, requested_price=1.0)

    kill_switch = PaperKillSwitch()
    kill_switch.pause_all()
    assert kill_switch.is_paused() is True
    cancelled = await kill_switch.cancel_pending(broker, order_store, portfolio.id)
    assert len(cancelled) == 1
    order = await order_store.get(cancelled[0])
    assert order.status == OrderStatus.CANCELLED
    await database.close()


# -- 19-21. Backtesting: execution, lookahead, strategy validation --------------

def _sma_cross_strategy() -> StrategySpec:
    return StrategySpec(
        name="always-in-out", universe=["TEST"], timeframe="1d",
        entry_rules=[IndicatorRule(field="close", operator=RuleOperator.GT, value=0.0)],
        exit_rules=[IndicatorRule(field="close", operator=RuleOperator.GT, value=0.0)],
    )


def test_backtest_simulator_produces_trades_without_lookahead():
    spec = _sma_cross_strategy()
    candles = make_candles([100 + i for i in range(40)])
    output = BarSimulator().run(spec, candles, initial_capital=10_000, fees_bps=0, slippage_bps=0)
    assert len(output.trades) > 0
    assert len(output.equity_curve) in (len(candles) - 1, len(candles))


def test_lookahead_protection_field_computation_ignores_future_bars():
    candles = make_candles([100 + i for i in range(30)])
    fields_before = compute_fields(candles, 10)
    mutated = list(candles)
    mutated[29] = Candle(timestamp=mutated[29].timestamp, open=9999, high=9999, low=9999, close=9999, volume=1)
    fields_after = compute_fields(mutated, 10)
    assert fields_before == fields_after  # bar 29 must never influence bar 10's fields


def test_strategy_validation_rejects_missing_rules():
    empty_spec = StrategySpec(name="empty", universe=["TEST"])
    with pytest.raises(StrategyValidationError):
        validate_for_backtest(empty_spec, make_candles([100] * 40), max_bars=5000)


def test_strategy_validation_rejects_insufficient_history():
    spec = _sma_cross_strategy()
    with pytest.raises(StrategyValidationError):
        validate_for_backtest(spec, make_candles([100, 101, 102]), max_bars=5000)


@pytest.mark.asyncio
async def test_backtest_engine_runs_end_to_end_against_local_fixture_data(tmp_path):
    database = await make_database(tmp_path)
    registry = ProviderRegistry.from_config({"providers": {"local_fixture": {"enabled": True}}, "default_provider": "local-fixture"})
    candle_service = CandleService(registry)
    engine = BacktestEngine(candle_service, database)
    spec = _sma_cross_strategy()
    result = await engine.run(spec, "TESTX", lookback=60)
    assert result.bar_count == 60
    assert result.data_provider == "local-fixture"
    assert result.integrity_notes  # documents timing/data assumptions (rule 26)
    await database.close()


# -- 22. Strategy versioning ---------------------------------------------------

def test_new_version_bumps_version_and_resets_to_draft():
    spec = _sma_cross_strategy()
    spec.status = StrategyStatus.PAPER_TESTING
    bumped = new_version(spec, reason="tightened stop")
    assert bumped.version != spec.version
    assert bumped.status == StrategyStatus.DRAFT
    assert bumped.changelog[-1].startswith(bumped.version)


@pytest.mark.asyncio
async def test_registry_refuses_to_overwrite_active_paper_testing_strategy(tmp_path):
    database = await make_database(tmp_path)
    registry = StrategyRegistry(database)
    spec = _sma_cross_strategy()
    await registry.create(spec)
    await registry.set_status(spec.name, spec.version, StrategyStatus.PAPER_TESTING)

    mutated = spec.model_copy(update={"entry_rules": [IndicatorRule(field="close", operator=RuleOperator.LT, value=99999)]})
    with pytest.raises(ActiveStrategyImmutableError):
        await registry.create(mutated)
    await database.close()


# -- 23-24. Alerts: condition + cooldown ----------------------------------------

def test_price_above_condition_evaluates_correctly():
    evaluator = ConditionEvaluator()
    condition = AlertCondition(type=AlertConditionType.PRICE_ABOVE, symbol="AAPL", threshold=150.0)
    quote = Quote(symbol="AAPL", provider="test", freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=160.0)
    assert evaluator.evaluate(condition, AlertContext(quote=quote)) is True
    quote_low = Quote(symbol="AAPL", provider="test", freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=140.0)
    assert evaluator.evaluate(condition, AlertContext(quote=quote_low)) is False


@pytest.mark.asyncio
async def test_alert_cooldown_prevents_repeated_trigger(tmp_path):
    database = await make_database(tmp_path)
    store = AlertStore(database)
    engine = AlertEngine(store)
    alert = Alert(name="AAPL breakout", condition=AlertCondition(type=AlertConditionType.PRICE_ABOVE, symbol="AAPL", threshold=100.0), cooldown_seconds=3600)
    await engine.create(alert)

    async def context_provider(_alert):
        return AlertContext(quote=Quote(symbol="AAPL", provider="test", freshness=DataFreshness.MOCK, market_state=MarketState.OPEN, price=150.0))

    first = await engine.check_all(context_provider)
    second = await engine.check_all(context_provider)
    assert len(first) == 1
    assert len(second) == 0  # still within cooldown
    await database.close()


# -- 25. Model routing (zero paid model calls, correct L0-L2 classification) ----

def test_analyze_market_classifies_as_finance_with_no_model_needed():
    profile = TaskClassifier().classify("Analyze NVDA")
    assert profile.domain.value == "finance"
    assert profile.intent == "analyze_market"
    assert profile.deterministic is True
    assert "phase10" in profile.needs


def test_market_briefing_phrase_is_not_stolen_by_business_meeting_briefing():
    # "prepare me for ... meeting" is the meeting_briefing (business/CRM)
    # trigger and used to fire first regardless of content, so a request
    # naming the market briefing by its own exact phrase was routed to the
    # wrong engine entirely (business, not phase10) before this had any
    # exclusion for it.
    profile = TaskClassifier().classify("prepare me for the market briefing meeting")
    assert profile.intent == "market_briefing"
    assert "phase10" in profile.needs

    # The original business case must still route correctly.
    profile = TaskClassifier().classify("prepare me for the client meeting")
    assert profile.intent == "meeting_briefing"
    assert "business" in profile.needs


def test_paper_trade_setup_is_never_misclassified_as_l3_real_trading():
    engine = PermissionEngine()
    assert engine.classify("create a paper trade setup for BTC") == PermissionLevel.L1
    assert engine.classify("place a paper order for AAPL") == PermissionLevel.L2
    assert engine.classify("buy stock AAPL") == PermissionLevel.L3  # real trading phrase is untouched


# -- 26. Data failure pause (risk kill switch on stale data) --------------------

def test_kill_switch_pauses_on_stale_data_and_risk_engine_rejects():
    rules = risk_rules()
    kill_switch = RiskKillSwitch(rules)
    kill_switch.check_stale_data(True)
    assert kill_switch.is_active() is True

    engine = RiskEngine(rules, kill_switch)
    portfolio = Portfolio(name="Test", kind=PortfolioKind.PAPER, cash=100_000)
    setup = _setup("AAPL", 100, 95)
    sizing = calculate_position_size(PositionSizingInput(account_size=100_000, risk_percentage=1.0, entry=100.0, stop=95.0))
    decision = engine.evaluate(setup, sizing, portfolio)
    assert decision.decision == RiskDecisionType.REJECT
    assert "kill switch" in decision.reasons[0].lower()


def test_kill_switch_never_auto_resumes():
    rules = risk_rules()
    kill_switch = RiskKillSwitch(rules)
    kill_switch.check_daily_loss(day_start_equity=100_000, current_equity=90_000)
    assert kill_switch.is_active() is True
    # Nothing except an explicit resume() call clears it.
    kill_switch.resume()
    assert kill_switch.is_active() is False


# -- 27. Sensitive financial routing (config) ------------------------------------

def test_finance_config_marks_portfolio_data_sensitive():
    import yaml

    project_root = Path(__file__).resolve().parents[3]
    config = yaml.safe_load((project_root / "config" / "finance.yaml").read_text(encoding="utf-8"))
    assert config["sensitivity"]["portfolio_default_sensitivity"] == "sensitive"


# -- 28. UI events (Phase10Engine composition + emitted events) -----------------

@pytest.mark.asyncio
async def test_analyze_market_emits_events_and_ui_composition(tmp_path):
    from app.market_intelligence.catalyst_analysis import CatalystResearcher
    from app.market_intelligence.regime import RegimeClassifier
    from app.market_intelligence.researcher import MarketResearcher
    from app.market_intelligence.sentiment import SentimentAnalyzer
    from app.market_intelligence.technical_analysis import TechnicalAnalysisEngine
    from app.market_intelligence.thesis_builder import ThesisBuilder
    from app.phase10.engine import Phase10Engine
    from app.research.orchestrator import DeepResearchTask
    from app.schemas.tasks import Task, TaskProfile
    from app.trading.setup_builder import SetupBuilder
    from app.trading.trade_manager import TradeManager

    database = await make_database(tmp_path)
    registry = ProviderRegistry.from_config({"providers": {"local_fixture": {"enabled": True}}, "default_provider": "local-fixture"})
    quote_service = QuoteService(registry, FreshnessPolicy(15, 900, 86400))
    candle_service = CandleService(registry)
    research_task = DeepResearchTask.from_config({
        "depths": {"standard": {"max_queries": 2, "max_sources": 3, "max_model_calls": 1, "max_browser_time_seconds": 20, "max_cost": 0.02, "max_runtime_seconds": 30}},
        "default_depth": "standard", "default_source_diversity": 2, "search_providers": {"local_fixture": {"enabled": True}},
    })
    market_researcher = MarketResearcher(
        quote_service, candle_service, TechnicalAnalysisEngine(), RegimeClassifier(),
        CatalystResearcher(research_task), SentimentAnalyzer(), ThesisBuilder(),
    )
    rules = risk_rules()
    portfolio_store = PortfolioStore(database)
    order_store = PaperOrderStore(database)
    broker = PaperBroker(portfolio_store, order_store, quote_service)
    trade_manager = TradeManager(RiskEngine(rules), broker)
    strategy_registry = StrategyRegistry(database)
    backtest_engine = BacktestEngine(candle_service, database)
    from app.finance.store import WatchlistStore
    from app.trading.store import JournalStore
    from app.alerts.store import AlertStore
    from app.alerts.engine import AlertEngine

    engine = Phase10Engine(
        market_researcher=market_researcher, setup_builder=SetupBuilder(), trade_manager=trade_manager,
        paper_broker=broker, backtest_engine=backtest_engine, strategy_registry=strategy_registry,
        portfolio_store=portfolio_store, watchlist_store=WatchlistStore(database), journal_store=JournalStore(database),
        alert_engine=AlertEngine(AlertStore(database)), risk_rules=rules,
    )

    events: list[tuple[str, str, dict]] = []

    async def emit(event_type: str, message: str, payload: dict) -> None:
        events.append((event_type, message, payload))

    task = Task(goal="Analyze NVDA", user_request="Analyze NVDA")
    profile = TaskProfile(domain="finance", intent="analyze_market", needs={"phase10"}, deterministic=True)
    result = await engine.execute(task, profile, emit)

    assert result.ui_composition is not None
    object_types = {obj["type"] for obj in result.ui_composition["objects"]}
    assert "price-chart" in object_types
    event_types = {e[0] for e in events}
    assert "market_data_requested" in event_types
    assert "market_data_received" in event_types
    await database.close()


# -- 29. Journal creation ---------------------------------------------------------

@pytest.mark.asyncio
async def test_journal_entry_records_win_result_and_pnl(tmp_path):
    database = await make_database(tmp_path)
    journal_store = JournalStore(database)
    journal_service = JournalService(journal_store)

    entry_order = PaperOrder(portfolio_id="p1", symbol="AAPL", side=OrderSide.BUY, quantity=10, order_type=OrderType.MARKET, fill_price=100.0, status=OrderStatus.FILLED, filled_at=datetime.now(timezone.utc))
    entry = await journal_service.open_entry(portfolio_id="p1", symbol="AAPL", direction=TradeDirection.LONG, entry_order=entry_order, sources=["local-fixture"])
    assert entry.label == "PAPER"

    exit_order = PaperOrder(portfolio_id="p1", symbol="AAPL", side=OrderSide.SELL, quantity=10, order_type=OrderType.MARKET, fill_price=110.0, fees_paid=0.0, status=OrderStatus.FILLED, filled_at=datetime.now(timezone.utc) + timedelta(hours=1))
    closed = await journal_service.close_entry(entry.id, exit_order)
    assert closed.result.value == "win"
    assert closed.pnl == pytest.approx(100.0)

    persisted = await journal_store.get(entry.id)
    assert persisted is not None and persisted.pnl == pytest.approx(100.0)
    await database.close()
