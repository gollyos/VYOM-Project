from __future__ import annotations

from dataclasses import dataclass, field

from app.finance.metrics import compute_drawdown
from app.finance.schemas import Portfolio
from app.market_data.schemas import Quote
from app.market_intelligence.schemas import TechnicalSnapshot

from .schemas import AlertCondition, AlertConditionType


@dataclass
class AlertContext:
    """Everything a condition evaluator might need — deterministic
    inputs only, no model call (rule 40)."""

    quote: Quote | None = None
    previous_close: float | None = None
    technical: TechnicalSnapshot | None = None
    portfolio: Portfolio | None = None
    equity_curve: list[float] = field(default_factory=list)
    news_claims: list[str] = field(default_factory=list)


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == "gte":
        return value >= threshold
    if operator == "lte":
        return value <= threshold
    if operator == "gt":
        return value > threshold
    if operator == "lt":
        return value < threshold
    return False


class ConditionEvaluator:
    def evaluate(self, condition: AlertCondition, context: AlertContext) -> bool:
        if condition.type == AlertConditionType.PRICE_ABOVE:
            return context.quote is not None and condition.threshold is not None and context.quote.price > condition.threshold
        if condition.type == AlertConditionType.PRICE_BELOW:
            return context.quote is not None and condition.threshold is not None and context.quote.price < condition.threshold
        if condition.type == AlertConditionType.PERCENTAGE_MOVE:
            if context.quote is None or condition.threshold is None or context.quote.change_pct is None:
                return False
            return abs(context.quote.change_pct) >= condition.threshold
        if condition.type == AlertConditionType.VOLUME_CONDITION:
            if context.quote is None or condition.threshold is None or context.quote.volume is None:
                return False
            return context.quote.volume >= condition.threshold
        if condition.type == AlertConditionType.TECHNICAL_CONDITION:
            if context.technical is None or condition.field is None or condition.threshold is None:
                return False
            value = getattr(context.technical, condition.field, None)
            if value is None:
                return False
            return _compare(value, condition.operator, condition.threshold)
        if condition.type == AlertConditionType.PORTFOLIO_DRAWDOWN:
            if not context.equity_curve or condition.threshold is None:
                return False
            drawdown = compute_drawdown(context.equity_curve)
            return drawdown is not None and drawdown.current_drawdown_pct >= condition.threshold
        if condition.type == AlertConditionType.PAPER_POSITION_STOP:
            if context.portfolio is None or condition.symbol is None or condition.threshold is None:
                return False
            position = context.portfolio.find_position(condition.symbol)
            return position is not None and position.current_price is not None and position.current_price <= condition.threshold
        if condition.type == AlertConditionType.PAPER_TARGET:
            if context.portfolio is None or condition.symbol is None or condition.threshold is None:
                return False
            position = context.portfolio.find_position(condition.symbol)
            return position is not None and position.current_price is not None and position.current_price >= condition.threshold
        if condition.type == AlertConditionType.NEWS_CONDITION:
            if condition.keyword is None:
                return False
            keyword = condition.keyword.lower()
            return any(keyword in claim.lower() for claim in context.news_claims)
        return False
