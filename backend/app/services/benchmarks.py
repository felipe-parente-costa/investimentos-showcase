"""Benchmark series for performance comparison, all as index base 100.

- CDI: daily rate from the Central Bank SGS API (series 12), compounded.
- IBOV: ^BVSP closes via yfinance (already in BRL).
- S&P500: ^GSPC closes via yfinance, converted to BRL with the day's PTAX
  so the comparison with the BRL portfolio is currency-consistent.
- BTC: BTCBRL daily klines from Binance (shared cache with the BTC
  position history).
- IPCA+6: monthly IPCA (SGS series 433) spread evenly across the calendar
  days of its reference month, compounded with a fixed +6% a.a. add-on
  (252 business-day convention, same base as CDI). Frozen (no IPCA accrual,
  add-on keeps accruing) during the current month until BCB publishes it.
- Dólar+5: day-over-day USD/BRL PTAX variation compounded with a fixed
  +5% a.a. add-on (same 252 business-day convention). The add-on only
  accrues on business days; weekends carry the index flat.

Series are cached in the quotes table under their own tickers and carried
forward over non-trading days, like position closes.
"""

import calendar
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

import httpx
from sqlalchemy.orm import Session

from app.models.enums import Market
from app.services.fx import get_usd_brl_series
from app.services.history import (
    Granularity,
    _carry_forward,
    build_patrimony_history,
    fetch_yfinance_history,
    get_daily_closes,
)
from app.services.quotes import QuoteFetchError

ZERO = Decimal("0")
HUNDRED = Decimal("100")
BUSINESS_DAYS_PER_YEAR = 252
SGS_CDI_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.12/dados"
SGS_IPCA_URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.433/dados"

BenchmarkName = Literal["cdi", "ibov", "ifix", "sp500", "btc", "ipca6", "dolar5"]


@dataclass
class PerformancePoint:
    date: date
    portfolio: Decimal
    benchmarks: dict[str, Decimal | None] = field(default_factory=dict)


@dataclass
class PerformanceResult:
    points: list[PerformancePoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fetch_sgs_series(url: str, label: str, start: date, end: date) -> dict[date, Decimal]:
    params = {
        "formato": "json",
        "dataInicial": start.strftime("%d/%m/%Y"),
        "dataFinal": end.strftime("%d/%m/%Y"),
    }
    try:
        response = httpx.get(url, params=params, timeout=10.0)
        response.raise_for_status()
        rows = json.loads(response.text)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise QuoteFetchError(f"SGS {label} request failed: {exc}") from exc
    rates: dict[date, Decimal] = {}
    for row in rows:
        try:
            when = datetime.strptime(row["data"], "%d/%m/%Y").date()
            rates[when] = Decimal(str(row["valor"]))
        except (KeyError, ValueError):
            continue
    if not rates:
        raise QuoteFetchError(f"SGS returned no {label} rates")
    return rates


def fetch_cdi_rates(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    return _fetch_sgs_series(SGS_CDI_URL, "CDI", start, end)


def fetch_ipca_rates(ticker: str, start: date, end: date) -> dict[date, Decimal]:
    """Monthly IPCA variation (%), one value per month dated the first day
    of the reference month (SGS series 433)."""
    return _fetch_sgs_series(SGS_IPCA_URL, "IPCA", start, end)


def _annualized_daily_factor(annual_pct: Decimal, day_count: int = BUSINESS_DAYS_PER_YEAR) -> Decimal:
    """Daily compounding factor for a fixed annual rate (e.g. 6 for +6%
    a.a.), using the 252 business-day convention (same base as CDI)."""
    daily = (1.0 + float(annual_pct) / 100.0) ** (1.0 / day_count)
    return Decimal(str(daily))


def _monthly_daily_factor(monthly_pct: Decimal, day: date) -> Decimal:
    """Daily compounding factor equivalent to `monthly_pct`, spread evenly
    across the calendar days of `day`'s month."""
    days_in_month = calendar.monthrange(day.year, day.month)[1]
    daily = (1.0 + float(monthly_pct) / 100.0) ** (1.0 / days_in_month)
    return Decimal(str(daily))


def _ipca_plus_index(
    ipca_monthly: dict[date, Decimal], days: list[date], addon_annual_pct: Decimal
) -> list[Decimal | None]:
    if not ipca_monthly:
        return [None] * len(days)
    monthly_factor = {
        date(when.year, when.month, 1): _monthly_daily_factor(rate, when)
        for when, rate in ipca_monthly.items()
    }
    addon = _annualized_daily_factor(addon_annual_pct)
    factor = Decimal("1")
    current: Decimal | None = None
    out: list[Decimal | None] = []
    for day in days:
        month_key = date(day.year, day.month, 1)
        if month_key in monthly_factor:
            current = monthly_factor[month_key]
        if current is None:
            out.append(None)
            continue
        # IPCA spreads over every calendar day of the month (it is a
        # calendar-time figure); the +6% a.a. add-on accrues only on
        # business days (252/year convention).
        factor *= current
        if day.weekday() < 5:
            factor *= addon
        out.append(HUNDRED * factor)
    return out


def _fx_plus_index(
    fx_series: dict[date, Decimal], days: list[date], addon_annual_pct: Decimal
) -> list[Decimal | None]:
    if not fx_series:
        return [None] * len(days)
    addon = _annualized_daily_factor(addon_annual_pct)
    carried = _carry_forward(fx_series, days)
    factor = Decimal("1")
    prev: Decimal | None = None
    out: list[Decimal | None] = []
    for day, value in zip(days, carried):
        if value is None:
            out.append(None)
            prev = None
            continue
        if prev is not None:
            factor *= value / prev
            if day.weekday() < 5:
                factor *= addon
        prev = value
        out.append(HUNDRED * factor)
    return out


ALL_BENCHMARKS = ("cdi", "ibov", "sp500", "btc")


def benchmark_index_series(
    db: Session, days: list[date], keys: tuple[str, ...] = ALL_BENCHMARKS
) -> tuple[dict[str, list[Decimal | None]], list[str]]:
    """Daily benchmark indexes (base 100 at the series start) aligned to
    `days`, computed only for the requested `keys`. Each entry is None
    before the benchmark's first data point; callers rebase to their own
    window."""
    start, end = days[0], days[-1]
    benchmarks: dict[str, list[Decimal | None]] = {}
    warnings: list[str] = []

    if "cdi" in keys:
        cdi_rates = get_daily_closes(
            db, "CDI", None, start, end, fetcher=fetch_cdi_rates, currency="BRL", source="sgs"
        )
        if cdi_rates:
            benchmarks["cdi"] = _compound_index(cdi_rates, days)
        else:
            warnings.append("CDI indisponível (SGS)")

    if "ibov" in keys:
        ibov = get_daily_closes(
            db,
            "^BVSP",
            None,
            start,
            end,
            fetcher=fetch_yfinance_history,
            currency="BRL",
            source="yfinance-history",
        )
        if ibov:
            benchmarks["ibov"] = _price_index(_carry_forward(ibov, days))
        else:
            warnings.append("IBOV indisponível (yfinance)")

    if "ifix" in keys:
        # No free deep series for the IFIX index itself (yfinance has none;
        # brapi's free plan caps history at 3 months). XFIX11 (Trend ETF
        # IFIX) is the sanctioned proxy: a deep daily series that tracks the
        # index. It carries an expense ratio, so an alpha computed against it
        # embeds a small slack vs the pure index — labelled in the UI.
        ifix = get_daily_closes(
            db,
            "XFIX11.SA",
            None,
            start,
            end,
            fetcher=fetch_yfinance_history,
            currency="BRL",
            source="yfinance-history",
        )
        if ifix:
            benchmarks["ifix"] = _price_index(_carry_forward(ifix, days))
        else:
            warnings.append("IFIX (proxy XFIX11) indisponível (yfinance)")

    if "sp500" in keys:
        sp500 = get_daily_closes(
            db,
            "^GSPC",
            None,
            start,
            end,
            fetcher=fetch_yfinance_history,
            currency="USD",
            source="yfinance-history",
        )
        fx_series = get_usd_brl_series(db, start, end)
        if sp500 and fx_series:
            fx = _carry_forward(fx_series, days)
            closes = _carry_forward(sp500, days)
            in_brl = [
                c * r if c is not None and r is not None else None
                for c, r in zip(closes, fx)
            ]
            benchmarks["sp500"] = _price_index(in_brl)
        else:
            warnings.append("S&P500 em BRL indisponível (yfinance/PTAX)")

    if "btc" in keys:
        btc = get_daily_closes(db, "BTC", Market.crypto, start, end)
        if btc:
            benchmarks["btc"] = _price_index(_carry_forward(btc, days))
        else:
            warnings.append("BTC indisponível (Binance)")

    if "ipca6" in keys:
        ipca_rates = get_daily_closes(
            db, "IPCA", None, start, end, fetcher=fetch_ipca_rates, currency="BRL", source="sgs"
        )
        if ipca_rates:
            benchmarks["ipca6"] = _ipca_plus_index(ipca_rates, days, Decimal("6"))
        else:
            warnings.append("IPCA+6 indisponível (SGS)")

    if "dolar5" in keys:
        fx_series = get_usd_brl_series(db, start, end)
        if fx_series:
            benchmarks["dolar5"] = _fx_plus_index(fx_series, days, Decimal("5"))
        else:
            warnings.append("Dólar+5 indisponível (PTAX)")

    return benchmarks, warnings


def build_performance(
    db: Session, granularity: Granularity = "daily"
) -> PerformanceResult:
    history = build_patrimony_history(db, granularity="daily")
    result = PerformanceResult(warnings=list(history.warnings))
    if not history.points:
        return result

    days = [p.date for p in history.points]
    benchmarks, bm_warnings = benchmark_index_series(db, days)
    result.warnings.extend(bm_warnings)

    for index, point in enumerate(history.points):
        result.points.append(
            PerformancePoint(
                date=point.date,
                portfolio=point.twr_index,
                benchmarks={
                    name: series[index] for name, series in benchmarks.items()
                },
            )
        )
    result.points = _sample(result.points, granularity)
    return result


def _price_index(values: list[Decimal | None]) -> list[Decimal | None]:
    base: Decimal | None = None
    out: list[Decimal | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        if base is None:
            base = value
        out.append(HUNDRED * value / base)
    return out


def _compound_index(rates: dict[date, Decimal], days: list[date]) -> list[Decimal | None]:
    factor = Decimal("1")
    out: list[Decimal | None] = []
    for day in days:
        rate = rates.get(day)
        if rate is not None:
            factor *= 1 + rate / HUNDRED
        out.append(HUNDRED * factor)
    return out


def _sample(
    points: list[PerformancePoint], granularity: Granularity
) -> list[PerformancePoint]:
    if granularity == "daily" or not points:
        return points
    if granularity == "weekly":
        def key(d: date) -> tuple:
            iso = d.isocalendar()
            return (iso.year, iso.week)
    else:
        def key(d: date) -> tuple:
            return (d.year, d.month)
    sampled: dict[tuple, PerformancePoint] = {}
    for point in points:
        sampled[key(point.date)] = point
    return list(sampled.values())
