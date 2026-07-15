"""External market-context indicators for the Mercado section.

Context, not signal: this module only reads public sources and reports the
numbers (and the source's own textual classification, for F&G). No buy/sell
labels, no "cheap/expensive". Each indicator is fetched independently and the
aggregate is cached for 30 minutes; a failing source falls back to its last
known value marked stale (or a null placeholder), never breaking the section.

Reuses existing fetchers: yfinance history (^VIX/^GSPC/DX-Y.NYB via
history().Close — never fast_info, which returns None for indices), brapi for
IBOV (with the same yfinance ^BVSP path as fallback when brapi fails), and
the Binance USDT klines fetcher for the Mayer Multiple.
"""

from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.schemas.market import Fng, FngEntry, Indicator, MarketOut, Mayer
from app.services.history import fetch_binance_usd_history, fetch_yfinance_history
from app.services.quotes import QuoteFetchError, _get_json

HTTP_TIMEOUT = 10.0
CACHE_TTL = timedelta(minutes=30)
# BTC moves faster than the macro indicators, so its price/24h change refreshes
# on a shorter cache, overlaid onto the (30-min) dominance card.
BTC_CACHE_TTL = timedelta(minutes=15)
MAYER_YEARS = 4

_CENTS = Decimal("0.01")
_Q4 = Decimal("0.0001")

# Whole-response cache + per-indicator last-known-good (for stale fallback).
_cache: dict = {"at": None, "out": None}
_last: dict = {}
# 15-min cache for the BTC spot price + 24h change (tuple or None).
_btc_cache: dict = {"at": None, "data": None}


def reset_cache() -> None:
    _cache["at"] = None
    _cache["out"] = None
    _last.clear()
    _btc_cache["at"] = None
    _btc_cache["data"] = None


def _today() -> "datetime.date":
    return datetime.now(timezone.utc).date()


# --- individual sources (module-level so a single one can be stubbed) -------


def fetch_fng() -> Fng:
    """Crypto Fear & Greed (alternative.me). value/timestamp are strings."""
    response = httpx.get("https://api.alternative.me/fng/?limit=8", timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    entries = response.json()["data"]

    def entry(i: int) -> FngEntry | None:
        if i >= len(entries):
            return None
        raw = entries[i]
        return FngEntry(
            value=int(raw["value"]),
            classification=raw["value_classification"],
            date=datetime.fromtimestamp(int(raw["timestamp"]), tz=timezone.utc).date(),
        )

    return Fng(today=entry(0), yesterday=entry(1), last_week=entry(7), stale=False)


def fetch_btc_dominance() -> Indicator:
    response = httpx.get("https://api.coingecko.com/api/v3/global", timeout=HTTP_TIMEOUT)
    response.raise_for_status()
    dom = response.json()["data"]["market_cap_percentage"]["btc"]
    return Indicator(
        key="btc_dominance",
        label="Dominância BTC",
        value=Decimal(str(dom)).quantize(_CENTS),
        unit="%",
        as_of=_today(),
        source="coingecko",
    )


def fetch_crypto_24h(ticker: str) -> tuple[Decimal, Decimal]:
    """Spot USD price and REAL rolling 24h change from Binance's 24hr ticker
    for the {ticker}USDT pair — not a yfinance D-1/D close difference. Returns
    (price_usd, change_fraction)."""
    data = _get_json(
        "https://api.binance.com/api/v3/ticker/24hr",
        params={"symbol": f"{ticker}USDT"},
    )
    price = Decimal(str(data["lastPrice"])).quantize(_CENTS)
    pct = (Decimal(str(data["priceChangePercent"])) / 100).quantize(_Q4)
    return price, pct


def fetch_btc_24h() -> tuple[Decimal, Decimal]:
    """BTC spot price + rolling 24h change (BTCUSDT) for the dominance card."""
    return fetch_crypto_24h("BTC")


def _change(last: Decimal, prev: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if prev is None or prev == 0:
        return None, None
    return (last - prev).quantize(_Q4), ((last / prev) - 1).quantize(_Q4)


def _yfinance_last_two(symbol: str) -> tuple[Decimal, Decimal | None, "datetime.date"]:
    """Latest and previous closes via history().Close (never fast_info)."""
    end = _today()
    series = fetch_yfinance_history(symbol, end - timedelta(days=14), end)
    dates = sorted(series)
    last = dates[-1]
    prev = series[dates[-2]] if len(dates) > 1 else None
    return series[last], prev, last


def fetch_index(key: str, label: str, symbol: str, unit: str) -> Indicator:
    price, prev, on = _yfinance_last_two(symbol)
    change, change_pct = _change(price, prev)
    return Indicator(
        key=key,
        label=label,
        value=price.quantize(_CENTS),
        unit=unit,
        change=change,
        change_pct=change_pct,
        as_of=on,
        source="yfinance",
    )


def fetch_treasury_3m() -> Indicator:
    # ^IRX is the 13-week T-bill annualised yield (%); same fetch the CAPM uses.
    return fetch_index("treasury_3m", "3M Treasury", "^IRX", "%")


def fetch_treasury_10y() -> Indicator:
    # ^TNX is the 10-year Treasury note yield (%).
    return fetch_index("treasury_10y", "10Y Treasury", "^TNX", "%")


def fetch_ibov() -> Indicator:
    """brapi first (intraday-ish quote, value+change in one call); any brapi
    failure (quota 402, timeout, bad payload) falls back to the same
    yfinance ^BVSP close-based path the other indices already use — reused,
    not duplicated — so a dead brapi degrades the card to close-vs-close
    instead of killing it. Each path labels its own `source`, so the
    dashboard shows whoever actually answered. Both dead -> the exception
    reaches _safe, which serves last-known stale, as before."""
    try:
        return _fetch_ibov_brapi()
    except QuoteFetchError:
        return fetch_index("ibov", "IBOV", "^BVSP", "pts")


def _fetch_ibov_brapi() -> Indicator:
    # brapi's IBOV symbol is ^BVSP; the caret must be URL-encoded (%5EBVSP) or
    # brapi rejects/ times out. The same response carries the change, so no
    # extra call is needed.
    params = {"token": settings.brapi_token} if settings.brapi_token else {}
    data = _get_json(
        f"https://brapi.dev/api/quote/{quote('^BVSP', safe='')}", params=params
    )
    result = (data.get("results") or [None])[0]
    if not result or result.get("regularMarketPrice") is None:
        raise QuoteFetchError("brapi returned no IBOV price")
    price = Decimal(str(result["regularMarketPrice"]))
    change_raw = result.get("regularMarketChange")
    pct_raw = result.get("regularMarketChangePercent")
    market_time = result.get("regularMarketTime")
    as_of = (
        date_type.fromisoformat(str(market_time)[:10]) if market_time else _today()
    )
    return Indicator(
        key="ibov",
        label="IBOV",
        value=price.quantize(_CENTS),
        unit="pts",
        change=Decimal(str(change_raw)).quantize(_CENTS) if change_raw is not None else None,
        # brapi gives the percent as e.g. 1.21 (already %); store as fraction.
        change_pct=(Decimal(str(pct_raw)) / 100).quantize(_Q4) if pct_raw is not None else None,
        as_of=as_of,
        source="brapi",
    )


def fetch_mayer() -> Mayer:
    """Mayer Multiple from Binance BTCUSDT klines: price / 200d MA, plus the
    components and where today sits in the last MAYER_YEARS of Mayer values."""
    end = _today()
    start = end - timedelta(days=MAYER_YEARS * 365 + 220)  # +220 to seed MA200
    series = fetch_binance_usd_history("BTCUSDT", start, end)
    dates = sorted(series)
    closes = [series[d] for d in dates]
    if len(closes) < 200:
        raise QuoteFetchError("insufficient BTCUSDT klines for MA200")

    window = Decimal(200)
    running = sum(closes[:200], Decimal(0))
    ma200 = [running / window]
    for i in range(200, len(closes)):
        running += closes[i] - closes[i - 200]
        ma200.append(running / window)
    # ma200[k] aligns with closes[199 + k]
    mayer_series = [closes[199 + k] / ma200[k] for k in range(len(ma200))]

    current = mayer_series[-1]
    below = sum(1 for m in mayer_series if m <= current)
    return Mayer(
        value=current.quantize(_Q4),
        price=closes[-1].quantize(_CENTS),
        ma200=ma200[-1].quantize(_CENTS),
        min=min(mayer_series).quantize(_Q4),
        max=max(mayer_series).quantize(_Q4),
        percentile=(Decimal(below) / Decimal(len(mayer_series))).quantize(_Q4),
        years=MAYER_YEARS,
        as_of=dates[-1],
        source="binance",
    )


# --- aggregation with 30-min cache + independent failure handling ----------


def _safe(key, fetch, fallback, warnings):
    try:
        value = fetch()
    except Exception as exc:  # noqa: BLE001 - one dead source must not kill the rest
        warnings.append(f"{key}: fonte indisponível ({type(exc).__name__})")
        prev = _last.get(key)
        if prev is not None:
            return prev.model_copy(update={"stale": True})
        return fallback()
    _last[key] = value
    return value


def _btc_spot_24h() -> tuple[Decimal, Decimal] | None:
    """BTC price + 24h change on a 15-min cache; last-known on failure."""
    now = datetime.now(timezone.utc)
    if (
        _btc_cache["data"] is not None
        and _btc_cache["at"] is not None
        and now - _btc_cache["at"] < BTC_CACHE_TTL
    ):
        return _btc_cache["data"]
    try:
        data = fetch_btc_24h()
    except Exception:  # noqa: BLE001
        return _btc_cache["data"]
    _btc_cache["data"] = data
    _btc_cache["at"] = now
    return data


def _with_btc(out: MarketOut) -> MarketOut:
    """Overlay the fresh (15-min) BTC price + 24h change onto the dominance
    card, leaving the rest of the (30-min) response untouched."""
    spot = _btc_spot_24h()
    if spot is None:
        return out
    price, change_pct = spot
    dominance = out.btc_dominance.model_copy(
        update={"btc_price_usd": price, "btc_change_pct": change_pct}
    )
    return out.model_copy(update={"btc_dominance": dominance})


def build_market_indicators(refresh: bool = False) -> MarketOut:
    now = datetime.now(timezone.utc)
    if (
        not refresh
        and _cache["out"] is not None
        and _cache["at"] is not None
        and now - _cache["at"] < CACHE_TTL
    ):
        return _with_btc(_cache["out"])

    warnings: list[str] = []
    out = MarketOut(
        fng=_safe("fng", fetch_fng, lambda: Fng(stale=True), warnings),
        btc_dominance=_safe(
            "btc_dominance",
            fetch_btc_dominance,
            lambda: Indicator(
                key="btc_dominance", label="Dominância BTC", unit="%",
                source="coingecko", stale=True,
            ),
            warnings,
        ),
        mayer=_safe("mayer", fetch_mayer, lambda: Mayer(source="binance", stale=True), warnings),
        ibov=_safe(
            "ibov",
            fetch_ibov,
            lambda: Indicator(key="ibov", label="IBOV", unit="pts", source="brapi", stale=True),
            warnings,
        ),
        sp500=_safe(
            "sp500",
            lambda: fetch_index("sp500", "S&P 500", "^GSPC", "pts"),
            lambda: Indicator(key="sp500", label="S&P 500", unit="pts", source="yfinance", stale=True),
            warnings,
        ),
        vix=_safe(
            "vix",
            lambda: fetch_index("vix", "VIX", "^VIX", "pts"),
            lambda: Indicator(key="vix", label="VIX", unit="pts", source="yfinance", stale=True),
            warnings,
        ),
        dxy=_safe(
            "dxy",
            lambda: fetch_index("dxy", "DXY", "DX-Y.NYB", "pts"),
            lambda: Indicator(key="dxy", label="DXY", unit="pts", source="yfinance", stale=True),
            warnings,
        ),
        treasury_3m=_safe(
            "treasury_3m",
            fetch_treasury_3m,
            lambda: Indicator(key="treasury_3m", label="3M Treasury", unit="%", source="yfinance", stale=True),
            warnings,
        ),
        treasury_10y=_safe(
            "treasury_10y",
            fetch_treasury_10y,
            lambda: Indicator(key="treasury_10y", label="10Y Treasury", unit="%", source="yfinance", stale=True),
            warnings,
        ),
        fetched_at=now,
        warnings=warnings,
    )
    _cache["out"] = out
    _cache["at"] = now
    return _with_btc(out)
