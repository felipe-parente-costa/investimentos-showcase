"""Quote service with a 5-minute cache over the `quotes` table.

Source per market (fixed by CLAUDE.md / user choice):
- br: brapi.dev (token from APP_BRAPI_TOKEN)
- us: yfinance
- crypto: Binance REST, always quoted against BRL ({ticker}BRL pair)

Rules:
- Never call an external source if a quote for the ticker was fetched
  within the cache window.
- On fetch failure, return the last cached quote with stale=True.
- Fixed income: Tesouro Direto bonds are marked to market via the Tesouro
  Transparente CSV (see services/tesouro.py), refreshed once per business
  day. Private fixed income (CDB/LCI/LCA) has no public price and returns
  None, so the portfolio values it at cost.
- Live fetches only happen from `live=True` call sites (the scheduler job).
  Request paths (e.g. GET /portfolio) call with `live=False`: cache hit or
  miss, they always return immediately, never block on an external call.
- Every fallback to a stale (or absent) cache logs a warning with the
  ticker and the reason — a dead source must never look, from the logs
  alone, indistinguishable from a healthy one.
- source='cotahist' quotes (Market.br stocks/FIIs) do not use the 5-minute
  CACHE_WINDOW: they refresh once/day on a calendar session, not a rolling
  window, so freshness is "is this still the expected trading session"
  (see _is_fresh) rather than "was this fetched N minutes ago". US, crypto
  and Tesouro Direto are unaffected — they keep their existing checks.
- source='brapi' quotes are written once a day too (the 15:00 BRT scheduler
  window, BR stocks only), so they are fresh for the rest of their São
  Paulo day (see _is_fresh) — precedence between brapi and cotahist for the
  same ticker is simply "latest fetched_at wins" (_latest_cached): the
  15:00 intraday price supersedes the morning close, and the next morning's
  COTAHIST supersedes it back.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.enums import AssetClass, Market
from app.models.quote import Quote
from app.services.cotahist import expected_previous_session
from app.services.tesouro import (
    TreasuryError,
    fetch_treasury_price,
    parse_bond_ticker,
)

logger = logging.getLogger(__name__)

CACHE_WINDOW = timedelta(minutes=5)
HTTP_TIMEOUT = 10.0
# Tesouro prices change once per business day; the trading-day boundary is
# São Paulo local time, not UTC.
SAO_PAULO = ZoneInfo("America/Sao_Paulo")


class QuoteFetchError(Exception):
    pass


@dataclass
class FetchedQuote:
    price: Decimal
    currency: str
    quote_date: date
    source: str


@dataclass
class QuoteResult:
    ticker: str
    price: Decimal
    currency: str
    quote_date: date
    fetched_at: datetime
    source: str
    stale: bool


def get_quote(
    db: Session,
    ticker: str,
    market: Market,
    asset_class: AssetClass,
    *,
    live: bool = True,
) -> QuoteResult | None:
    """`live=False` (request paths) never calls an external source: a cache
    hit returns fresh, a cache miss/expiry returns the last row stale (or
    None with no cache at all) — always immediate. `live=True` (the
    scheduler job only) may block on a real fetch when the cache is cold."""
    if asset_class is AssetClass.fixed_income:
        return _get_treasury_quote(db, ticker, live=live)
    fetcher = FETCHERS.get(market)
    if fetcher is None:
        return None

    now = datetime.now(timezone.utc)
    cached = _latest_cached(db, ticker)
    if cached is not None and _is_fresh(cached, now):
        return _result(cached, stale=False)

    if not live:
        return _result(cached, stale=True) if cached is not None else None

    try:
        fetched = fetcher(ticker)
    except QuoteFetchError as exc:
        if cached is not None:
            logger.warning(
                "%s: live fetch failed (%s); serving stale cache from %s",
                ticker, exc, _as_utc(cached.fetched_at).isoformat(),
            )
            return _result(cached, stale=True)
        logger.warning("%s: live fetch failed (%s); no cache to fall back to", ticker, exc)
        return None

    quote = Quote(
        ticker=ticker,
        date=fetched.quote_date,
        close_price=fetched.price,
        currency=fetched.currency,
        source=fetched.source,
        kind="intraday",
        fetched_at=now,
    )
    db.add(quote)
    db.commit()
    return _result(quote, stale=False)


def _get_treasury_quote(
    db: Session, ticker: str, *, live: bool = True
) -> QuoteResult | None:
    """Mark-to-market for Tesouro Direto bonds; None (valued at cost) for
    private fixed income (CDB/LCI/LCA) or a Tesouro bond absent from the
    source. Prices change only on business days, so a price already fetched
    today is reused without hitting the source again."""
    key = parse_bond_ticker(ticker)
    if key is None:
        return None  # not a Tesouro Direto bond -> cost

    now = datetime.now(timezone.utc)
    cached = _latest_cached(db, ticker)
    if cached is not None and _sp_date(cached.fetched_at) == _sp_date(now):
        return _result(cached, stale=False)

    if not live:
        return _result(cached, stale=True) if cached is not None else None

    try:
        price = fetch_treasury_price(key)
    except TreasuryError as exc:
        # No source reachable: keep the last price if we have one.
        if cached is not None:
            logger.warning(
                "%s: Tesouro price fetch failed (%s); serving stale cache from %s",
                ticker, exc, _as_utc(cached.fetched_at).isoformat(),
            )
            return _result(cached, stale=True)
        logger.warning("%s: Tesouro price fetch failed (%s); no cache to fall back to", ticker, exc)
        return None
    if price is None:
        # Recognized type, no matching bond in the source -> cost.
        if cached is not None:
            logger.warning(
                "%s: Tesouro bond not found in source; serving stale cache from %s",
                ticker, _as_utc(cached.fetched_at).isoformat(),
            )
            return _result(cached, stale=True)
        logger.warning("%s: Tesouro bond not found in source; no cache, valued at cost", ticker)
        return None

    quote = Quote(
        ticker=ticker,
        date=price.reference_date,
        close_price=price.pu,
        currency="BRL",
        source=price.source,
        kind="intraday",
        fetched_at=now,
    )
    db.add(quote)
    db.commit()
    return _result(quote, stale=False)


def fetch_brapi(ticker: str) -> FetchedQuote:
    params: dict[str, str] = {}
    if settings.brapi_token:
        params["token"] = settings.brapi_token
    data = _get_json(f"https://brapi.dev/api/quote/{ticker}", params=params)
    results = data.get("results") or []
    price = results[0].get("regularMarketPrice") if results else None
    if price is None:
        raise QuoteFetchError(f"brapi returned no price for {ticker}")
    market_time = results[0].get("regularMarketTime")
    quote_date = (
        date.fromisoformat(str(market_time)[:10])
        if market_time
        else datetime.now(timezone.utc).date()
    )
    return FetchedQuote(
        price=_as_decimal(price),
        currency=results[0].get("currency") or "BRL",
        quote_date=quote_date,
        source="brapi",
    )


def fetch_binance(ticker: str) -> FetchedQuote:
    symbol = f"{ticker}BRL"
    data = _get_json(
        "https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol}
    )
    price = data.get("price")
    if price is None:
        raise QuoteFetchError(f"Binance returned no price for {symbol}")
    return FetchedQuote(
        price=_as_decimal(price),
        currency="BRL",
        quote_date=datetime.now(timezone.utc).date(),
        source="binance",
    )


def fetch_binance_usd(ticker: str) -> FetchedQuote:
    """Spot price of a crypto asset against USDT (~USD), for the USD view of
    the Cripto section. Stored under a distinct `{ticker}USDT` cache key so it
    never collides with the BRL `{ticker}` quote."""
    symbol = f"{ticker}USDT"
    data = _get_json(
        "https://api.binance.com/api/v3/ticker/price", params={"symbol": symbol}
    )
    price = data.get("price")
    if price is None:
        raise QuoteFetchError(f"Binance returned no price for {symbol}")
    return FetchedQuote(
        price=_as_decimal(price),
        currency="USD",
        quote_date=datetime.now(timezone.utc).date(),
        source="binance-usd",
    )


def get_crypto_usd_quote(
    db: Session, ticker: str, *, live: bool = True
) -> QuoteResult | None:
    """USD (USDT) spot quote for a crypto ticker, cached under `{ticker}USDT`.

    Same live/cache contract as get_quote: `live=False` (request paths, e.g.
    the USD view inside GET /portfolio) never fetches — fresh hit, stale
    fallback or None, always immediate. The scheduler keeps this cache warm
    with `live=True`."""
    cache_ticker = f"{ticker}USDT"
    now = datetime.now(timezone.utc)
    cached = _latest_cached(db, cache_ticker)
    if cached is not None and now - _as_utc(cached.fetched_at) < CACHE_WINDOW:
        return _result(cached, stale=False)
    if not live:
        return _result(cached, stale=True) if cached is not None else None
    try:
        fetched = CRYPTO_USD_FETCHER(ticker)
    except QuoteFetchError as exc:
        if cached is not None:
            logger.warning(
                "%s: crypto USD quote fetch failed (%s); serving stale cache from %s",
                ticker, exc, _as_utc(cached.fetched_at).isoformat(),
            )
            return _result(cached, stale=True)
        logger.warning("%s: crypto USD quote fetch failed (%s); no cache to fall back to", ticker, exc)
        return None
    quote = Quote(
        ticker=cache_ticker,
        date=fetched.quote_date,
        close_price=fetched.price,
        currency="USD",
        source=fetched.source,
        kind="intraday",
        fetched_at=now,
    )
    db.add(quote)
    db.commit()
    return _result(quote, stale=False)


MARKET_FX_TICKER = "USDBRL=X"
# Commercial USD/BRL is display-only (a header card); a 10-minute cache keeps
# the yfinance pull light without aggressive polling.
MARKET_FX_CACHE = timedelta(minutes=10)


def get_usdbrl_market_rate(db: Session) -> QuoteResult | None:
    """Commercial (market) USD/BRL spot from yfinance, cached for 10 minutes.

    This is the delayed market quote shown on the EUA page header — NOT the
    PTAX used for the portfolio cost basis. Cached under the `USDBRL=X` ticker;
    on a fetch failure the last known value is returned with stale=True.
    """
    now = datetime.now(timezone.utc)
    cached = _latest_cached(db, MARKET_FX_TICKER)
    if cached is not None and now - _as_utc(cached.fetched_at) < MARKET_FX_CACHE:
        return _result(cached, stale=False)
    try:
        fetched = MARKET_FX_FETCHER(MARKET_FX_TICKER)
    except QuoteFetchError as exc:
        if cached is not None:
            logger.warning(
                "USD/BRL market rate fetch failed (%s); serving stale cache from %s",
                exc, _as_utc(cached.fetched_at).isoformat(),
            )
            return _result(cached, stale=True)
        logger.warning("USD/BRL market rate fetch failed (%s); no cache to fall back to", exc)
        return None
    quote = Quote(
        ticker=MARKET_FX_TICKER,
        date=fetched.quote_date,
        close_price=fetched.price,
        currency=fetched.currency,
        source=fetched.source,
        kind="intraday",
        fetched_at=now,
    )
    db.add(quote)
    db.commit()
    return _result(quote, stale=False)


def fetch_yfinance(ticker: str) -> FetchedQuote:
    try:
        import yfinance  # heavy import, deferred until a us-market quote is needed

        info = yfinance.Ticker(ticker).fast_info
        price = info["lastPrice"]
        currency = info["currency"]
    except Exception as exc:
        raise QuoteFetchError(f"yfinance failed for {ticker}: {exc}") from exc
    if price is None:
        raise QuoteFetchError(f"yfinance returned no price for {ticker}")
    return FetchedQuote(
        price=_as_decimal(price),
        currency=str(currency or "USD"),
        quote_date=datetime.now(timezone.utc).date(),
        source="yfinance",
    )


# Injectable so tests don't reach Binance for the USD crypto spot quote.
CRYPTO_USD_FETCHER: Callable[[str], FetchedQuote] = fetch_binance_usd

# Single source for the commercial USD/BRL market rate; swap here to change it.
MARKET_FX_FETCHER: Callable[[str], FetchedQuote] = fetch_yfinance

FETCHERS: dict[Market, Callable[[str], FetchedQuote]] = {
    Market.br: fetch_brapi,
    Market.us: fetch_yfinance,
    Market.crypto: fetch_binance,
}


def get_previous_close(db: Session, ticker: str, before: date) -> Decimal | None:
    """Last cached official close strictly before `before` (cache-only, no
    fetch). Intraday snapshot rows are not closes and are ignored.

    The history backfill keeps daily closes in the quotes table, so for
    held tickers this is the prior trading day's close.
    """
    row = db.execute(
        select(Quote.close_price)
        .where(
            Quote.ticker == ticker,
            Quote.date < before,
            Quote.kind == "close",
        )
        .order_by(Quote.date.desc(), Quote.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row


def _latest_cached(db: Session, ticker: str) -> Quote | None:
    """Row the current-price path serves. kind='intraday' rows (spot
    snapshots: cotahist/brapi/binance/yfinance fast_info/tesouro) win over
    kind='close' rows (history backfill) of the same session or older, even
    when the close row was fetched later: the backfill landing yesterday's
    official close mid-afternoon must not hijack the displayed price back to
    a stale-flagged D-1 value (or trample the 15:00 brapi intraday with it).
    A close row with a strictly NEWER session still wins — it is genuinely
    newer information, e.g. the spot feed has been dead for days. Ties
    between intraday rows keep the existing fetched_at order (cotahist 06:00
    vs brapi 15:00 precedence unchanged). The long series (TWR/correlation)
    reads kind='close' through its own queries and is untouched here."""
    intraday = db.execute(
        select(Quote)
        .where(Quote.ticker == ticker, Quote.kind == "intraday")
        .order_by(Quote.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    close = db.execute(
        select(Quote)
        .where(Quote.ticker == ticker, Quote.kind != "intraday")
        .order_by(Quote.date.desc(), Quote.fetched_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if intraday is None:
        return close
    if close is not None and close.date > intraday.date:
        return close
    return intraday


def _is_fresh(cached: Quote, now: datetime) -> bool:
    """source='cotahist' rows refresh once/day on a calendar session, not a
    rolling window: the 5-minute CACHE_WINDOW would mark a same-day official
    close stale for all but the few minutes right after the daily job runs.
    Fresh here means "still the expected trading session" — it goes stale
    once a newer session should have replaced it (a new one was fetched, or
    the daily job fell behind and expected_previous_session moved on),
    which is exactly when refresh_br_quotes_daily's own warning would also
    fire. The pregão calendar lives in São Paulo time: using the UTC date
    here flipped BR quotes to stale at 21:00 BRT (UTC midnight) instead of
    at the local midnight. Every other source keeps the original
    rolling-window check."""
    if cached.source == "cotahist":
        return cached.date >= expected_previous_session(_sp_date(now))
    if cached.source == "brapi":
        # Written once a day by the 15:00 BRT scheduler window (BR stocks
        # only): fresh for the rest of its São Paulo day, like the Tesouro
        # rule above. The 5-minute window would flag it stale from 15:05
        # until the next COTAHIST close lands at 06:00 — an intraday price
        # from today's own session is not "a dead source serving old data".
        # After SP midnight it goes stale until COTAHIST takes over, the
        # same overnight gap cotahist rows already have.
        return _sp_date(cached.fetched_at) == _sp_date(now)
    return now - _as_utc(cached.fetched_at) < CACHE_WINDOW


def _result(quote: Quote, *, stale: bool) -> QuoteResult:
    return QuoteResult(
        ticker=quote.ticker,
        price=quote.close_price,
        currency=quote.currency,
        quote_date=quote.date,
        fetched_at=_as_utc(quote.fetched_at),
        source=quote.source,
        stale=stale,
    )


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo on read; stored values are always UTC.
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _sp_date(value: datetime) -> date:
    """Calendar date of a UTC timestamp in São Paulo local time."""
    return _as_utc(value).astimezone(SAO_PAULO).date()


def _as_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _get_json(url: str, params: dict[str, str] | None = None) -> dict:
    try:
        response = httpx.get(url, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return json.loads(response.text, parse_float=Decimal)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise QuoteFetchError(f"{url}: {exc}") from exc
