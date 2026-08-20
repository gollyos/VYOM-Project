from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class RiskRules:
    """Immutable risk limits loaded from `config/risk.yaml` (rule 14/63).
    Nothing in the runtime constructs this from scattered constants, and
    nothing in the runtime is able to raise these values at runtime — only
    editing the YAML file (a normal, auditable user/config change) can."""

    starting_cash: float
    base_currency: str
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    max_total_exposure_pct: float
    max_single_symbol_exposure_pct: float
    max_sector_exposure_pct: float
    max_correlated_exposure_pct: float
    max_drawdown_pct: float
    default_slippage_bps: float
    default_fee_bps: float
    default_approval_mode: str
    pause_on_daily_loss_breach: bool
    pause_on_drawdown_breach: bool
    pause_on_stale_data: bool
    pause_on_strategy_anomaly: bool

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "RiskRules":
        account = config.get("default_paper_account", {})
        limits = config.get("limits", {})
        execution = config.get("execution_assumptions", {})
        paper = config.get("paper_trading", {})
        kill_switch = config.get("kill_switch", {})
        return cls(
            starting_cash=float(account.get("starting_cash", 100_000.0)),
            base_currency=str(account.get("base_currency", "USD")),
            max_risk_per_trade_pct=float(limits.get("max_risk_per_trade_pct", 1.0)),
            max_daily_loss_pct=float(limits.get("max_daily_loss_pct", 3.0)),
            max_open_positions=int(limits.get("max_open_positions", 8)),
            max_total_exposure_pct=float(limits.get("max_total_exposure_pct", 100.0)),
            max_single_symbol_exposure_pct=float(limits.get("max_single_symbol_exposure_pct", 20.0)),
            max_sector_exposure_pct=float(limits.get("max_sector_exposure_pct", 35.0)),
            max_correlated_exposure_pct=float(limits.get("max_correlated_exposure_pct", 45.0)),
            max_drawdown_pct=float(limits.get("max_drawdown_pct", 15.0)),
            default_slippage_bps=float(execution.get("default_slippage_bps", 5)),
            default_fee_bps=float(execution.get("default_fee_bps", 2)),
            default_approval_mode=str(paper.get("default_approval_mode", "manual")),
            pause_on_daily_loss_breach=bool(kill_switch.get("pause_on_daily_loss_breach", True)),
            pause_on_drawdown_breach=bool(kill_switch.get("pause_on_drawdown_breach", True)),
            pause_on_stale_data=bool(kill_switch.get("pause_on_stale_data", True)),
            pause_on_strategy_anomaly=bool(kill_switch.get("pause_on_strategy_anomaly", True)),
        )

    @classmethod
    def from_yaml(cls, path: Path) -> "RiskRules":
        return cls.from_config(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
