"""Correlation matrix of daily returns between portfolio assets.

Uses only historical closes already cached in the quotes table (no
external calls). Returns are computed in each asset's native currency
(BR/crypto in BRL, US in USD) so the matrix measures co-movement of the
assets themselves, not a shared USD/BRL factor. Pearson correlation is
computed pairwise over the dates where both assets have an actual close,
so differing trading calendars don't inject spurious zero-return days.

Fixed income and any ticker without enough cached closes in the window
are excluded (reported as warnings).
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Market
from app.models.transaction import Transaction
from app.services.history import _cached_closes
from app.services.portfolio import compute_positions

MIN_OVERLAP = 5  # minimum shared daily returns to report a coefficient
PERIOD_DAYS = {"3M": 91, "6M": 182, "1A": 365}
PERIODS = ("3M", "6M", "1A", "MAX")
SEGMENT_MARKET = {"br": Market.br, "us": Market.us, "crypto": Market.crypto}


@dataclass
class CorrelationResult:
    period: str
    segment: str | None
    tickers: list[str] = field(default_factory=list)
    matrix: list[list[float | None]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_correlation(
    db: Session, period: str = "1A", segment: str | None = None
) -> CorrelationResult:
    period = period.upper()
    if period not in PERIODS:
        period = "1A"
    market = SEGMENT_MARKET.get(segment) if segment else None

    result = CorrelationResult(period=period, segment=segment)

    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return result

    positions = compute_positions(transactions).positions
    end = datetime.now(timezone.utc).date()
    start = _window_start(period, end)

    returns: dict[str, dict[date, float]] = {}
    # One series per ticker: a ticker held across custodies (hot/cold) shares a
    # single price series, so dedupe by ticker.
    for position in sorted(positions.values(), key=lambda p: p.ticker):
        ticker = position.ticker
        if ticker in returns or not position.is_open:
            continue
        if market is not None and position.market is not market:
            continue
        if position.asset_class is AssetClass.fixed_income:
            result.warnings.append(f"{ticker}: renda fixa não tem cotação para correlação")
            continue
        series = _cached_closes(db, ticker, start, end)
        ticker_returns = _daily_returns(series)
        if len(ticker_returns) < MIN_OVERLAP:
            result.warnings.append(
                f"{ticker}: cotações insuficientes no período para correlação"
            )
            continue
        returns[ticker] = ticker_returns

    tickers = list(returns)
    matrix: list[list[float | None]] = []
    for row_ticker in tickers:
        row: list[float | None] = []
        for col_ticker in tickers:
            if row_ticker == col_ticker:
                row.append(1.0)
            else:
                row.append(_pearson(returns[row_ticker], returns[col_ticker]))
        matrix.append(row)

    result.tickers = tickers
    result.matrix = matrix
    return result


def _window_start(period: str, end: date) -> date:
    if period == "MAX":
        return date(2000, 1, 1)
    return end - timedelta(days=PERIOD_DAYS[period])


def _daily_returns(closes: dict[date, object]) -> dict[date, float]:
    items = sorted(closes.items())
    out: dict[date, float] = {}
    for index in range(1, len(items)):
        previous = float(items[index - 1][1])
        current = float(items[index][1])
        if previous > 0:
            out[items[index][0]] = current / previous - 1
    return out


def _pearson(a: dict[date, float], b: dict[date, float]) -> float | None:
    common = sorted(a.keys() & b.keys())
    if len(common) < MIN_OVERLAP:
        return None
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0 or var_y <= 0:
        return None
    r = cov / (var_x**0.5 * var_y**0.5)
    return max(-1.0, min(1.0, r))  # clamp floating-point drift to [-1, 1]
