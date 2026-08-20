from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.backtesting.engine import BacktestResult
from app.backtesting.strategy import StrategyValidationError
from app.strategies.schemas import StrategySpec

router = APIRouter(prefix="/api/backtesting", tags=["backtesting"])


@router.post("/run", response_model=BacktestResult)
async def run_backtest(
    strategy_name: str,
    strategy_version: str,
    symbol: str,
    request: Request,
    initial_capital: float = 100_000.0,
    fees_bps: float = 2.0,
    slippage_bps: float = 5.0,
) -> BacktestResult:
    spec = await request.app.state.strategy_registry.get(strategy_name, strategy_version)
    if spec is None:
        raise HTTPException(status_code=404, detail="Strategy version not found")
    try:
        return await request.app.state.backtest_engine.run(
            spec, symbol, initial_capital=initial_capital, fees_bps=fees_bps, slippage_bps=slippage_bps,
        )
    except StrategyValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/results", response_model=list[BacktestResult])
async def list_results(request: Request, strategy_name: str | None = None) -> list[BacktestResult]:
    return await request.app.state.backtest_engine.list_results(strategy_name)


@router.post("/strategies", response_model=StrategySpec)
async def create_strategy(spec: StrategySpec, request: Request) -> StrategySpec:
    try:
        return await request.app.state.strategy_registry.create(spec)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/strategies", response_model=list[StrategySpec])
async def list_strategies(request: Request) -> list[StrategySpec]:
    return await request.app.state.strategy_registry.list_all()
