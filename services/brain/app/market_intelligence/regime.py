from __future__ import annotations

from .schemas import MarketRegime, RegimeAssessment, TechnicalSnapshot, utc_now


class RegimeClassifier:
    """Transparent rule-based regime classification (rule 9). Confidence is
    always < 1.0 — a regime label is never presented as certainty."""

    def classify(self, snapshot: TechnicalSnapshot) -> RegimeAssessment:
        rationale: list[str] = []

        if snapshot.volatility_pct is not None and snapshot.volatility_pct >= 3.5:
            rationale.append(f"Daily volatility {snapshot.volatility_pct}% is elevated")
            return RegimeAssessment(regime=MarketRegime.HIGH_VOLATILITY, confidence=0.6, rationale=rationale)
        if snapshot.volatility_pct is not None and snapshot.volatility_pct <= 0.5:
            rationale.append(f"Daily volatility {snapshot.volatility_pct}% is compressed")
            return RegimeAssessment(regime=MarketRegime.LOW_VOLATILITY, confidence=0.55, rationale=rationale)

        if snapshot.sma_20 is not None and snapshot.sma_50 is not None:
            if snapshot.sma_20 > snapshot.sma_50 * 1.01:
                rationale.append("SMA-20 is meaningfully above SMA-50")
                if snapshot.rsi_14 is not None and snapshot.rsi_14 > 55:
                    rationale.append(f"RSI-14 ({snapshot.rsi_14}) confirms upward momentum")
                    return RegimeAssessment(regime=MarketRegime.TRENDING_UP, confidence=0.65, rationale=rationale)
                return RegimeAssessment(regime=MarketRegime.TRENDING_UP, confidence=0.5, rationale=rationale)
            if snapshot.sma_20 < snapshot.sma_50 * 0.99:
                rationale.append("SMA-20 is meaningfully below SMA-50")
                if snapshot.rsi_14 is not None and snapshot.rsi_14 < 45:
                    rationale.append(f"RSI-14 ({snapshot.rsi_14}) confirms downward momentum")
                    return RegimeAssessment(regime=MarketRegime.TRENDING_DOWN, confidence=0.65, rationale=rationale)
                return RegimeAssessment(regime=MarketRegime.TRENDING_DOWN, confidence=0.5, rationale=rationale)
            rationale.append("SMA-20 and SMA-50 are close together")
            return RegimeAssessment(regime=MarketRegime.RANGE, confidence=0.5, rationale=rationale)

        rationale.append("Insufficient history for a moving-average based regime read")
        return RegimeAssessment(regime=MarketRegime.UNCERTAIN, confidence=0.2, rationale=rationale)
