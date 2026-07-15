"""Patrimony history: daily portfolio value reconstructed from transactions.

Daily closes per ticker are fetched from the market's source (yfinance
`.SA` for B3, Binance klines for crypto, yfinance for US) and cached in
the `quotes` table — one row per (ticker, date). Missing dates (weekends,
holidays) carry the previous close forward. Positions without a close for
a given day (fixed income, delisted tickers) fall back to cost basis. USD
values are converted with the PTAX closing rate of each day, per CLAUDE.md.

brapi is deliberately NOT used here: its free plan caps daily history at 3
months (range=max returns 400), so every call this module ever made to it
failed by construction while still burning monthly quota — including as a
"fallback", which could only fire in exactly the situation where it would
400 as well. Tickers no longer resolvable anywhere live in
DEAD_HISTORY_TICKERS instead of retrying forever.
"""

import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Callable, Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Market, Operation
from app.models.quote import Quote
from app.models.transaction import Transaction
from app.services import splits as splits_service
from app.services.cotahist import BR_COTAHIST_CLOSE_CUTOFF
from app.services.fx import get_usd_brl_series
from app.services.portfolio import Position, _apply, _engine_order
from app.services.quotes import QuoteFetchError
from app.services.tesouro import (
    TreasuryError,
    parse_bond_ticker,
    treasury_pu_history,
)

logger = logging.getLogger(__name__)

# Injectable so tests don't hit the network; the real one is yfinance.
SPLITS_FETCHER = splits_service.fetch_splits

ZERO = Decimal("0")
FETCH_MEMO_WINDOW = timedelta(minutes=5)
# Start-edge slack (see _covers): tolerates listing dates near the window
# start without refetching forever.
COVERAGE_SLACK = timedelta(days=7)
# End-edge slack: how old the newest official close may be before a refetch.
# 3 days is the minimum that a weekend gap satisfies (Friday's close on a
# Monday) without triggering a fetch-per-memo-window loop on days when no
# new close can exist yet; new closes therefore land in batches of at most
# 3 days. The live price shown for positions comes from get_quote, not from
# this series.
RECENT_SLACK = timedelta(days=3)
# After this many consecutive fetch failures for a ticker, retries back off
# from the 5-minute memo to once a day: a symbol the source cannot resolve
# (delisted, renamed) would otherwise re-attempt on every screen open.
FAILURE_BACKOFF_THRESHOLD = 3
FAILURE_BACKOFF_WINDOW = timedelta(hours=24)

# Tickers whose close series can never advance again — same explicit
# per-ticker allowlist pattern as ASSET_CLASS_OVERRIDES. Delisted or renamed
# symbols (a closed position whose ticker no longer resolves at any source)
# would otherwise re-attempt a doomed external fetch on every screen open.
# The frozen series is harmless: valuation after the holding window
# multiplies a zero quantity. Being listed here skips the external fetch
# entirely; the cached series still serves reads. Map ticker -> reason, e.g.
# {"OLDT3": "renamed to NEWT3; symbol extinct at the sources"}.
DEAD_HISTORY_TICKERS: dict[str, str] = {}

Granularity = Literal["daily", "weekly", "monthly"]


@dataclass
class HistoryPoint:
    date: date
    total_brl: Decimal
    # Cumulative Time-Weighted Return index, base 100 at the series start.
    twr_index: Decimal = Decimal("100")


@dataclass
class HistoryResult:
    points: list[HistoryPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class MarketData:
    """Daily closes and FX shared across every segment computation.

    `days` spans the global transaction history so segment TWR series stay
    aligned for comparison; `closes[ticker]` and `fx` are carried forward
    over non-trading days.
    """

    days: list[date]
    closes: dict[str, list[Decimal | None]]
    fx: list[Decimal | None] | None
    warnings: list[str] = field(default_factory=list)


_fetch_attempts: dict[str, datetime] = {}
_fetch_failures: dict[str, int] = {}
_dead_logged: set[str] = set()


def reset_memo() -> None:
    _fetch_attempts.clear()
    _fetch_failures.clear()
    _dead_logged.clear()


def get_daily_closes(
    db: Session,
    ticker: str,
    market: Market | None,
    start: date,
    end: date,
    *,
    fetcher: Callable[[str, date, date], dict[date, Decimal]] | None = None,
    currency: str | None = None,
    source: str | None = None,
) -> dict[date, Decimal]:
    """Daily series for a ticker, cached in the quotes table.

    By default the fetcher/currency/source come from the market; explicit
    overrides serve series outside any market (benchmark indexes, CDI).
    """
    series = _cached_closes(db, ticker, start, end)
    if fetcher is None and market is not None:
        fetcher = HISTORY_FETCHERS.get(market)
        currency = "USD" if market is Market.us else "BRL"
        source = f"{HISTORY_SOURCES[market]}-history"
    if fetcher is None or _covers(series, start, end):
        return series

    if ticker in DEAD_HISTORY_TICKERS:
        # Known-dead symbol: serve whatever is cached, never re-attempt.
        # Logged once per process so the give-up stays visible without a
        # log line per screen open.
        if ticker not in _dead_logged:
            _dead_logged.add(ticker)
            logger.info(
                "%s: history fetch skipped permanently (%s)",
                ticker, DEAD_HISTORY_TICKERS[ticker],
            )
        return series

    now = datetime.now(timezone.utc)
    attempted = _fetch_attempts.get(ticker)
    window = (
        FAILURE_BACKOFF_WINDOW
        if _fetch_failures.get(ticker, 0) >= FAILURE_BACKOFF_THRESHOLD
        else FETCH_MEMO_WINDOW
    )
    if attempted is not None and now - attempted < window:
        return series
    _fetch_attempts[ticker] = now

    try:
        fetched = fetcher(ticker, start, end)
    except QuoteFetchError as exc:
        failures = _fetch_failures.get(ticker, 0) + 1
        _fetch_failures[ticker] = failures
        if failures == FAILURE_BACKOFF_THRESHOLD:
            logger.warning(
                "%s: %d consecutive history fetch failures (%s); backing off "
                "to daily retries — if the symbol is truly gone, add it to "
                "DEAD_HISTORY_TICKERS",
                ticker, failures, exc,
            )
        return series
    _fetch_failures.pop(ticker, None)

    # Option 2: store closes as-traded (un-apply yfinance's split adjustment)
    # so they match our as-traded share counts. Fail loud — never write an
    # unverified as-traded series.
    store_source = source or "history"
    if market in (Market.us, Market.br):
        fetched, store_source = _as_traded(db, ticker, market, fetched, store_source)

    # Only official closes count as "already stored": an intraday snapshot on
    # a date must not block that date's real close from landing (bug C3).
    existing = set(
        db.execute(
            select(Quote.date).where(Quote.ticker == ticker, Quote.kind == "close")
        ).scalars()
    )
    skipped_cutoff = 0
    for close_date, close in fetched.items():
        if close_date >= now.date():
            # Today's bar is still forming (a mid-session price, not a
            # close); writing it would freeze that partial value forever,
            # since existing dates are never rewritten. It lands tomorrow.
            continue
        if market is Market.br and close_date >= BR_COTAHIST_CLOSE_CUTOFF:
            # From the cutoff session on, BR closes are written only by the
            # COTAHIST 06:00 job. Writing here would race it overnight: the
            # UTC "today" check above releases the current session's bar at
            # 21:00 BRT, hours before the job runs — whoever landed first
            # would own the date forever (existing dates are never
            # rewritten). One shared constant on both sides removes the race.
            skipped_cutoff += 1
            continue
        if close_date not in existing:
            db.add(
                Quote(
                    ticker=ticker,
                    date=close_date,
                    close_price=close,
                    currency=currency or "BRL",
                    source=store_source,
                    kind="close",
                    fetched_at=now,
                )
            )
    if skipped_cutoff:
        logger.info(
            "%s: skipped %d fetched BR close(s) on/after %s — kind='close' "
            "for Market.br is COTAHIST-only from the cutoff on "
            "(BR_COTAHIST_CLOSE_CUTOFF)",
            ticker,
            skipped_cutoff,
            BR_COTAHIST_CLOSE_CUTOFF.isoformat(),
        )
    db.commit()
    return _cached_closes(db, ticker, start, end)


def _as_traded(
    db: Session,
    ticker: str,
    market: Market,
    fetched: dict[date, Decimal],
    source: str,
) -> tuple[dict[date, Decimal], str]:
    """Convert a fetched (split-adjusted) series to as-traded, or fail loud.

    Returns (series, source). On any failure to obtain or verify the split
    data, the adjusted series is kept unchanged and the source is marked
    `-adj`, so the data is never silently wrong. As-traded prices are only
    written when the position's quantity is reconciled with the splits (a
    split/bonus transaction for each split in the holding window) — un-
    adjusting price without the matching quantity event would create a new
    artifact, so unreconciled tickers stay adjusted (a backlog item).
    """
    sp = SPLITS_FETCHER(ticker, market)
    if sp is None:
        logger.warning("%s: split source unavailable; keeping adjusted closes", ticker)
        return fetched, f"{source}-adj"
    if not sp:
        return fetched, source  # no splits -> already as-traded
    if not splits_service.adjusted_is_continuous_at_splits(fetched, sp):
        logger.warning(
            "%s: adjusted series not continuous at split dates; "
            "keeping adjusted closes",
            ticker,
        )
        return fetched, f"{source}-adj"
    if not _quantity_reconciled(db, ticker, sp):
        logger.warning(
            "%s: splits not reconciled with quantity transactions; "
            "keeping adjusted closes (backlog)",
            ticker,
        )
        return fetched, f"{source}-adj"
    return splits_service.to_as_traded(fetched, sp), source


def _quantity_reconciled(
    db: Session, ticker: str, sp: list[tuple[date, Decimal]]
) -> bool:
    """True when every split during the holding window has a matching
    split/bonus transaction (±10 days), so the quantity timeline already
    absorbs the split. Splits before the first trade are ignored (the
    position was opened in post-split units)."""
    rows = db.execute(
        select(Transaction.date, Transaction.operation).where(
            Transaction.ticker == ticker
        )
    ).all()
    if not rows:
        return False
    first = min(r.date for r in rows)
    qty_events = [
        r.date for r in rows if r.operation in (Operation.split, Operation.bonus)
    ]
    for split_date, _ in sp:
        if split_date < first:
            continue
        if not any(abs((qd - split_date).days) <= 10 for qd in qty_events):
            return False
    return True


def fetch_treasury_history(
    ticker: str, start: date, end: date
) -> dict[date, Decimal]:
    """Daily PU Base series for a Tesouro bond, adapted to the fetcher
    signature. Raises QuoteFetchError on an unreachable source or an empty
    series so the engine falls back to cost."""
    try:
        series = treasury_pu_history(ticker, start, end)
    except TreasuryError as exc:
        raise QuoteFetchError(str(exc)) from exc
    if not series:
        raise QuoteFetchError(f"no Tesouro PU history for {ticker}")
    return series


# Injectable so tests don't hit the Tesouro CSV; the real one downloads it.
TREASURY_FETCHER = fetch_treasury_history


def load_market_data(db: Session, transactions: list[Transaction]) -> MarketData:
    """Loads daily closes and FX over the full transaction history.

    Tesouro Direto bonds are marked to market from their official PU history;
    private fixed income (CDB/LCI/LCA) has no public price and stays at cost.
    """
    ordered = sorted(transactions, key=_engine_order)
    start = ordered[0].date
    end = datetime.now(timezone.utc).date()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    ticker_market: dict[str, Market] = {}
    treasury_tickers: dict[str, None] = {}
    needs_fx = False
    for tx in ordered:
        if tx.asset_class is not AssetClass.fixed_income:
            ticker_market.setdefault(tx.ticker, tx.market)
        elif parse_bond_ticker(tx.ticker) is not None:
            treasury_tickers.setdefault(tx.ticker, None)
        if tx.market is Market.us or tx.currency == "USD":
            needs_fx = True

    warnings: list[str] = []
    closes: dict[str, list[Decimal | None]] = {}
    for ticker, market in ticker_market.items():
        series = get_daily_closes(db, ticker, market, start, end)
        if series:
            closes[ticker] = _carry_forward(series, days)
        else:
            warnings.append(f"{ticker}: sem histórico de cotações; valorado a custo")

    for ticker in treasury_tickers:
        series = get_daily_closes(
            db,
            ticker,
            None,
            start,
            end,
            fetcher=TREASURY_FETCHER,
            currency="BRL",
            source="tesouro-history",
        )
        if series:
            closes[ticker] = _carry_forward(series, days)
        else:
            warnings.append(f"{ticker}: sem histórico de PU; valorado a custo")

    fx: list[Decimal | None] | None = None
    if needs_fx:
        fx_series = get_usd_brl_series(db, start, end)
        if fx_series:
            fx = _carry_forward(fx_series, days)
        else:
            warnings.append(
                "PTAX indisponível; posições em USD valoradas a custo sem conversão"
            )

    return MarketData(days=days, closes=closes, fx=fx, warnings=warnings)


def load_usd_market_data(db: Session, transactions: list[Transaction]) -> MarketData:
    """Market data for the USD sections (EUA + Cripto), valued in USD.

    Closes are native USD — yfinance for US, Binance USDT klines for crypto
    (cached under `{ticker}USDT` to avoid colliding with the BRL series) —
    and `fx` is all-ones so `compute_value_and_twr` keeps values in USD.
    Crypto transactions fed to it must be repriced to USD (services/usd.py).
    """
    relevant = [
        t for t in transactions if t.market in (Market.us, Market.crypto)
    ]
    ordered = sorted(relevant, key=_engine_order)
    if not ordered:
        return MarketData(days=[], closes={}, fx=None)
    start = ordered[0].date
    end = datetime.now(timezone.utc).date()
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    ticker_market: dict[str, Market] = {}
    for tx in ordered:
        ticker_market.setdefault(tx.ticker, tx.market)

    warnings: list[str] = []
    closes: dict[str, list[Decimal | None]] = {}
    for ticker, market in ticker_market.items():
        if market is Market.us:
            series = get_daily_closes(db, ticker, Market.us, start, end)
        else:  # crypto: USDT klines under a distinct cache key
            series = get_daily_closes(
                db,
                f"{ticker}USDT",
                None,
                start,
                end,
                fetcher=BINANCE_USD_FETCHER,
                currency="USD",
                source="binance-usd-history",
            )
        if series:
            closes[ticker] = _carry_forward(series, days)
        else:
            warnings.append(f"{ticker}: sem histórico USD; valorado a custo")

    fx = [Decimal("1")] * len(days)  # values already in USD -> no conversion
    return MarketData(days=days, closes=closes, fx=fx, warnings=warnings)


def compute_value_and_twr(
    transactions: list[Transaction], data: MarketData
) -> tuple[list[Decimal], list[Decimal]]:
    """Daily (total_brl, twr_index) for a transaction subset, aligned to
    `data.days`. Passing a filtered subset yields a single segment's series
    while reusing the shared closes/FX."""
    by_day: dict[date, list[Transaction]] = defaultdict(list)
    for tx in sorted(transactions, key=_engine_order):
        by_day[tx.date].append(tx)

    positions: dict[str, Position] = {}
    engine_warnings: list[str] = []
    twr_factor = Decimal("1")
    previous_total: Decimal | None = None
    totals: list[Decimal] = []
    twr: list[Decimal] = []
    for index, day in enumerate(data.days):
        contributions = ZERO
        withdrawals = ZERO
        transfer_net = ZERO
        for tx in by_day.get(day, ()):
            position = positions.get(tx.ticker)
            if position is None:
                position = Position(
                    ticker=tx.ticker,
                    asset_name=tx.asset_name,
                    asset_class=tx.asset_class,
                    market=tx.market,
                    currency=tx.currency,
                )
                positions[tx.ticker] = position
            flow = _apply_with_flow(
                position, tx, engine_warnings, index, data.closes, data.fx
            )
            if tx.operation is Operation.transfer:
                # Transfers are netted per day so custody round trips
                # (lending settlements) stay neutral; only the residual is
                # an external flow.
                transfer_net += flow
            elif flow > 0:
                contributions += flow
            else:
                withdrawals += flow
        inflow = contributions + (transfer_net if transfer_net > 0 else ZERO)
        outflow = withdrawals + (transfer_net if transfer_net < 0 else ZERO)

        total = ZERO
        for position in positions.values():
            if position.quantity == 0:
                continue
            total += _position_value_brl(position, index, data.closes, data.fx)

        # TWR: chain daily returns net of external flows. Asymmetric
        # convention — contributions at start of day (denominator),
        # withdrawals at end of day (numerator) — so a purchase executed
        # below the day's close on a near-empty portfolio cannot explode
        # the daily return. Days with an empty base contribute factor 1.
        if previous_total is not None:
            denominator = previous_total + inflow
            if denominator > 0:
                twr_factor *= (total - outflow) / denominator
        previous_total = total
        totals.append(total)
        twr.append(100 * twr_factor)
    return totals, twr


def build_patrimony_history(
    db: Session, granularity: Granularity = "daily"
) -> HistoryResult:
    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return HistoryResult()

    data = load_market_data(db, transactions)
    totals, twr = compute_value_and_twr(transactions, data)
    result = HistoryResult(warnings=data.warnings)
    result.points = [
        HistoryPoint(date=day, total_brl=total, twr_index=index)
        for day, total, index in zip(data.days, totals, twr)
    ]
    result.points = _sample(result.points, granularity)
    return result


def _apply_with_flow(
    position: Position,
    tx: Transaction,
    warnings: list[str],
    day_index: int,
    closes: dict[str, list[Decimal | None]],
    fx: list[Decimal | None] | None,
) -> Decimal:
    """Applies the transaction and returns its external cash flow in BRL.

    Flows (TWR breaks): buys are contributions; sells and income are
    withdrawals. Transfers move value in/out without return: priced
    tickers are flowed at the day's close (matching the valuation, so
    custody pairs are neutral); unpriced ones at the exact cost delta the
    engine applied (matching the cost-based valuation, e.g. CDB maturity).
    Splits and bonuses are corporate events, not flows.
    """
    rate = Decimal("1")
    if position.market is Market.us or position.currency == "USD":
        rate = (fx[day_index] if fx else None) or ZERO

    op = tx.operation
    fees = tx.fees or ZERO
    if op is Operation.custody_transfer:
        # Custody is collapsed in this ticker-keyed engine, so a hot<->cold
        # move is internal: no quantity change, no value change, no flow. TWR
        # is neutral on the transfer day by construction.
        return ZERO
    if op is Operation.buy:
        _apply(position, tx, warnings)
        return (tx.quantity * tx.unit_price + fees) * rate
    if op is Operation.sell:
        # Clamped sells (no tracked cost basis, e.g. CDB redemptions with
        # purchases predating the export) moved nothing in the portfolio
        # and must not register a flow either.
        applied = _apply(position, tx, warnings)
        if applied == 0:
            return ZERO
        return (applied * tx.unit_price + fees) * rate
    if op in (Operation.dividend, Operation.jcp, Operation.yield_):
        _apply(position, tx, warnings)
        return -(tx.total_value or ZERO) * rate
    if op is Operation.transfer:
        ticker_closes = closes.get(tx.ticker)
        close = ticker_closes[day_index] if ticker_closes else None
        if close is not None:
            applied = _apply(position, tx, warnings)
            return applied * close * rate
        cost_before = position.total_cost
        _apply(position, tx, warnings)
        return (position.total_cost - cost_before) * rate
    _apply(position, tx, warnings)  # split/bonus: no external flow
    return ZERO


def _position_value_brl(
    position: Position,
    day_index: int,
    closes: dict[str, list[Decimal | None]],
    fx: list[Decimal | None] | None,
) -> Decimal:
    ticker_closes = closes.get(position.ticker)
    close = ticker_closes[day_index] if ticker_closes else None
    if close is None:
        value = position.total_cost
        value_currency = position.currency
    else:
        value = position.quantity * close
        value_currency = "USD" if position.market is Market.us else "BRL"
    if value_currency == "USD" and fx is not None:
        rate = fx[day_index]
        if rate is not None:
            return value * rate
    return value if value_currency == "BRL" else ZERO


def _carry_forward(
    series: dict[date, Decimal], days: list[date]
) -> list[Decimal | None]:
    carried: list[Decimal | None] = []
    last: Decimal | None = None
    for day in days:
        value = series.get(day)
        if value is not None:
            last = value
        carried.append(last)
    return carried


def _sample(points: list[HistoryPoint], granularity: Granularity) -> list[HistoryPoint]:
    if granularity == "daily" or not points:
        return points
    if granularity == "weekly":
        def key(d: date) -> tuple:
            iso = d.isocalendar()
            return (iso.year, iso.week)
    else:
        def key(d: date) -> tuple:
            return (d.year, d.month)
    sampled: dict[tuple, HistoryPoint] = {}
    for point in points:
        sampled[key(point.date)] = point  # last point of each period wins
    return list(sampled.values())


def _cached_closes(
    db: Session, ticker: str, start: date, end: date
) -> dict[date, Decimal]:
    """Official daily closes only — intraday snapshot rows (kind='intraday',
    written by the quote service) are not closes and never feed history."""
    rows = db.execute(
        select(Quote.date, Quote.close_price)
        .where(
            Quote.ticker == ticker,
            Quote.date >= start,
            Quote.date <= end,
            Quote.kind == "close",
        )
        .order_by(Quote.date, Quote.fetched_at)
    ).all()
    return {row.date: row.close_price for row in rows}


def _covers(series: dict[date, Decimal], start: date, end: date) -> bool:
    # Both edges matter. The series holds only official closes (kind='close'),
    # so an intraday quote row can no longer suppress the backfill; the end
    # edge just tolerates days that cannot have a close yet (weekend, today).
    # Tickers listed after `start` keep failing the old edge and refetch at
    # most once per memo window — accepted cost.
    return (
        bool(series)
        and max(series) >= end - RECENT_SLACK
        and min(series) <= start + COVERAGE_SLACK
    )


def fetch_binance_history(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    symbol = f"{ticker}BRL"
    start_ms = int(datetime.combine(start, time(), tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(
        datetime.combine(end + timedelta(days=1), time(), tzinfo=timezone.utc).timestamp()
        * 1000
    )
    series: dict[date, Decimal] = {}
    while start_ms < end_ms:
        try:
            response = httpx.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1d",
                    "startTime": str(start_ms),
                    "endTime": str(end_ms),
                    "limit": "1000",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            rows = json.loads(response.text)
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise QuoteFetchError(f"Binance klines failed for {symbol}: {exc}") from exc
        if not rows:
            break
        for row in rows:
            open_date = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date()
            series[open_date] = Decimal(str(row[4]))
        start_ms = rows[-1][0] + 86_400_000
        if len(rows) < 1000:
            break
    if not series:
        raise QuoteFetchError(f"Binance returned no klines for {symbol}")
    return series


def fetch_yfinance_history(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    try:
        import yfinance

        frame = yfinance.Ticker(ticker).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
    except Exception as exc:
        raise QuoteFetchError(f"yfinance history failed for {ticker}: {exc}") from exc
    if frame is None or frame.empty:
        raise QuoteFetchError(f"yfinance returned no history for {ticker}")
    series: dict[date, Decimal] = {}
    for stamp, close in frame["Close"].items():
        # yfinance emits a NaN Close for session dates without a trade
        # (illiquid FIIs). Decimal('NaN') then fails the NOT NULL constraint
        # on insert with an IntegrityError nothing catches — one bad bar
        # 500'd every history screen (hit live with an illiquid FII).
        # Skip the hole; carry-forward already bridges missing dates.
        if close is None or not math.isfinite(close):
            continue
        series[stamp.date()] = Decimal(str(close))
    if not series:
        raise QuoteFetchError(f"yfinance returned only empty bars for {ticker}")
    return series


def fetch_binance_usd_history(symbol: str, start: date, end: date) -> dict[date, Decimal]:
    """Daily USDT closes for a crypto symbol (e.g. ``BTCUSDT``) for the USD
    view of the Cripto section. ``symbol`` is already the full pair, kept as a
    distinct cache key so it never collides with the BRL ``{ticker}`` series."""
    start_ms = int(datetime.combine(start, time(), tzinfo=timezone.utc).timestamp() * 1000)
    end_ms = int(
        datetime.combine(end + timedelta(days=1), time(), tzinfo=timezone.utc).timestamp()
        * 1000
    )
    series: dict[date, Decimal] = {}
    while start_ms < end_ms:
        try:
            response = httpx.get(
                "https://api.binance.com/api/v3/klines",
                params={
                    "symbol": symbol,
                    "interval": "1d",
                    "startTime": str(start_ms),
                    "endTime": str(end_ms),
                    "limit": "1000",
                },
                timeout=10.0,
            )
            response.raise_for_status()
            rows = json.loads(response.text)
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise QuoteFetchError(f"Binance klines failed for {symbol}: {exc}") from exc
        if not rows:
            break
        for row in rows:
            open_date = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).date()
            series[open_date] = Decimal(str(row[4]))
        start_ms = rows[-1][0] + 86_400_000
        if len(rows) < 1000:
            break
    if not series:
        raise QuoteFetchError(f"Binance returned no USDT klines for {symbol}")
    return series


# Injectable so tests don't hit Binance; the real one downloads USDT klines.
BINANCE_USD_FETCHER = fetch_binance_usd_history


def fetch_b3_history(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    # yfinance carries full B3 history under the .SA suffix. brapi was
    # removed outright (not demoted to fallback): its free plan caps daily
    # history at 3 months (range=max returns 400), so a brapi fallback could
    # only fire when yfinance had already failed — and would then 400 too,
    # burning quota in exactly the failure path. See the module docstring.
    return fetch_yfinance_history(f"{ticker}.SA", start, end)


HISTORY_FETCHERS: dict[Market, Callable[[str, date, date], dict[date, Decimal]]] = {
    Market.br: fetch_b3_history,
    Market.us: fetch_yfinance_history,
    Market.crypto: fetch_binance_history,
}

HISTORY_SOURCES: dict[Market, str] = {
    # New BR rows are labelled with their real provenance; rows written
    # before 2026-07-11 carry "brapi-history" (same yfinance data — the
    # brapi leg never succeeded on the free plan). Nothing filters on the
    # source string; it is provenance metadata only.
    Market.br: "yfinance",
    Market.us: "yfinance",
    Market.crypto: "binance",
}
