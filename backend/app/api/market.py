from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.market import MarketOut, MoversOut
from app.services.market import build_market_indicators
from app.services.movers import build_movers

router = APIRouter(prefix="/market")


@router.get("", response_model=MarketOut)
def get_market(refresh: bool = False) -> MarketOut:
    """External market-context indicators (sentiment/macro), cached 30 min.
    `refresh=true` bypasses the cache. Context only — never a buy/sell signal."""
    return build_market_indicators(refresh=refresh)


@router.get("/movers", response_model=MoversOut)
def get_movers(refresh: bool = False, db: Session = Depends(get_db)) -> MoversOut:
    """Biggest daily movers among the portfolio's own holdings (excl. renda
    fixa): 6 largest gainers + 6 largest losers per chip filter, cached 15 min.
    Display only — never a buy/sell signal."""
    return build_movers(db, refresh=refresh)
