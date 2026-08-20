from __future__ import annotations

from app.market_data.schemas import Candle
from app.market_intelligence.technical_analysis import atr, ema, macd, rsi, sma

from .schemas import IndicatorRule, RuleOperator, StrategySpec


def compute_fields(candles: list[Candle], index: int) -> dict[str, float]:
    """Computes every indicator field a rule can reference, using only
    `candles[0:index+1]` — data at or before the current bar. This is the
    lookahead boundary: nothing beyond `index` is ever visible here
    (docs/BACKTESTING.md)."""
    window = candles[: index + 1]
    closes = [c.close for c in window]
    current = window[-1]
    fields: dict[str, float] = {
        "close": current.close, "open": current.open, "high": current.high,
        "low": current.low, "volume": current.volume,
    }
    if (value := sma(closes, 20)) is not None:
        fields["sma_20"] = value
    if (value := sma(closes, 50)) is not None:
        fields["sma_50"] = value
    if (value := sma(closes, 200)) is not None:
        fields["sma_200"] = value
    if (value := ema(closes, 12)) is not None:
        fields["ema_12"] = value
    if (value := ema(closes, 26)) is not None:
        fields["ema_26"] = value
    if (value := rsi(closes, 14)) is not None:
        fields["rsi_14"] = value
    if (value := atr(window, 14)) is not None:
        fields["atr"] = value
    macd_result = macd(closes)
    if macd_result is not None:
        fields["macd"], fields["macd_signal"], fields["macd_histogram"] = macd_result
    return fields


class StrategyEvaluator:
    """Evaluates a `StrategySpec`'s structured entry/exit/filter rules
    against a deterministic field snapshot. There is no code path here that
    lets a model decide entry/exit on vibes (rule 24)."""

    def evaluate_rule(self, rule: IndicatorRule, fields: dict[str, float], prev_fields: dict[str, float] | None) -> bool:
        if rule.field not in fields:
            return False
        current_value = fields[rule.field]
        target = fields.get(rule.compare_field) if rule.compare_field else rule.value
        if target is None:
            return False

        if rule.operator == RuleOperator.GT:
            return current_value > target
        if rule.operator == RuleOperator.GTE:
            return current_value >= target
        if rule.operator == RuleOperator.LT:
            return current_value < target
        if rule.operator == RuleOperator.LTE:
            return current_value <= target
        if rule.operator in (RuleOperator.CROSSES_ABOVE, RuleOperator.CROSSES_BELOW):
            if prev_fields is None or rule.field not in prev_fields:
                return False
            prev_value = prev_fields[rule.field]
            prev_target = prev_fields.get(rule.compare_field) if rule.compare_field else rule.value
            if prev_target is None:
                return False
            if rule.operator == RuleOperator.CROSSES_ABOVE:
                return prev_value <= prev_target and current_value > target
            return prev_value >= prev_target and current_value < target
        return False

    def evaluate_all(self, rules: list[IndicatorRule], fields: dict[str, float], prev_fields: dict[str, float] | None) -> bool:
        if not rules:
            return False
        return all(self.evaluate_rule(rule, fields, prev_fields) for rule in rules)

    def should_enter(self, spec: StrategySpec, fields: dict[str, float], prev_fields: dict[str, float] | None) -> bool:
        if spec.filters and not self.evaluate_all(spec.filters, fields, prev_fields):
            return False
        return self.evaluate_all(spec.entry_rules, fields, prev_fields)

    def should_exit(self, spec: StrategySpec, fields: dict[str, float], prev_fields: dict[str, float] | None) -> bool:
        return self.evaluate_all(spec.exit_rules, fields, prev_fields)
