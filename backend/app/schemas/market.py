"""Schemas for the Mercado section — external context indicators.

These are context numbers (sentiment/macro), never buy/sell signals. Each
indicator fails independently: a dead source yields a null value with
stale=True, the rest still render.
"""

from datetime import date as date_type
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class FngEntry(BaseModel):
    value: int | None = None
    classification: str | None = None
    date: date_type | None = None


class Fng(BaseModel):
    today: FngEntry | None = None
    yesterday: FngEntry | None = None
    last_week: FngEntry | None = None
    source: str = "alternative.me"
    stale: bool = False


class Indicator(BaseModel):
    key: str
    label: str
    value: Decimal | None = None
    unit: str | None = None
    # Direction-only change vs the previous close (neutral; no semantic color):
    # change is absolute, change_pct is fractional. None when unavailable
    # without an extra API call (e.g. BTC dominance).
    change: Decimal | None = None
    change_pct: Decimal | None = None
    # Spot BTC price in USD + its real 24h change, shown inside the BTC
    # dominance card (best-effort; the card still renders if only the price is
    # missing). The 24h change is the one place semantic color is used.
    btc_price_usd: Decimal | None = None
    btc_change_pct: Decimal | None = None
    as_of: date_type | None = None
    source: str
    stale: bool = False


class Mayer(BaseModel):
    """Mayer Multiple = current BTC price / 200-day moving average, with the
    components and the position of today's value within its historical range
    (percentile + min/max). Not classified as cheap/expensive."""

    value: Decimal | None = None
    price: Decimal | None = None
    ma200: Decimal | None = None
    min: Decimal | None = None
    max: Decimal | None = None
    percentile: Decimal | None = None  # 0..1 position of today within history
    years: int | None = None
    source: str = "binance"
    as_of: date_type | None = None
    stale: bool = False


class MarketOut(BaseModel):
    fng: Fng
    btc_dominance: Indicator
    mayer: Mayer
    ibov: Indicator
    sp500: Indicator
    vix: Indicator
    dxy: Indicator
    treasury_3m: Indicator
    treasury_10y: Indicator
    fetched_at: datetime
    warnings: list[str] = []


# --- "Maiores Variações do Dia" card --------------------------------------


class MoverOut(BaseModel):
    """One asset ranked by its daily variation. Value is the current quote in
    the asset's native display currency (BRL for BR, USD for EUA/Cripto)."""

    ticker: str
    asset_name: str | None = None
    segment: str  # br | us | crypto
    change_pct: Decimal  # fractional day variation (crypto: Binance 24h)
    price: Decimal  # current quote, native currency
    currency: str  # BRL | USD


class MoversBucketOut(BaseModel):
    gainers: list[MoverOut] = []  # up to 6, change_pct desc
    losers: list[MoverOut] = []  # up to 6, change_pct asc


class MoversOut(BaseModel):
    """Pre-ranked buckets for each chip filter, so switching chips needs no
    refetch. Keys: all, br, us, crypto."""

    filters: dict[str, MoversBucketOut]
    # Crypto band shown under the "all" view only: BTC/ETH with their Binance
    # 24h change, kept out of the stock ranking (different metric). Empty for
    # the per-segment chips, which carry crypto in their own filters bucket.
    crypto_info: list[MoverOut] = []
    skipped: int = 0  # flat/unpriced assets excluded from ranking
    fetched_at: datetime
    warnings: list[str] = []
