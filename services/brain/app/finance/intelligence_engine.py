from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from app.alerts.engine import AlertEngine
from app.backtesting.engine import BacktestEngine
from app.backtesting.reports import BacktestReport
from app.finance.exposure import compute_exposure, herfindahl_concentration
from app.finance.pnl import compute_pnl
from app.finance.schemas import Instrument, PortfolioKind, WatchlistItem
from app.finance.store import PortfolioStore, WatchlistStore
from app.market_intelligence.researcher import MarketAnalysis, MarketResearcher
from app.risk.engine import RiskDecisionType
from app.risk.portfolio_risk import evaluate_portfolio_risk
from app.risk.rules import RiskRules
from app.schemas.tasks import Task, TaskProfile
from app.schemas.results import ExecutionResult
from app.strategies.registry import StrategyRegistry
from app.trading.paper_broker import PaperBroker
from app.trading.schemas import TradeDirection, TradeResult
from app.trading.setup_builder import SetupBuilder
from app.trading.store import JournalStore
from app.trading.trade_manager import TradeManager, TradeProposalOutcome

from .extraction import extract_percentage, extract_symbol, extract_watchlist_name

EventEmitter = Callable[[str, str, dict], Awaitable[None]]


def _frame(x: float, y: float, width: float, layer: int | None = None) -> dict:
    frame = {"x": x, "y": y, "width": width}
    if layer:
        frame["layer"] = layer
    return frame


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Understanding", "Researching", "Executing", "Verifying", "Completed"]
    sequence = []
    for index, item in enumerate(objects):
        sequence.append({
            "id": f"reveal-{index}", "label": item.get("eyebrow", item["title"]),
            "atMs": index * 320, "state": states[min(index, len(states) - 1)], "objectIds": [item["id"]],
        })
    return {
        "schemaVersion": 1, "id": identifier, "mode": mode, "label": label,
        "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": objects, "sequence": sequence,
    }


class FinancialIntelligenceEngine:
    """Financial intelligence and controlled paper-trading operating layer for VYOM."""

    INTENTS = {
        "analyze_market", "watchlist_add", "watchlist_show", "portfolio_risk",
        "create_paper_trade_setup", "run_backtest", "market_briefing", "trade_postmortem",
    }

    def __init__(
        self,
        market_researcher: MarketResearcher,
        setup_builder: SetupBuilder,
        trade_manager: TradeManager,
        paper_broker: PaperBroker,
        backtest_engine: BacktestEngine,
        strategy_registry: StrategyRegistry,
        portfolio_store: PortfolioStore,
        watchlist_store: WatchlistStore,
        journal_store: JournalStore,
        alert_engine: AlertEngine,
        risk_rules: RiskRules,
    ) -> None:
        self.market_researcher = market_researcher
        self.setup_builder = setup_builder
        self.trade_manager = trade_manager
        self.paper_broker = paper_broker
        self.backtest_engine = backtest_engine
        self.strategy_registry = strategy_registry
        self.portfolio_store = portfolio_store
        self.watchlist_store = watchlist_store
        self.journal_store = journal_store
        self.alert_engine = alert_engine
        self.risk_rules = risk_rules
        self.backtest_report = BacktestReport()
        self._last_analysis: dict[str, MarketAnalysis] = {}

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        intent = profile.intent
        if intent == "analyze_market":
            return await self._analyze_market(task, emit)
        if intent == "watchlist_add":
            return await self._watchlist_add(task, emit)
        if intent == "watchlist_show":
            return await self._watchlist_show(task, emit)
        if intent == "portfolio_risk":
            return await self._portfolio_risk(task, emit)
        if intent == "create_paper_trade_setup":
            return await self._create_paper_trade_setup(task, emit)
        if intent == "run_backtest":
            return await self._run_backtest(task, emit)
        if intent == "market_briefing":
            return await self._market_briefing(task, emit)
        if intent == "trade_postmortem":
            return await self._trade_postmortem(task, emit)
        raise RuntimeError(f"Unsupported financial intent: {intent}")

    # -- Analysis ---------------------------------------------------------

    async def _analyze_market(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        symbol = extract_symbol(task.user_request)
        if not symbol:
            statement = "No instrument symbol was recognized in the request; try 'Analyze NVDA' or 'Analyze BTC'."
            obj = {"id": "unresolved", "type": "verified-result", "title": "Market analysis", "eyebrow": "Instrument not resolved", "tone": "attention", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
            return ExecutionResult(response=statement, structured_data={"resolved": False}, ui_composition=_composition(f"analyze-{task.id}", "brain-context", "Market analysis", statement, [obj]), evidence=[])

        await emit("market_data_requested", f"Requesting market data for {symbol}", {"symbol": symbol})
        analysis = await self.market_researcher.analyze(symbol, emit=emit)
        self._last_analysis[task.id] = analysis
        await emit("market_data_received", f"Received {analysis.quote.freshness.value} data for {symbol}", {"symbol": symbol, "provider": analysis.quote.provider, "freshness": analysis.quote.freshness.value})

        chart_object = {
            "id": "price-chart", "type": "price-chart", "title": f"{symbol} · {analysis.candles.timeframe}",
            "eyebrow": f"{analysis.quote.provider} · {analysis.quote.freshness.value}", "tone": "intelligence", "frame": _frame(4, 12, 48),
            "candles": [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close, c.volume] for c in analysis.candles.candles[-90:]],
            "indicators": {"sma_20": analysis.technical.sma_20, "sma_50": analysis.technical.sma_50, "rsi_14": analysis.technical.rsi_14},
        }
        regime_object = {
            "id": "regime", "type": "confidence-indicator", "title": "Market regime", "eyebrow": analysis.regime.regime.value,
            "tone": "intelligence", "frame": _frame(54, 12, 20), "score": analysis.regime.confidence, "label": "; ".join(analysis.regime.rationale) or analysis.regime.regime.value,
        }
        objects = [chart_object, regime_object]

        if analysis.thesis is not None:
            await emit("market_thesis_ready", f"{symbol} thesis ready ({analysis.thesis.direction.value})", {"thesis_id": analysis.thesis.id, "confidence": analysis.thesis.confidence})
            objects.append({
                "id": "thesis", "type": "verified-result", "title": f"{symbol} thesis", "eyebrow": f"{analysis.thesis.direction.value} · confidence {analysis.thesis.confidence}",
                "tone": "verified", "frame": _frame(4, 60, 48), "statement": analysis.thesis.thesis,
                "evidence": analysis.thesis.supporting_evidence[:5], "timestamp": analysis.thesis.data_timestamp.isoformat(),
            })
        else:
            objects.append({
                "id": "thesis-unavailable", "type": "verified-result", "title": f"{symbol} thesis", "eyebrow": "Not enough evidence",
                "tone": "attention", "frame": _frame(4, 60, 48), "statement": analysis.thesis_unavailable_reason or "Insufficient evidence for a thesis.",
                "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        if analysis.catalysts:
            objects.append({
                "id": "catalysts", "type": "comparison-table", "title": "Catalysts", "eyebrow": f"{len(analysis.catalysts)} found", "tone": "neutral",
                "frame": _frame(54, 60, 42), "headers": ["Category", "Description", "Source", "Confidence"],
                "rows": [[c.category, c.description[:80], c.source, c.confidence] for c in analysis.catalysts[:6]],
            })

        summary = (
            f"{symbol}: {analysis.quote.price} ({analysis.quote.provider}, {analysis.quote.freshness.value}). "
            f"Regime: {analysis.regime.regime.value} (confidence {analysis.regime.confidence}). "
            + (f"Thesis: {analysis.thesis.direction.value}, confidence {analysis.thesis.confidence}." if analysis.thesis else "No thesis: insufficient independent evidence.")
        )
        composition = _composition(f"analyze-{task.id}", "brain-context", f"Analysis: {symbol}", summary, objects)
        return ExecutionResult(
            response=summary, structured_data=analysis.model_dump(mode="json"),
            ui_composition=composition, evidence=analysis.citations or [f"provider:{analysis.quote.provider}"],
        )

    # -- Watchlist ----------------------------------------------------------

    async def _watchlist_add(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        symbol = extract_symbol(task.user_request)
        name = extract_watchlist_name(task.user_request)
        if not symbol:
            statement = "No instrument symbol was recognized to add to the watchlist."
            return ExecutionResult(response=statement, structured_data={"added": False}, evidence=[])

        watchlist = await self.watchlist_store.get_or_create(name)
        watchlist.add(WatchlistItem(instrument=Instrument(symbol=symbol), reason=f"Added via: {task.user_request[:120]}"))
        await self.watchlist_store.save(watchlist)

        statement = f"Added {symbol} to '{watchlist.name}' ({len(watchlist.items)} instrument(s))."
        obj = {"id": "watchlist", "type": "verified-result", "title": watchlist.name, "eyebrow": f"{len(watchlist.items)} instrument(s)", "tone": "verified", "frame": _frame(20, 20, 46), "statement": statement, "evidence": [f"watchlist_id:{watchlist.id}"], "timestamp": datetime.now(timezone.utc).isoformat()}
        composition = _composition(f"watchlist-add-{task.id}", "brain-context", "Watchlist", statement, [obj])
        return ExecutionResult(response=statement, structured_data=watchlist.model_dump(mode="json"), ui_composition=composition, evidence=[f"watchlist_id:{watchlist.id}"])

    async def _watchlist_show(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        name = extract_watchlist_name(task.user_request)
        watchlist = await self.watchlist_store.get_by_name(name)
        if watchlist is None or not watchlist.items:
            statement = f"'{name}' has no instruments yet."
            return ExecutionResult(response=statement, structured_data={"items": []}, evidence=[])

        rows = [[item.instrument.normalized_symbol(), item.reason or "-", ", ".join(item.tags) or "-"] for item in watchlist.items]
        obj = {"id": "watchlist-table", "type": "comparison-table", "title": watchlist.name, "eyebrow": f"{len(watchlist.items)} instrument(s)", "tone": "neutral", "frame": _frame(10, 14, 52), "headers": ["Symbol", "Reason", "Tags"], "rows": rows}
        summary = f"{watchlist.name}: {len(watchlist.items)} instrument(s)."
        composition = _composition(f"watchlist-show-{task.id}", "brain-context", watchlist.name, summary, [obj])
        return ExecutionResult(response=summary, structured_data=watchlist.model_dump(mode="json"), ui_composition=composition, evidence=[f"watchlist_id:{watchlist.id}"])

    # -- Portfolio risk -------------------------------------------------------

    async def _portfolio_risk(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        portfolios = await self.portfolio_store.list()
        if not portfolios:
            statement = "No portfolio has been entered yet. Add positions before requesting a risk read."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        portfolio = portfolios[0]

        pnl = compute_pnl(portfolio)
        exposure = compute_exposure(portfolio)
        concentration = herfindahl_concentration(exposure)
        report = evaluate_portfolio_risk(portfolio, self.risk_rules)

        tone = "verified" if report.passed else "attention"
        statement = (
            f"{portfolio.name}: total value {pnl.total_value:.2f} {portfolio.base_currency}, "
            f"exposure {report.total_exposure_pct:.1f}%, largest sector {report.largest_sector or 'n/a'} "
            f"({report.largest_sector_pct:.1f}%), concentration (HHI) {concentration}. "
            + ("Within configured risk limits." if report.passed else "Risk limits breached: " + "; ".join(report.reasons))
            + " (Using local-fixture simulated prices, not live market data.)"
        )
        objects = [
            {"id": "risk-summary", "type": "verified-result", "title": f"{portfolio.name} risk", "eyebrow": "Risk read (local-fixture data)", "tone": tone, "frame": _frame(10, 14, 44), "statement": statement, "evidence": [f"positions:{len(portfolio.positions)}"], "timestamp": datetime.now(timezone.utc).isoformat()},
            {"id": "exposure", "type": "comparison-table", "title": "Sector exposure", "eyebrow": "% of total value", "tone": "neutral", "frame": _frame(58, 14, 38), "headers": ["Sector", "% of portfolio"], "rows": [[sector, pct] for sector, pct in exposure.by_sector.items()] or [["Unclassified", exposure.unclassified_sector_value]]},
        ]
        composition = _composition(f"portfolio-risk-{task.id}", "brain-context", "Portfolio risk", statement, objects)
        return ExecutionResult(
            response=statement,
            structured_data={"pnl": pnl.model_dump(mode="json"), "exposure": exposure.model_dump(mode="json"), "risk": report.model_dump(mode="json")},
            ui_composition=composition, evidence=[f"portfolio_id:{portfolio.id}"],
        )

    # -- Paper trade setup ----------------------------------------------------

    async def _create_paper_trade_setup(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        symbol = extract_symbol(task.user_request)
        if not symbol:
            statement = "No instrument symbol was recognized for the paper trade setup."
            return ExecutionResult(response=statement, structured_data={"created": False}, evidence=[])

        analysis = self._last_analysis.get(task.id) or await self.market_researcher.analyze(symbol, emit=emit)
        direction = analysis.thesis.direction if analysis.thesis else TradeDirection.LONG
        setup = self.setup_builder.build(
            analysis.thesis or _fallback_thesis(symbol, direction, analysis), analysis.technical, current_price=analysis.quote.price,
        )
        await emit("trade_setup_created", f"Setup created for {symbol}", {"setup_id": setup.id, "direction": setup.direction.value})

        portfolio = await self.paper_broker.get_or_create_portfolio(starting_cash=self.risk_rules.starting_cash, base_currency=self.risk_rules.base_currency)
        risk_pct = extract_percentage(task.user_request, default=self.risk_rules.max_risk_per_trade_pct)

        await emit("risk_check_started", f"Checking risk for {symbol} setup", {"setup_id": setup.id})
        proposal = await self.trade_manager.propose(
            setup, portfolio, account_size=portfolio.total_value() or self.risk_rules.starting_cash, risk_percentage=risk_pct, approved=False,
        )
        if proposal.risk_decision.decision == RiskDecisionType.REJECT:
            await emit("risk_check_failed", "Risk check failed", {"reasons": proposal.risk_decision.reasons})
            await emit("trade_setup_rejected", f"Setup for {symbol} rejected by Risk Engine", {"reasons": proposal.risk_decision.reasons})
        else:
            await emit("risk_check_passed", f"Risk check {proposal.risk_decision.decision.value}", {"reasons": proposal.risk_decision.reasons})

        tone = "verified" if proposal.outcome != TradeProposalOutcome.REJECTED else "attention"
        statement = (
            f"PAPER setup for {symbol} ({setup.direction.value}): entry {setup.entry_zone}, stop {setup.stop}, "
            f"targets {setup.targets}, risk/reward {setup.risk_reward}. Risk Engine: {proposal.risk_decision.decision.value}. "
            + ("Rejected: " + "; ".join(proposal.risk_decision.reasons) if proposal.outcome == TradeProposalOutcome.REJECTED
               else "Requires explicit approval before a simulated order is placed (manual approval mode).")
        )
        obj = {
            "id": "setup", "type": "trade-setup", "title": f"{symbol} PAPER setup", "eyebrow": f"{setup.direction.value} · {proposal.risk_decision.decision.value}",
            "tone": tone, "frame": _frame(10, 16, 48), "label": "PAPER",
            "entryZone": setup.entry_zone, "stop": setup.stop, "targets": setup.targets, "riskReward": setup.risk_reward,
            "maxRisk": setup.max_risk, "confidence": setup.confidence, "invalidation": setup.invalidation,
            "dataTimestamp": analysis.quote.timestamp.isoformat(),
        }
        risk_obj = {
            "id": "risk", "type": "risk-panel", "title": "Risk check", "eyebrow": proposal.risk_decision.decision.value,
            "tone": tone, "frame": _frame(60, 16, 36), "reasons": proposal.risk_decision.reasons,
            "riskPctOfEquity": proposal.risk_decision.trade_check.risk_pct_of_equity,
            "positionSize": proposal.risk_decision.adjusted_position_size or proposal.sizing.position_size,
        }
        composition = _composition(f"setup-{task.id}", "brain-context", f"{symbol} setup", statement, [obj, risk_obj])
        return ExecutionResult(
            response=statement, structured_data=proposal.model_dump(mode="json"),
            ui_composition=composition, evidence=[f"setup_id:{setup.id}", f"risk_decision:{proposal.risk_decision.decision.value}"],
        )

    # -- Backtesting ----------------------------------------------------------

    async def _run_backtest(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        symbol = extract_symbol(task.user_request) or "SPY"
        strategies = await self.strategy_registry.list_all()
        if not strategies:
            statement = "No strategy is defined yet. Create a StrategySpec with entry/exit rules before backtesting."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        spec = strategies[0]

        await emit("backtest_started", f"Backtesting {spec.name} v{spec.version} on {symbol}", {"strategy": spec.name, "symbol": symbol})
        try:
            result = await self.backtest_engine.run(spec, symbol)
        except Exception as error:
            await emit("backtest_failed", str(error), {"strategy": spec.name})
            statement = f"Backtest failed: {error}"
            return ExecutionResult(response=statement, structured_data={"failed": True}, evidence=[])

        await emit("backtest_completed", f"Backtest complete: {result.metrics.trade_count} trade(s)", {"backtest_id": result.id})
        summary = self.backtest_report.summarize(result)
        obj = {
            "id": "backtest", "type": "equity-curve", "title": f"{spec.name} v{spec.version} on {symbol}", "eyebrow": f"{result.metrics.trade_count} trade(s)",
            "tone": "verified", "frame": _frame(8, 14, 52), "equityCurve": self.backtest_report.equity_curve_rows(result),
            "metrics": result.metrics.model_dump(mode="json"), "integrityNotes": result.integrity_notes,
        }
        composition = _composition(f"backtest-{task.id}", "brain-context", "Backtest", summary, [obj])
        return ExecutionResult(response=summary, structured_data=result.model_dump(mode="json"), ui_composition=composition, evidence=[f"backtest_id:{result.id}"])

    # -- Briefing / journal ----------------------------------------------------

    async def _market_briefing(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        portfolios = await self.portfolio_store.list(kind=PortfolioKind.PAPER.value)
        watchlists = await self.watchlist_store.list()
        open_positions = sum(len(p.positions) for p in portfolios)
        watch_symbols = sorted({item.instrument.normalized_symbol() for w in watchlists for item in w.items})

        summary = (
            f"Market briefing: {len(watch_symbols)} watchlist instrument(s), {open_positions} open PAPER position(s) "
            f"across {len(portfolios)} paper portfolio(s)."
        )
        await emit("briefing_generated", summary, {"watchlist_count": len(watch_symbols), "open_positions": open_positions})
        obj = {"id": "briefing", "type": "verified-result", "title": "Market briefing", "eyebrow": "PAPER portfolio + watchlist", "tone": "neutral", "frame": _frame(14, 16, 48), "statement": summary, "evidence": [], "timestamp": datetime.now(timezone.utc).isoformat()}
        composition = _composition(f"briefing-{task.id}", "brain-context", "Market briefing", summary, [obj])
        return ExecutionResult(response=summary, structured_data={"watchlist": watch_symbols, "open_positions": open_positions}, ui_composition=composition, evidence=[])

    async def _trade_postmortem(self, task: Task, emit: EventEmitter) -> ExecutionResult:
        entries = await self.journal_store.list()
        closed = [e for e in entries if e.result in {TradeResult.LOSS, TradeResult.WIN, TradeResult.BREAKEVEN}]
        if not closed:
            statement = "No closed PAPER trades are in the journal yet."
            return ExecutionResult(response=statement, structured_data={"available": False}, evidence=[])
        entry = closed[0]

        process_note = (
            "Process appears sound (evidence-backed thesis on record)." if entry.sources
            else "No sourced thesis is on record for this trade; process cannot be fully assessed."
        )
        statement = (
            f"{entry.symbol} {entry.direction.value} PAPER trade: entry {entry.entry_price}, exit {entry.exit_price}, "
            f"P&L {entry.pnl}, result {entry.result.value}. {process_note}"
        )
        obj = {"id": "postmortem", "type": "verified-result", "title": f"{entry.symbol} post-mortem", "eyebrow": entry.result.value, "tone": "verified" if entry.result == TradeResult.WIN else "attention", "frame": _frame(14, 16, 48), "statement": statement, "evidence": entry.sources, "timestamp": datetime.now(timezone.utc).isoformat()}
        composition = _composition(f"postmortem-{task.id}", "brain-context", "Trade post-mortem", statement, [obj])
        return ExecutionResult(response=statement, structured_data=entry.model_dump(mode="json"), ui_composition=composition, evidence=[f"journal_id:{entry.id}"])


def _fallback_thesis(symbol: str, direction: TradeDirection, analysis: MarketAnalysis):
    from app.trading.schemas import TradeThesis

    return TradeThesis(
        instrument=symbol, direction=direction, time_horizon="swing (days-weeks)",
        thesis=f"No independently-evidenced thesis was available for {symbol}; setup uses technical structure only.",
        invalidation="Reassess once catalyst/research evidence is available.",
        confidence=0.2, data_timestamp=analysis.technical.as_of,
    )


Phase10Engine = FinancialIntelligenceEngine
__all__ = ["FinancialIntelligenceEngine", "Phase10Engine"]
