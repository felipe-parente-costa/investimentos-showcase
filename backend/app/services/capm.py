"""CAPM metrics (beta, Jensen's alpha, correlation) per portfolio segment.

For each segment we build a daily Time-Weighted return series (reusing the
patrimony engine over a filtered transaction subset), a benchmark daily
return series, and a daily risk-free series, then fit the excess returns:

    excess(t) = return(t) - risk_free(t)
    beta      = cov(excess_seg, excess_bm) / var(excess_bm)
    alpha     = mean(excess_seg) - beta * mean(excess_bm)   (Jensen, daily)

Alpha is reported annualised (compounded over 252 trading days).
Correlation is the Pearson correlation of the *raw* daily returns (no
risk-free), paired only over dates where both the segment and the
benchmark have a real return — the same rule as the correlation heatmap.

Segment / benchmark / risk-free pairings:
- Total Brasil -> IBOV / CDI  (mixes stocks and FIIs; beta less meaningful)
- Ações (stocks only)         -> IBOV / CDI
- FIIs                        -> IFIX (XFIX11 proxy) / CDI
- EUA                         -> S&P 500 / Treasury 3M (^IRX)

Renda Fixa and Cripto are intentionally excluded: alpha/beta do not apply
(RF has no market beta; the crypto book is ~all BTC so beta is trivially 1).
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Market
from app.models.transaction import Transaction
from app.services.benchmarks import (
    benchmark_index_series,
    fetch_cdi_rates,
)
from app.services.history import (
    compute_value_and_twr,
    fetch_yfinance_history,
    get_daily_closes,
    load_market_data,
)

TRADING_DAYS = 252
MIN_OBS = 20  # minimum paired daily returns to report a coefficient
PERIODS = ("6M", "1A", "2A", "MAX")
PERIOD_DAYS = {"6M": 182, "1A": 365, "2A": 730}
PERIOD_LABEL = {"6M": "6 meses", "1A": "1 ano", "2A": "2 anos", "MAX": "máximo"}


@dataclass
class CapmSegment:
    key: str
    label: str
    predicate: Callable[[Transaction], bool]
    benchmark: str  # key for benchmark_index_series
    benchmark_label: str
    risk_free: str  # "cdi" | "irx"
    risk_free_label: str
    note: str | None = None


def _is_br_variable(tx: Transaction) -> bool:
    return tx.market is Market.br and tx.asset_class is not AssetClass.fixed_income


SEGMENTS: list[CapmSegment] = [
    CapmSegment(
        "br_total",
        "Total Brasil",
        _is_br_variable,
        "ibov",
        "IBOV",
        "cdi",
        "CDI",
        note="Mistura ações e FIIs; beta menos interpretável.",
    ),
    CapmSegment(
        "br_stock",
        "Ações",
        lambda tx: tx.market is Market.br and tx.asset_class is AssetClass.stock,
        "ibov",
        "IBOV",
        "cdi",
        "CDI",
    ),
    CapmSegment(
        "br_fii",
        "FIIs",
        lambda tx: tx.market is Market.br and tx.asset_class is AssetClass.fii,
        "ifix",
        "IFIX (proxy XFIX11, c/ taxa adm.)",
        "cdi",
        "CDI",
    ),
    CapmSegment(
        "us",
        "EUA",
        lambda tx: tx.market is Market.us,
        "sp500",
        "S&P 500",
        "irx",
        "Treasury 3M (^IRX)",
    ),
]


@dataclass
class CapmMetrics:
    key: str
    label: str
    benchmark_label: str
    risk_free_label: str
    period: str
    period_label: str
    frequency: str = "diária"
    beta: float | None = None
    alpha_annual_pct: float | None = None
    correlation: float | None = None
    observations: int = 0
    note: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class CapmResult:
    period: str
    period_label: str
    frequency: str = "diária"
    segments: list[CapmMetrics] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- pure math (no DB) -------------------------------------------------------


def _capm_fit(
    seg_excess: dict[date, float], bm_excess: dict[date, float]
) -> tuple[float, float, int] | None:
    """Returns (beta, daily_alpha, n) from an OLS fit of segment excess
    returns on benchmark excess returns, paired over common dates."""
    common = sorted(seg_excess.keys() & bm_excess.keys())
    n = len(common)
    if n < MIN_OBS:
        return None
    s = [seg_excess[d] for d in common]
    m = [bm_excess[d] for d in common]
    mean_s = sum(s) / n
    mean_m = sum(m) / n
    var_m = sum((x - mean_m) ** 2 for x in m)
    if var_m <= 0:
        return None
    cov = sum((si - mean_s) * (mi - mean_m) for si, mi in zip(s, m))
    beta = cov / var_m
    alpha_daily = mean_s - beta * mean_m
    return beta, alpha_daily, n


def _annualize_alpha(alpha_daily: float) -> float:
    return ((1 + alpha_daily) ** TRADING_DAYS - 1) * 100


def _pearson(a: dict[date, float], b: dict[date, float]) -> float | None:
    common = sorted(a.keys() & b.keys())
    if len(common) < MIN_OBS:
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
    return max(-1.0, min(1.0, r))


def _excess(returns: dict[date, float], rf: dict[date, float]) -> dict[date, float]:
    """Excess returns. With no risk-free series, excess == raw return (the
    caller adds an explicit risk-free=0 warning)."""
    if not rf:
        return dict(returns)
    return {d: returns[d] - rf[d] for d in returns.keys() & rf.keys()}


# --- return series builders --------------------------------------------------


def _segment_daily_returns(
    totals: list[Decimal], twr: list[Decimal], days: list[date]
) -> dict[date, float]:
    """Daily TWR returns, only on days the segment actually held value on
    both ends (so pre-existence flat days inject no spurious zero returns)."""
    out: dict[date, float] = {}
    for i in range(1, len(days)):
        if totals[i - 1] > 0 and totals[i] > 0 and twr[i - 1] > 0:
            out[days[i]] = float(twr[i] / twr[i - 1]) - 1
    return out


def _index_daily_returns(
    index: list[Decimal | None], days: list[date]
) -> dict[date, float]:
    out: dict[date, float] = {}
    for i in range(1, len(days)):
        prev, cur = index[i - 1], index[i]
        if prev is not None and cur is not None and prev > 0:
            out[days[i]] = float(cur / prev) - 1
    return out


def _cdi_daily_returns(db: Session, days: list[date]) -> dict[date, float]:
    rates = get_daily_closes(
        db,
        "CDI",
        None,
        days[0],
        days[-1],
        fetcher=fetch_cdi_rates,
        currency="BRL",
        source="sgs",
    )
    # SGS series 12 is already the daily CDI rate in percent.
    return {d: float(r) / 100 for d, r in rates.items()}


def _irx_daily_returns(
    db: Session, days: list[date]
) -> tuple[dict[date, float], list[str]]:
    """Daily risk-free from ^IRX (13-week T-bill, annualised yield in %),
    converted to a per-trading-day rate. Empty + warning if unavailable —
    never silently zero."""
    series = get_daily_closes(
        db,
        "^IRX",
        None,
        days[0],
        days[-1],
        fetcher=fetch_yfinance_history,
        currency="USD",
        source="yfinance-history",
    )
    if not series:
        return {}, ["Treasury 3M (^IRX) indisponível; risk-free=0 assumido"]
    out: dict[date, float] = {}
    for d, annual in series.items():
        annual_f = float(annual) / 100
        out[d] = (1 + annual_f) ** (1 / TRADING_DAYS) - 1
    return out, []


def _window_start(period: str, days: list[date]) -> date:
    if period == "MAX":
        return days[0]
    return days[-1] - timedelta(days=PERIOD_DAYS[period])


def _restrict(returns: dict[date, float], start: date) -> dict[date, float]:
    return {d: r for d, r in returns.items() if d >= start}


# --- orchestrator ------------------------------------------------------------


def build_capm(db: Session, period: str = "1A") -> CapmResult:
    period = period.upper()
    if period not in PERIODS:
        period = "1A"
    result = CapmResult(period=period, period_label=PERIOD_LABEL[period])

    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return result

    data = load_market_data(db, transactions)
    days = data.days
    start = _window_start(period, days)

    # Only fetch the benchmarks/risk-frees that a populated segment needs, so
    # an empty book (e.g. no US holdings) triggers no external call.
    subsets = {
        seg.key: [tx for tx in transactions if seg.predicate(tx)] for seg in SEGMENTS
    }
    active = [seg for seg in SEGMENTS if subsets[seg.key]]

    needed_bm = tuple({seg.benchmark for seg in active})
    bm_returns: dict[str, dict[date, float]] = {}
    if needed_bm:
        bm_index, bm_warnings = benchmark_index_series(db, days, needed_bm)
        result.warnings.extend(bm_warnings)
        bm_returns = {
            key: _index_daily_returns(series, days) for key, series in bm_index.items()
        }

    rf_returns: dict[str, dict[date, float]] = {}
    needed_rf = {seg.risk_free for seg in active}
    if "cdi" in needed_rf:
        rf_returns["cdi"] = _cdi_daily_returns(db, days)
    if "irx" in needed_rf:
        rf_returns["irx"], irx_warnings = _irx_daily_returns(db, days)
        result.warnings.extend(irx_warnings)

    for seg in SEGMENTS:
        metrics = CapmMetrics(
            key=seg.key,
            label=seg.label,
            benchmark_label=seg.benchmark_label,
            risk_free_label=seg.risk_free_label,
            period=period,
            period_label=PERIOD_LABEL[period],
            note=seg.note,
        )
        subset = subsets[seg.key]
        if not subset:
            metrics.warnings.append("Sem posições neste segmento.")
            result.segments.append(metrics)
            continue

        totals, twr = compute_value_and_twr(subset, data)
        seg_ret = _restrict(_segment_daily_returns(totals, twr, days), start)
        bm_ret = _restrict(bm_returns.get(seg.benchmark, {}), start)
        rf_ret = _restrict(rf_returns.get(seg.risk_free, {}), start)

        if not bm_ret:
            metrics.warnings.append(
                f"Benchmark {seg.benchmark_label} indisponível no período."
            )
            result.segments.append(metrics)
            continue
        if not rf_ret:
            metrics.warnings.append(
                f"Risk-free {seg.risk_free_label} indisponível; "
                "excedente calculado com risk-free=0."
            )

        metrics.correlation = _pearson(seg_ret, bm_ret)
        fit = _capm_fit(_excess(seg_ret, rf_ret), _excess(bm_ret, rf_ret))
        if fit is None:
            metrics.warnings.append(
                f"Retornos pareados insuficientes (mín. {MIN_OBS}) para alfa/beta."
            )
        else:
            beta, alpha_daily, n = fit
            metrics.beta = beta
            metrics.alpha_annual_pct = _annualize_alpha(alpha_daily)
            metrics.observations = n

        result.segments.append(metrics)

    return result
