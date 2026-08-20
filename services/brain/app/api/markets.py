from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.market_data.schemas import CandleSeries, Fundamentals, Quote
from app.market_intelligence.researcher import MarketAnalysis

router = APIRouter(prefix="/api/markets", tags=["markets"])


@router.get("/quote/{symbol}", response_model=Quote)
async def get_quote(symbol: str, request: Request) -> Quote:
    try:
        return await request.app.state.quote_service.get_quote(symbol)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/candles/{symbol}", response_model=CandleSeries)
async def get_candles(symbol: str, request: Request, timeframe: str = "1d", lookback: int = 90) -> CandleSeries:
    try:
        return await request.app.state.candle_service.get_candles(symbol, timeframe, lookback)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/fundamentals/{symbol}", response_model=Fundamentals)
async def get_fundamentals(symbol: str, request: Request) -> Fundamentals:
    try:
        return await request.app.state.fundamentals_service.get_fundamentals(symbol)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/analyze/{symbol}", response_model=MarketAnalysis)
async def analyze(symbol: str, request: Request) -> MarketAnalysis:
    return await request.app.state.market_researcher.analyze(symbol)
