from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.finance.schemas import Instrument, Portfolio, PortfolioKind, Position, Watchlist, WatchlistItem

router = APIRouter(prefix="/api/finance", tags=["finance"])


@router.get("/portfolios", response_model=list[Portfolio])
async def list_portfolios(request: Request, kind: str | None = None) -> list[Portfolio]:
    return await request.app.state.portfolio_store.list(kind=kind)


@router.post("/portfolios", response_model=Portfolio)
async def create_portfolio(portfolio: Portfolio, request: Request) -> Portfolio:
    return await request.app.state.portfolio_store.save(portfolio)


@router.get("/portfolios/{portfolio_id}", response_model=Portfolio)
async def get_portfolio(portfolio_id: str, request: Request) -> Portfolio:
    portfolio = await request.app.state.portfolio_store.get(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return portfolio


@router.post("/portfolios/{portfolio_id}/positions", response_model=Portfolio)
async def add_position(portfolio_id: str, position: Position, request: Request) -> Portfolio:
    portfolio_service = request.app.state.portfolio_service
    portfolio = await request.app.state.portfolio_store.get(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    return await portfolio_service.add_position(portfolio, position)


@router.get("/portfolios/{portfolio_id}/analytics")
async def portfolio_analytics(portfolio_id: str, request: Request, reprice: bool = True) -> dict:
    portfolio_service = request.app.state.portfolio_service
    portfolio = await request.app.state.portfolio_store.get(portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    if reprice:
        portfolio = await portfolio_service.reprice(portfolio)
        await request.app.state.portfolio_store.save(portfolio)
    return await portfolio_service.analytics(portfolio)


@router.get("/watchlists", response_model=list[Watchlist])
async def list_watchlists(request: Request) -> list[Watchlist]:
    return await request.app.state.watchlist_store.list()


@router.get("/watchlists/{name}", response_model=Watchlist)
async def get_watchlist(name: str, request: Request) -> Watchlist:
    watchlist = await request.app.state.watchlist_store.get_by_name(name)
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return watchlist


@router.post("/watchlists/{name}/items", response_model=Watchlist)
async def add_watchlist_item(name: str, symbol: str, reason: str | None, request: Request) -> Watchlist:
    watchlist = await request.app.state.watchlist_store.get_or_create(name)
    watchlist.add(WatchlistItem(instrument=Instrument(symbol=symbol), reason=reason))
    return await request.app.state.watchlist_store.save(watchlist)
