from __future__ import annotations

from app.trading.schemas import TradeDirection, TradeThesis

from .schemas import CatalystRecord, MarketRegime, RegimeAssessment, TechnicalSnapshot, utc_now
from .sentiment import SentimentAssessment


class InsufficientEvidenceError(ValueError):
    """Raised when a thesis would rest on price movement alone (rule 11)."""


class ThesisBuilder:
    def build(
        self,
        instrument: str,
        direction: TradeDirection,
        *,
        time_horizon: str,
        snapshot: TechnicalSnapshot,
        regime: RegimeAssessment,
        catalysts: list[CatalystRecord],
        sentiment: SentimentAssessment | None,
        research_gaps: list[str],
    ) -> TradeThesis:
        supporting: list[str] = []
        contradicting: list[str] = []

        technical_confluences = 0
        if regime.regime in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
            aligned = (direction == TradeDirection.LONG and regime.regime == MarketRegime.TRENDING_UP) or \
                      (direction == TradeDirection.SHORT and regime.regime == MarketRegime.TRENDING_DOWN)
            if aligned:
                supporting.append(f"Regime is {regime.regime.value} ({'; '.join(regime.rationale)})")
                technical_confluences += 1
            else:
                contradicting.append(f"Regime is {regime.regime.value}, which does not confirm a {direction.value} thesis")

        if snapshot.rsi_14 is not None:
            if direction == TradeDirection.LONG and snapshot.rsi_14 < 30:
                supporting.append(f"RSI-14 ({snapshot.rsi_14}) suggests oversold conditions")
                technical_confluences += 1
            elif direction == TradeDirection.SHORT and snapshot.rsi_14 > 70:
                supporting.append(f"RSI-14 ({snapshot.rsi_14}) suggests overbought conditions")
                technical_confluences += 1

        for catalyst in catalysts:
            if catalyst.confidence >= 0.4:
                supporting.append(f"[{catalyst.category}] {catalyst.description} (source: {catalyst.source})")

        if sentiment is not None:
            if (direction == TradeDirection.LONG and sentiment.label == "positive") or \
               (direction == TradeDirection.SHORT and sentiment.label == "negative"):
                supporting.append(f"Sentiment heuristic reads {sentiment.label} ({sentiment.rationale})")
            elif (direction == TradeDirection.LONG and sentiment.label == "negative") or \
                 (direction == TradeDirection.SHORT and sentiment.label == "positive"):
                contradicting.append(f"Sentiment heuristic reads {sentiment.label}, against the proposed direction")

        for gap in research_gaps:
            contradicting.append(f"Research gap: no verified source for '{gap}'")

        # Rule 11: never build a thesis from price movement alone. Require at
        # least one catalyst/research-backed item, or >=2 technical
        # confluences beyond a single moving-average read.
        catalyst_backed = any("source:" in item for item in supporting)
        if not catalyst_backed and technical_confluences < 2:
            raise InsufficientEvidenceError(
                "Not enough independent evidence to build a thesis: found only "
                f"{technical_confluences} technical confluence(s) and no catalyst/research support. "
                "A thesis requires more than price movement alone."
            )

        confidence = min(0.9, 0.3 + 0.12 * len(supporting) - 0.08 * len(contradicting))
        confidence = max(0.1, round(confidence, 3))

        invalidation = (
            f"Close below {snapshot.support_candidates[0]}" if direction == TradeDirection.LONG and snapshot.support_candidates
            else f"Close above {snapshot.resistance_candidates[0]}" if direction == TradeDirection.SHORT and snapshot.resistance_candidates
            else "Thesis invalidated if regime or catalyst evidence reverses"
        )

        return TradeThesis(
            instrument=instrument.upper(),
            direction=direction,
            time_horizon=time_horizon,
            thesis=(
                f"{instrument.upper()} {direction.value} thesis based on {regime.regime.value} regime "
                f"and {len(catalysts)} researched catalyst(s)."
            ),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            catalysts=[c.description for c in catalysts],
            risks=[item for item in contradicting],
            invalidation=invalidation,
            confidence=confidence,
            data_timestamp=snapshot.as_of,
            created_at=utc_now(),
        )
