from __future__ import annotations

from pydantic import BaseModel, Field


class PositionSizingInput(BaseModel):
    account_size: float
    risk_percentage: float = Field(gt=0, le=100)
    entry: float
    stop: float
    lot_size: float = 1.0        # minimum tradable increment (e.g. 1 share, 0.0001 BTC)
    max_position_value: float | None = None  # optional hard cap (e.g. available cash)


class PositionSizingResult(BaseModel):
    risk_amount: float
    distance_to_stop: float
    position_size: float
    estimated_loss_at_stop: float
    position_value: float
    assumptions: dict[str, float]


class InvalidStopError(ValueError):
    pass


def calculate_position_size(inputs: PositionSizingInput) -> PositionSizingResult:
    """Deterministic risk-based sizing: risk_amount = account_size *
    risk_percentage; position_size = risk_amount / distance_to_stop,
    rounded down to `lot_size`. Assumptions are always returned alongside
    the result (rule 13) so the caller can display them."""
    distance_to_stop = abs(inputs.entry - inputs.stop)
    if distance_to_stop <= 0:
        raise InvalidStopError("Stop must differ from entry to compute a risk distance")

    risk_amount = inputs.account_size * (inputs.risk_percentage / 100.0)
    raw_size = risk_amount / distance_to_stop
    lots = int(raw_size / inputs.lot_size) if inputs.lot_size > 0 else raw_size
    position_size = round(lots * inputs.lot_size, 8)

    position_value = position_size * inputs.entry
    if inputs.max_position_value is not None and position_value > inputs.max_position_value:
        capped_size = inputs.max_position_value / inputs.entry
        lots = int(capped_size / inputs.lot_size) if inputs.lot_size > 0 else capped_size
        position_size = round(lots * inputs.lot_size, 8)
        position_value = position_size * inputs.entry

    estimated_loss_at_stop = position_size * distance_to_stop

    return PositionSizingResult(
        risk_amount=round(risk_amount, 4),
        distance_to_stop=round(distance_to_stop, 6),
        position_size=position_size,
        estimated_loss_at_stop=round(estimated_loss_at_stop, 4),
        position_value=round(position_value, 4),
        assumptions={
            "account_size": inputs.account_size,
            "risk_percentage": inputs.risk_percentage,
            "entry": inputs.entry,
            "stop": inputs.stop,
            "lot_size": inputs.lot_size,
        },
    )
