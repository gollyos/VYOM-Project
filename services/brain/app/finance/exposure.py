from __future__ import annotations

from pydantic import BaseModel, Field

from .schemas import Portfolio


class ExposureBreakdown(BaseModel):
    total_value: float
    by_instrument: dict[str, float] = Field(default_factory=dict)      # symbol -> % of total_value
    by_sector: dict[str, float] = Field(default_factory=dict)          # sector -> % of total_value
    largest_position_pct: float = 0.0
    largest_position_symbol: str | None = None
    unclassified_sector_value: float = 0.0


def compute_exposure(portfolio: Portfolio) -> ExposureBreakdown:
    total_value = portfolio.total_value()
    breakdown = ExposureBreakdown(total_value=total_value)
    if total_value <= 0:
        return breakdown

    by_instrument: dict[str, float] = {}
    by_sector: dict[str, float] = {}
    unclassified = 0.0
    largest_pct, largest_symbol = 0.0, None

    for position in portfolio.positions:
        value = position.market_value if position.market_value is not None else position.cost_basis
        pct = round((value / total_value) * 100, 4)
        symbol = position.instrument.normalized_symbol()
        by_instrument[symbol] = by_instrument.get(symbol, 0.0) + pct
        if pct > largest_pct:
            largest_pct, largest_symbol = pct, symbol
        sector = position.instrument.sector
        if sector:
            by_sector[sector] = by_sector.get(sector, 0.0) + pct
        else:
            unclassified += pct

    breakdown.by_instrument = by_instrument
    breakdown.by_sector = by_sector
    breakdown.largest_position_pct = largest_pct
    breakdown.largest_position_symbol = largest_symbol
    breakdown.unclassified_sector_value = round(unclassified, 4)
    return breakdown


def herfindahl_concentration(breakdown: ExposureBreakdown) -> float:
    """Herfindahl-Hirschman-style concentration index (0-1) over instrument
    weights; higher means more concentrated in fewer positions."""
    if not breakdown.by_instrument:
        return 0.0
    return round(sum((weight / 100) ** 2 for weight in breakdown.by_instrument.values()), 4)
