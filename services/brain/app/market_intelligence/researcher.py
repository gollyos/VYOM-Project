from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.market_data.candles import CandleService
from app.market_data.quotes import QuoteService
from app.market_data.schemas import CandleSeries, Quote
from app.research.schemas import ResearchResult
from app.trading.schemas import TradeDirection, TradeThesis

from .catalyst_analysis import CatalystResearcher
from .regime import RegimeClassifier
from .schemas import CatalystRecord, MarketRegime, RegimeAssessment, SentimentAssessment, TechnicalSnapshot, utc_now
from .sentiment import SentimentAnalyzer
from .technical_analysis import TechnicalAnalysisEngine
from .thesis_builder import InsufficientEvidenceError, ThesisBuilder

EmitFn = Callable[[str, str, dict[str, Any]], Awaitable[None]]


class MarketAnalysis(BaseModel):
    instrument: str
    quote: Quote
    candles: CandleSeries
    technical: TechnicalSnapshot
    regime: RegimeAssessment
    catalysts: list[CatalystRecord] = Field(default_factory=list)
    sentiment: SentimentAssessment | None = None
    research_gaps: list[str] = Field(default_factory=list)
    thesis: TradeThesis | None = None
    thesis_unavailable_reason: str | None = None
    citations: list[str] = Field(default_factory=list)
    generated_at: Any = Field(default_factory=utc_now)


class MarketResearcher:
    """Orchestrates the full analysis flow (rule 7):
    instrument resolution -> fresh market data -> historical context ->
    relevant research/news -> technical structure -> catalysts -> risks ->
    thesis -> evidence. Facts (quote/candles/technical) are kept separate
    from analysis/inference (regime/sentiment/thesis) in the result shape."""

    def __init__(
        self,
        quote_service: QuoteService,
        candle_service: CandleService,
        technical_engine: TechnicalAnalysisEngine,
        regime_classifier: RegimeClassifier,
        catalyst_researcher: CatalystResearcher,
        sentiment_analyzer: SentimentAnalyzer,
        thesis_builder: ThesisBuilder,
    ):
        self.quote_service = quote_service
        self.candle_service = candle_service
        self.technical_engine = technical_engine
        self.regime_classifier = regime_classifier
        self.catalyst_researcher = catalyst_researcher
        self.sentiment_analyzer = sentiment_analyzer
        self.thesis_builder = thesis_builder

    async def analyze(
        self,
        symbol: str,
        *,
        timeframe: str = "1d",
        lookback: int = 200,
        time_horizon: str = "swing (days-weeks)",
        emit: EmitFn | None = None,
    ) -> MarketAnalysis:
        symbol = symbol.upper()

        quote = await self.quote_service.get_quote(symbol)
        candle_series = await self.candle_service.get_candles(symbol, timeframe, lookback)

        technical = self.technical_engine.analyze(symbol, timeframe, candle_series.candles)
        regime = self.regime_classifier.classify(technical)

        catalysts, research_result = await self.catalyst_researcher.research(symbol, emit=emit)
        sentiment = self.sentiment_analyzer.analyze(research_result.claims)

        direction = TradeDirection.LONG if regime.regime != MarketRegime.TRENDING_DOWN else TradeDirection.SHORT

        thesis: TradeThesis | None = None
        thesis_unavailable_reason: str | None = None
        try:
            thesis = self.thesis_builder.build(
                symbol, direction, time_horizon=time_horizon, snapshot=technical, regime=regime,
                catalysts=catalysts, sentiment=sentiment, research_gaps=research_result.gaps,
            )
        except InsufficientEvidenceError as error:
            thesis_unavailable_reason = str(error)

        return MarketAnalysis(
            instrument=symbol, quote=quote, candles=candle_series, technical=technical, regime=regime,
            catalysts=catalysts, sentiment=sentiment, research_gaps=research_result.gaps,
            thesis=thesis, thesis_unavailable_reason=thesis_unavailable_reason,
            citations=research_result.citations,
        )
