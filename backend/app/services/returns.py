"""Per-segment cumulative return (TWR) series for the comparison chart.

Reuses the patrimony-history TWR engine: each segment is the same chained
daily return computed over a filtered subset of transactions (total /
Brasil / EUA / Cripto / Renda Fixa), sharing one closes/FX load so the
series stay aligned. Every series is rebased to 0% at the start of the
requested period so segments and benchmarks (CDI, IBOV, S&P500, BTC) can
be overlaid on one axis.

Renda fixa is valued at cost (no mark-to-market, per project scope), so
its return reflects only realized cash events; a warning is emitted.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Market
from app.models.transaction import Transaction
from app.services.benchmarks import benchmark_index_series
from app.services.history import (
    Granularity,
    compute_value_and_twr,
    load_market_data,
    load_usd_market_data,
)
from app.services.tesouro import parse_bond_ticker
from app.services.usd import to_usd_transactions

ZERO = Decimal("0")
HUNDRED = Decimal("100")

PERIODS = ("1M", "3M", "6M", "YTD", "1A", "MAX")


@dataclass
class SegmentDef:
    label: str
    predicate: Callable[[Transaction], bool]


SEGMENTS: dict[str, SegmentDef] = {
    "total": SegmentDef("Carteira Total", lambda tx: True),
    # Disjoint from "rf": Brazilian variable income only, so Tesouro (a BR
    # fixed-income asset) counts once, under "rf".
    "br": SegmentDef(
        "Brasil (B3)",
        lambda tx: tx.market is Market.br
        and tx.asset_class is not AssetClass.fixed_income,
    ),
    "us": SegmentDef("EUA (Avenue)", lambda tx: tx.market is Market.us),
    # market-based filter: all crypto regardless of custody (Binance hot +
    # Cold Wallet), since the TWR engine collapses custody by ticker.
    "crypto": SegmentDef("Cripto", lambda tx: tx.market is Market.crypto),
    "rf": SegmentDef(
        "Renda Fixa", lambda tx: tx.asset_class is AssetClass.fixed_income
    ),
}

BENCHMARK_LABELS = {"cdi": "CDI", "ibov": "IBOV", "sp500": "S&P 500", "btc": "BTC"}

PERIOD_GRANULARITY: dict[str, Granularity] = {
    "1M": "daily",
    "3M": "daily",
    "6M": "weekly",
    "YTD": "weekly",
    "1A": "weekly",
    "MAX": "monthly",
}

PERIOD_DAYS = {"1M": 30, "3M": 91, "6M": 182, "1A": 365}


@dataclass
class ReturnPoint:
    date: date
    return_pct: Decimal | None


@dataclass
class ReturnSeries:
    key: str
    label: str
    kind: str  # "segment" | "benchmark"
    points: list[ReturnPoint] = field(default_factory=list)


@dataclass
class ReturnsResult:
    period: str
    start: date | None
    series: list[ReturnSeries] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def build_returns(
    db: Session,
    segments: list[str],
    benchmarks: list[str],
    period: str = "MAX",
    currency: str = "BRL",
) -> ReturnsResult:
    period = period.upper()
    if period not in PERIODS:
        period = "MAX"
    currency = currency.upper()

    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return ReturnsResult(period=period, start=None)

    # USD view (EUA/Cripto): value in USD with FX=1, so the curve is the
    # asset's return in its native currency, free of USD/BRL drift.
    usd = currency == "USD"
    data = load_usd_market_data(db, transactions) if usd else load_market_data(db, transactions)
    if not data.days:
        return ReturnsResult(period=period, start=None, warnings=list(data.warnings))
    days = data.days
    window_start = _window_start_index(period, days)
    granularity = PERIOD_GRANULARITY[period]

    result = ReturnsResult(
        period=period, start=days[window_start], warnings=list(data.warnings)
    )

    for key in segments:
        seg = SEGMENTS.get(key)
        if seg is None:
            continue
        subset = [tx for tx in transactions if seg.predicate(tx)]
        if usd:
            # Reprice crypto to USD by each date's PTAX; US is already USD.
            subset = to_usd_transactions(db, subset)
        if not subset:
            result.series.append(ReturnSeries(key, seg.label, "segment"))
            continue
        _, twr = compute_value_and_twr(subset, data)
        points = _window_returns(list(twr), days, window_start, granularity)
        result.series.append(ReturnSeries(key, seg.label, "segment", points))
        if key == "rf":
            # Tesouro is now marked to market; only private fixed income
            # (CDB/LCI/LCA) still has no price source. Warn only when such a
            # bond actually holds value within the displayed window — a long-
            # closed CDB does not distort a recent window.
            private = [tx for tx in subset if parse_bond_ticker(tx.ticker) is None]
            if private:
                priv_totals, _ = compute_value_and_twr(private, data)
                if any(t > ZERO for t in priv_totals[window_start:]):
                    result.warnings.append(
                        "Renda fixa privada (CDB/LCI/LCA) valorada a custo; "
                        "rentabilidade não reflete marcação a mercado"
                    )

    if benchmarks:
        bm_series, bm_warnings = benchmark_index_series(db, days, tuple(benchmarks))
        result.warnings.extend(bm_warnings)
        for key in benchmarks:
            series = bm_series.get(key)
            if not series:
                continue
            label = BENCHMARK_LABELS.get(key, key.upper())
            points = _window_returns(series, days, window_start, granularity)
            result.series.append(ReturnSeries(key, label, "benchmark", points))

    return result


def _window_start_index(period: str, days: list[date]) -> int:
    if period == "MAX":
        return 0
    today = days[-1]
    if period == "YTD":
        cutoff = date(today.year, 1, 1)
    else:
        cutoff = today - timedelta(days=PERIOD_DAYS[period])
    for index, day in enumerate(days):
        if day >= cutoff:
            return index
    return len(days) - 1


def _window_returns(
    index_series: list[Decimal | None],
    days: list[date],
    window_start: int,
    granularity: Granularity,
) -> list[ReturnPoint]:
    # Rebase to the first positive value in the window so the series starts
    # at 0%; values before that (benchmark not yet listed) stay None.
    base: Decimal | None = None
    for i in range(window_start, len(days)):
        value = index_series[i]
        if value is not None and value > 0:
            base = value
            break

    points: list[ReturnPoint] = []
    for i in range(window_start, len(days)):
        value = index_series[i]
        if base is not None and value is not None and base > 0:
            points.append(ReturnPoint(days[i], (value / base - 1) * HUNDRED))
        else:
            points.append(ReturnPoint(days[i], None))
    return _sample(points, granularity)


def _sample(points: list[ReturnPoint], granularity: Granularity) -> list[ReturnPoint]:
    if granularity == "daily" or len(points) <= 1:
        return points
    if granularity == "weekly":
        def key(d: date) -> tuple:
            iso = d.isocalendar()
            return (iso.year, iso.week)
    else:
        def key(d: date) -> tuple:
            return (d.year, d.month)
    sampled: dict[tuple, ReturnPoint] = {}
    for point in points:
        sampled[key(point.date)] = point  # last point of each bucket wins
    out = list(sampled.values())
    # Keep the window's first point so every series visibly anchors at 0%.
    if out and out[0].date != points[0].date:
        out.insert(0, points[0])
    return out
