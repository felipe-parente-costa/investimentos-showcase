"""Portfolio risk analytics: the "Risco" section (replaces Correlação, which
now lives inside it as one of its analyses via the existing /portfolio/
correlation endpoint — this module does not touch that one).

Everything price-based (volatility, VaR/CVaR, drawdown, beta, sector/
sub-setor volatility and risk contribution) is derived from two existing,
already-computed series, never refit here:

- The whole-portfolio daily TWR index from `history.build_patrimony_history`
  — the same series behind the Dashboard's "Rentabilidade total (TWR)".
- Per-ticker cached closes via `history._cached_closes` (the same helper
  `correlation.py` uses), for the sector/sub-setor basket series.

Renda fixa privada (CDB/LCI/LCA) is marked at cost, not mark-to-market —
volatility/VaR/beta on it would be fabricated risk, so it is deliberately
excluded from every price-based calculation here and gets its own, different
lens instead (concentration by indexer/instituição, see `fixed_income_risk`).
Tesouro Direto *is* mark-to-market (PU history) and participates normally.

Every ratio/ percentage in this module is a plain Python float (statistics,
not money); only R$ amounts stay Decimal, per CLAUDE.md.
"""

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Custody, Indexer, Market
from app.models.transaction import Transaction
from app.services.assets import get_asset_meta
from app.services.benchmarks import benchmark_index_series
from app.services.capm import _cdi_daily_returns, _index_daily_returns, build_capm
from app.services.fx import FxResult, get_usd_brl
from app.services.history import HistoryPoint, _cached_closes, build_patrimony_history
from app.services.indexer import resolve_indexer
from app.services.portfolio import compute_positions
from app.services.quotes import get_quote
from app.services.segments import segment_of
from app.services.tesouro import parse_bond_ticker

ZERO = Decimal("0")
CENTS = Decimal("0.01")

TRADING_DAYS = 252
MIN_OBS = 20  # minimum daily observations to report a statistic (matches capm.py)
MIN_BASKET_OVERLAP = 10  # minimum shared dates to correlate/covary two baskets

PERIODS = ("3M", "6M", "1A", "2A", "MAX")
PERIOD_DAYS = {"3M": 91, "6M": 182, "1A": 365, "2A": 730}
PERIOD_LABEL = {
    "3M": "3 meses",
    "6M": "6 meses",
    "1A": "1 ano",
    "2A": "2 anos",
    "MAX": "máximo",
}

# capm.py's own PERIODS has no "3M" (see app/services/capm.py); stress
# scenarios need a CAPM-compatible window to fetch betas from.
_CAPM_PERIOD_FALLBACK = {"3M": "6M"}

GROUP_LEVELS = ("sector", "subsector")
NO_CLASS_LABEL = "Sem classificação"
NO_SUBSECTOR_SUFFIX = " (sem sub-setor)"
SUBSECTOR_ELIGIBLE = (AssetClass.stock, AssetClass.etf)

Z_95 = 1.6448536269514722  # one-tailed 95% normal quantile


# --- output dataclasses -------------------------------------------------------


@dataclass
class RiskOverall:
    volatility_annual_pct: float | None = None
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown_pct: float | None = None
    max_drawdown_date: date | None = None
    max_drawdown_duration_days: int | None = None
    current_drawdown_pct: float | None = None
    current_drawdown_days: int | None = None
    var_hist_95_pct: float | None = None
    var_hist_95_brl: Decimal | None = None
    var_hist_99_pct: float | None = None
    var_hist_99_brl: Decimal | None = None
    var_parametric_95_pct: float | None = None
    cvar_hist_95_pct: float | None = None
    cvar_hist_95_brl: Decimal | None = None
    skewness: float | None = None
    kurtosis_excess: float | None = None
    beta_ibov: float | None = None
    beta_sp500: float | None = None
    tracking_error_cdi_pct: float | None = None
    observations: int = 0
    hhi_position: float | None = None
    effective_positions: float | None = None
    top5_concentration_pct: float | None = None
    hhi_institution: float | None = None
    hhi_segment: float | None = None
    diversification_ratio: float | None = None
    usd_direct_exposure_pct: float | None = None
    total_value_brl: Decimal | None = None


@dataclass
class RiskPoint:
    date: date
    value: float


@dataclass
class RiskGroup:
    key: str
    label: str
    weight_pct: float
    market_value_brl: Decimal
    position_count: int
    priced_position_count: int
    volatility_annual_pct: float | None = None
    risk_contribution_pct: float | None = None
    avg_intra_correlation: float | None = None


@dataclass
class GroupCorrelation:
    labels: list[str] = field(default_factory=list)
    matrix: list[list[float | None]] = field(default_factory=list)


@dataclass
class StressScenario:
    key: str
    label: str
    shock_pct: float
    exposure_brl: Decimal
    beta: float
    beta_note: str | None
    impact_brl: Decimal | None
    impact_pct: float | None


@dataclass
class IndexerSlice:
    key: str
    label: str
    value_brl: Decimal
    weight_pct: float


@dataclass
class InstitutionSlice:
    label: str
    value_brl: Decimal
    weight_pct: float


@dataclass
class FixedIncomeRisk:
    total_brl: Decimal
    by_indexer: list[IndexerSlice] = field(default_factory=list)
    by_institution: list[InstitutionSlice] = field(default_factory=list)
    hhi_institution: float | None = None


@dataclass
class RiskResult:
    period: str
    period_label: str
    group_by: str
    overall: RiskOverall = field(default_factory=RiskOverall)
    drawdown_series: list[RiskPoint] = field(default_factory=list)
    rolling_volatility_21d: list[RiskPoint] = field(default_factory=list)
    rolling_volatility_63d: list[RiskPoint] = field(default_factory=list)
    daily_returns: list[RiskPoint] = field(default_factory=list)
    groups: list[RiskGroup] = field(default_factory=list)
    group_correlation: GroupCorrelation = field(default_factory=GroupCorrelation)
    risk_universe_coverage_pct: float | None = None
    stress_scenarios: list[StressScenario] = field(default_factory=list)
    fixed_income: FixedIncomeRisk | None = None
    warnings: list[str] = field(default_factory=list)


# --- pure math -----------------------------------------------------------


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs)


def _sample_std(xs: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return math.sqrt(var)


def _annualize_return(mean_daily: float) -> float:
    return (1 + mean_daily) ** TRADING_DAYS - 1


def _covariance(a: dict[date, float], b: dict[date, float]) -> tuple[float, int] | None:
    common = sorted(a.keys() & b.keys())
    n = len(common)
    if n < MIN_BASKET_OVERLAP:
        return None
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    mean_x, mean_y = _mean(xs), _mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / (n - 1)
    return cov, n


def _pearson(a: dict[date, float], b: dict[date, float]) -> float | None:
    cov = _covariance(a, b)
    if cov is None:
        return None
    # Std over the *paired* dates only (matches cov's window), not each
    # series' full history — otherwise correlation could exceed 1 in
    # magnitude when the two series' unpaired tails differ in volatility.
    common = sorted(a.keys() & b.keys())
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    std_x, std_y = _sample_std(xs), _sample_std(ys)
    if not std_x or not std_y:
        return None
    r = cov[0] / (std_x * std_y)
    return max(-1.0, min(1.0, r))


def _variance(xs_by_date: dict[date, float]) -> float | None:
    xs = list(xs_by_date.values())
    std = _sample_std(xs)
    return std * std if std is not None else None


@dataclass
class DrawdownStats:
    worst_pct: float
    worst_date: date | None
    worst_duration_days: int | None  # peak-to-trough of the worst episode
    current_underwater_days: int  # days since the window's running peak


def _max_drawdown(index: list[float], dates: list[date]) -> DrawdownStats:
    peak = index[0]
    peak_date = dates[0]
    worst = 0.0
    worst_date: date | None = None
    worst_peak_date: date | None = None
    for value, day in zip(index, dates):
        if value >= peak:
            peak = value
            peak_date = day
        drawdown = value / peak - 1 if peak > 0 else 0.0
        if drawdown < worst:
            worst = drawdown
            worst_date = day
            worst_peak_date = peak_date
    worst_duration = (
        (worst_date - worst_peak_date).days
        if worst_date is not None and worst_peak_date is not None
        else None
    )
    # peak_date/peak, after the loop, are the window's running (all-time-
    # high) peak — the current drawdown's own start, regardless of whether
    # it turned out to be the worst one.
    current_underwater = (dates[-1] - peak_date).days
    return DrawdownStats(worst, worst_date, worst_duration, current_underwater)


def _drawdown_series(index: list[float], dates: list[date]) -> list[RiskPoint]:
    peak = index[0]
    points: list[RiskPoint] = []
    for value, day in zip(index, dates):
        if value > peak:
            peak = value
        drawdown = value / peak - 1 if peak > 0 else 0.0
        points.append(RiskPoint(day, drawdown))
    return points


def _rolling_volatility(
    returns: dict[date, float], dates: list[date], window: int
) -> list[RiskPoint]:
    ordered = [(d, returns[d]) for d in dates if d in returns]
    points: list[RiskPoint] = []
    for i in range(window - 1, len(ordered)):
        chunk = [r for _, r in ordered[i - window + 1 : i + 1]]
        std = _sample_std(chunk)
        if std is not None:
            points.append(RiskPoint(ordered[i][0], std * math.sqrt(TRADING_DAYS)))
    return points


def _skew_kurtosis(xs: list[float]) -> tuple[float | None, float | None]:
    n = len(xs)
    if n < MIN_OBS:
        return None, None
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / n  # population moments (descriptive stat)
    std = math.sqrt(var)
    if std == 0:
        return None, None
    skew = (sum((x - m) ** 3 for x in xs) / n) / std**3
    kurt = (sum((x - m) ** 4 for x in xs) / n) / std**4 - 3
    return skew, kurt


def _historical_var_cvar(
    xs: list[float], confidence: float
) -> tuple[float | None, float | None]:
    """Historical VaR/CVaR (1-day) as a NEGATIVE percentage (a loss), from
    the empirical quantile of the return distribution."""
    n = len(xs)
    if n < MIN_OBS:
        return None, None
    ordered = sorted(xs)
    idx = int((1 - confidence) * n)
    idx = max(0, min(idx, n - 1))
    var = ordered[idx]
    tail = ordered[: idx + 1]
    cvar = _mean(tail) if tail else var
    return var, cvar


def _hhi(weights: list[float]) -> float | None:
    if not weights:
        return None
    return sum(w * w for w in weights)


# --- data assembly ---------------------------------------------------------


@dataclass
class ValuedPosition:
    ticker: str
    asset_name: str | None
    indexer: Indexer | None
    custody: Custody | None
    market: Market
    asset_class: AssetClass
    institution: str | None
    sector: str | None
    industry: str | None
    market_value_brl: Decimal


def _to_brl(
    amount: Decimal,
    currency: str,
    usd_rate: Callable[[], FxResult | None],
    warnings: list[str],
    ticker: str,
) -> Decimal | None:
    if currency == "BRL":
        return amount
    if currency == "USD":
        fx = usd_rate()
        if fx is not None:
            return amount * fx.rate
        warnings.append(f"{ticker}: USD/BRL indisponível; excluído do cálculo de risco")
        return None
    warnings.append(f"{ticker}: sem fonte de câmbio para {currency}")
    return None


def _valued_positions(
    db: Session, transactions: list[Transaction]
) -> tuple[list[ValuedPosition], list[str]]:
    warnings: list[str] = []
    computed = compute_positions(transactions)
    warnings.extend(computed.warnings)

    fx: FxResult | None = None
    fx_attempted = False

    def usd_rate() -> FxResult | None:
        nonlocal fx, fx_attempted
        if not fx_attempted:
            fx_attempted = True
            fx = get_usd_brl(db, datetime.now(timezone.utc).date())
        return fx

    out: list[ValuedPosition] = []
    for position in computed.positions.values():
        if not position.is_open:
            continue
        meta = get_asset_meta(db, position.ticker, position.market, position.asset_class)
        quote = get_quote(
            db, position.ticker, position.market, position.asset_class, live=False
        )
        if quote is not None:
            market_value = position.quantity * quote.price
            currency = quote.currency
        else:
            market_value = position.total_cost
            currency = position.currency
        market_value_brl = _to_brl(
            market_value, currency, usd_rate, warnings, position.ticker
        )
        if market_value_brl is None:
            continue
        out.append(
            ValuedPosition(
                ticker=position.ticker,
                asset_name=position.asset_name,
                indexer=position.indexer,
                custody=position.custody,
                market=position.market,
                asset_class=position.asset_class,
                institution=position.institution,
                sector=meta.sector,
                industry=meta.industry,
                market_value_brl=market_value_brl,
            )
        )
    return out, warnings


def _window_start(period: str, end: date) -> date:
    if period == "MAX":
        return date(2000, 1, 1)
    return end - timedelta(days=PERIOD_DAYS[period])


def _portfolio_returns(points: list[HistoryPoint]) -> dict[date, float]:
    """Daily TWR returns of the whole consolidated portfolio, guarded the
    same way capm.py guards a segment's: only days where both ends actually
    held value, so the pre-existence flat lead-in injects no fake returns."""
    out: dict[date, float] = {}
    for i in range(1, len(points)):
        prev, cur = points[i - 1], points[i]
        if prev.total_brl > 0 and cur.total_brl > 0 and prev.twr_index > 0:
            out[cur.date] = float(cur.twr_index / prev.twr_index) - 1
    return out


def _restrict(returns: dict[date, float], start: date) -> dict[date, float]:
    return {d: r for d, r in returns.items() if d >= start}


def _weighted_basket(
    returns_by_ticker: dict[str, dict[date, float]], weights: dict[str, float]
) -> dict[date, float]:
    all_dates: set[date] = set()
    for series in returns_by_ticker.values():
        all_dates |= series.keys()
    out: dict[date, float] = {}
    for d in all_dates:
        num = 0.0
        den = 0.0
        for ticker, series in returns_by_ticker.items():
            if d in series:
                w = weights.get(ticker, 0.0)
                num += w * series[d]
                den += w
        if den > 0:
            out[d] = num / den
    return out


def _daily_returns_from_closes(closes: dict[date, Decimal]) -> dict[date, float]:
    items = sorted(closes.items())
    out: dict[date, float] = {}
    for i in range(1, len(items)):
        previous = float(items[i - 1][1])
        current = float(items[i][1])
        if previous > 0:
            out[items[i][0]] = current / previous - 1
    return out


def _group_key(position: ValuedPosition, level: str) -> str:
    sector = position.sector or NO_CLASS_LABEL
    if level == "sector":
        return sector
    if position.asset_class in SUBSECTOR_ELIGIBLE and position.industry:
        return position.industry
    return f"{sector}{NO_SUBSECTOR_SUFFIX}"


def _is_priced(position: ValuedPosition) -> bool:
    """True for anything with a real price series to build a return
    series from: everything except fixed income, *except* Tesouro Direto
    within fixed income — it's mark-to-market via PU history (see module
    docstring), unlike private CDB/LCI/LCA, which stay at cost."""
    if position.asset_class is not AssetClass.fixed_income:
        return True
    return parse_bond_ticker(position.ticker) is not None


# --- orchestrator ------------------------------------------------------------


def build_risk(db: Session, period: str = "1A", group_by: str = "sector") -> RiskResult:
    period = period.upper() if period.upper() in PERIODS else "1A"
    group_by = group_by if group_by in GROUP_LEVELS else "sector"
    result = RiskResult(period=period, period_label=PERIOD_LABEL[period], group_by=group_by)

    transactions = db.execute(select(Transaction)).scalars().all()
    if not transactions:
        return result

    positions, pos_warnings = _valued_positions(db, transactions)
    result.warnings.extend(pos_warnings)
    if not positions:
        return result

    total_value = sum((p.market_value_brl for p in positions), ZERO)
    result.overall.total_value_brl = _cents(total_value)

    history = build_patrimony_history(db, "daily")
    result.warnings.extend(w for w in history.warnings if w not in result.warnings)
    if len(history.points) < 2:
        result.warnings.append("Histórico patrimonial insuficiente para métricas de risco.")
        _fill_concentration(result.overall, positions, total_value)
        result.fixed_income = _fixed_income_risk(positions)
        return result

    full_returns = _portfolio_returns(history.points)
    end = history.points[-1].date
    start = _window_start(period, end)
    window_returns = _restrict(full_returns, start)
    window_dates = [p.date for p in history.points if p.date >= start]
    window_index = [
        float(p.twr_index) for p in history.points if p.date >= start
    ]

    _fill_overall_stats(result.overall, window_returns, window_index, window_dates, total_value)
    _fill_concentration(result.overall, positions, total_value)
    _fill_fx_exposure(result.overall, positions, total_value)

    if window_index:
        result.drawdown_series = _drawdown_series(window_index, window_dates)
        result.rolling_volatility_21d = _rolling_volatility(window_returns, window_dates, 21)
        result.rolling_volatility_63d = _rolling_volatility(window_returns, window_dates, 63)
        result.daily_returns = [RiskPoint(d, window_returns[d]) for d in sorted(window_returns)]

    days = [p.date for p in history.points]
    bm_index, bm_warnings = benchmark_index_series(db, days, ("ibov", "sp500", "cdi"))
    result.warnings.extend(w for w in bm_warnings if w not in result.warnings)
    # Only convert keys benchmark_index_series actually returned — a fetch
    # failure (missing key, per its own contract) must fall through to an
    # empty return series, not crash: _index_daily_returns indexes by
    # `days` unconditionally, so calling it with the `[]` a naive
    # bm_index.get("ibov", []) would produce raises IndexError.
    bm_returns = {key: _index_daily_returns(series, days) for key, series in bm_index.items()}
    ibov_returns = _restrict(bm_returns.get("ibov", {}), start)
    sp500_returns = _restrict(bm_returns.get("sp500", {}), start)
    cdi_returns = _restrict(_cdi_daily_returns(db, days), start)

    _fill_beta_and_tracking_error(
        result.overall, window_returns, ibov_returns, sp500_returns, cdi_returns
    )

    groups, group_returns, priced_value = _build_groups(
        db, positions, group_by, start, end, total_value
    )
    result.groups = groups
    result.risk_universe_coverage_pct = (
        float(priced_value / total_value) if total_value > 0 else None
    )
    result.overall.diversification_ratio = _fill_risk_contribution(groups, group_returns)
    result.group_correlation = _group_correlation(groups, group_returns)

    result.stress_scenarios = _stress_scenarios(db, positions, period, total_value)
    result.fixed_income = _fixed_income_risk(positions)

    return result


def _cents(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def _fill_overall_stats(
    overall: RiskOverall,
    returns: dict[date, float],
    index: list[float],
    dates: list[date],
    total_value: Decimal,
) -> None:
    xs = [returns[d] for d in sorted(returns)]
    overall.observations = len(xs)
    if index:
        dd = _max_drawdown(index, dates)
        overall.max_drawdown_pct = dd.worst_pct
        overall.max_drawdown_date = dd.worst_date
        overall.max_drawdown_duration_days = dd.worst_duration_days
        overall.current_drawdown_days = dd.current_underwater_days
        peak = max(index)
        overall.current_drawdown_pct = index[-1] / peak - 1 if peak > 0 else 0.0
    if len(xs) < MIN_OBS:
        return

    std = _sample_std(xs)
    mean = _mean(xs)
    if std is not None:
        overall.volatility_annual_pct = std * math.sqrt(TRADING_DAYS)
    # Sharpe/Sortino need the CDI series (risk-free), fetched by the caller
    # alongside the benchmarks; filled in by _fill_beta_and_tracking_error.

    var95, cvar95 = _historical_var_cvar(xs, 0.95)
    var99, _cvar99 = _historical_var_cvar(xs, 0.99)
    if var95 is not None:
        overall.var_hist_95_pct = var95
        overall.var_hist_95_brl = _cents(Decimal(str(var95)) * total_value)
    if cvar95 is not None:
        overall.cvar_hist_95_pct = cvar95
        overall.cvar_hist_95_brl = _cents(Decimal(str(cvar95)) * total_value)
    if var99 is not None:
        overall.var_hist_99_pct = var99
        overall.var_hist_99_brl = _cents(Decimal(str(var99)) * total_value)
    if std is not None:
        overall.var_parametric_95_pct = mean - Z_95 * std

    skew, kurt = _skew_kurtosis(xs)
    overall.skewness = skew
    overall.kurtosis_excess = kurt


def _fill_beta_and_tracking_error(
    overall: RiskOverall,
    portfolio_returns: dict[date, float],
    ibov_returns: dict[date, float],
    sp500_returns: dict[date, float],
    cdi_returns: dict[date, float],
) -> None:
    overall.beta_ibov = _beta(portfolio_returns, ibov_returns)
    overall.beta_sp500 = _beta(portfolio_returns, sp500_returns)

    common = sorted(portfolio_returns.keys() & cdi_returns.keys())
    if len(common) >= MIN_OBS:
        excess = [portfolio_returns[d] - cdi_returns[d] for d in common]
        std_excess = _sample_std(excess)
        if std_excess is not None:
            overall.tracking_error_cdi_pct = std_excess * math.sqrt(TRADING_DAYS)
        mean_excess = _mean(excess)
        annual_excess = _annualize_return(mean_excess)

        # Sharpe's own volatility, over the exact same CDI-paired dates as
        # the excess-return numerator above — not overall.volatility_annual_pct
        # (the full window), which would silently mismatch the numerator's
        # sample whenever the CDI series has any gap within the window.
        paired_vol = _sample_std([portfolio_returns[d] for d in common])
        if paired_vol is not None and paired_vol > 0:
            overall.sharpe = annual_excess / (paired_vol * math.sqrt(TRADING_DAYS))

        downside = [min(e, 0.0) for e in excess]
        downside_std = math.sqrt(sum(d * d for d in downside) / len(downside))
        if downside_std > 0:
            overall.sortino = annual_excess / (downside_std * math.sqrt(TRADING_DAYS))


def _beta(seg: dict[date, float], bm: dict[date, float]) -> float | None:
    common = sorted(seg.keys() & bm.keys())
    if len(common) < MIN_OBS:
        return None
    xs = [bm[d] for d in common]
    ys = [seg[d] for d in common]
    mean_x, mean_y = _mean(xs), _mean(ys)
    var_x = sum((x - mean_x) ** 2 for x in xs)
    if var_x <= 0:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    return cov / var_x


def _fill_concentration(
    overall: RiskOverall, positions: list[ValuedPosition], total_value: Decimal
) -> None:
    if total_value <= 0:
        return
    weights = sorted(
        (float(p.market_value_brl / total_value) for p in positions), reverse=True
    )
    overall.hhi_position = _hhi(weights)
    if overall.hhi_position:
        overall.effective_positions = 1 / overall.hhi_position
    overall.top5_concentration_pct = sum(weights[:5])

    by_institution: dict[str, Decimal] = {}
    for p in positions:
        key = p.institution or "Não informado"
        by_institution[key] = by_institution.get(key, ZERO) + p.market_value_brl
    overall.hhi_institution = _hhi(
        [float(v / total_value) for v in by_institution.values()]
    )

    by_segment: dict[str, Decimal] = {}
    for p in positions:
        key = segment_of(p.market, p.asset_class) or "outros"
        by_segment[key] = by_segment.get(key, ZERO) + p.market_value_brl
    overall.hhi_segment = _hhi([float(v / total_value) for v in by_segment.values()])


def _fill_fx_exposure(
    overall: RiskOverall, positions: list[ValuedPosition], total_value: Decimal
) -> None:
    if total_value <= 0:
        return
    usd_value = sum(
        (p.market_value_brl for p in positions if p.market is Market.us), ZERO
    )
    overall.usd_direct_exposure_pct = float(usd_value / total_value)


def _build_groups(
    db: Session,
    positions: list[ValuedPosition],
    group_by: str,
    start: date,
    end: date,
    total_value: Decimal,
) -> tuple[list[RiskGroup], dict[str, dict[date, float]], Decimal]:
    by_group: dict[str, list[ValuedPosition]] = {}
    for p in positions:
        by_group.setdefault(_group_key(p, group_by), []).append(p)

    closes_cache: dict[str, dict[date, float]] = {}

    def ticker_returns(ticker: str) -> dict[date, float]:
        if ticker not in closes_cache:
            closes = _cached_closes(db, ticker, start, end)
            closes_cache[ticker] = _daily_returns_from_closes(closes)
        return closes_cache[ticker]

    groups: list[RiskGroup] = []
    group_returns: dict[str, dict[date, float]] = {}
    priced_value = ZERO

    for label, members in sorted(
        by_group.items(), key=lambda kv: sum(m.market_value_brl for m in kv[1]), reverse=True
    ):
        group_value = sum((m.market_value_brl for m in members), ZERO)
        weight_pct = float(group_value / total_value) if total_value > 0 else 0.0

        priceable = [m for m in members if _is_priced(m)]
        returns_by_ticker: dict[str, dict[date, float]] = {}
        weights: dict[str, float] = {}
        for m in priceable:
            series = ticker_returns(m.ticker)
            if len(series) < MIN_BASKET_OVERLAP:
                continue
            returns_by_ticker[m.ticker] = series
            # += , not =: the same ticker can appear twice in a group (e.g.
            # BTC held hot + cold custody) — both are real money and must
            # both count toward its weight in the basket.
            weights[m.ticker] = weights.get(m.ticker, 0.0) + float(m.market_value_brl)

        volatility = None
        avg_corr = None
        if returns_by_ticker:
            basket = _weighted_basket(returns_by_ticker, weights)
            var = _variance(basket)
            if var is not None:
                volatility = math.sqrt(var) * math.sqrt(TRADING_DAYS)
                group_returns[label] = basket
                priced_value += sum(
                    (m.market_value_brl for m in priceable if m.ticker in returns_by_ticker),
                    ZERO,
                )
            tickers = list(returns_by_ticker)
            if len(tickers) >= 2:
                coefs = []
                for i in range(len(tickers)):
                    for j in range(i + 1, len(tickers)):
                        r = _pearson(returns_by_ticker[tickers[i]], returns_by_ticker[tickers[j]])
                        if r is not None:
                            coefs.append(r)
                if coefs:
                    avg_corr = sum(coefs) / len(coefs)

        groups.append(
            RiskGroup(
                key=label,
                label=label,
                weight_pct=weight_pct,
                market_value_brl=_cents(group_value),
                position_count=len(members),
                priced_position_count=len(returns_by_ticker),
                volatility_annual_pct=volatility,
                avg_intra_correlation=avg_corr,
            )
        )

    return groups, group_returns, priced_value


def _fill_risk_contribution(
    groups: list[RiskGroup], group_returns: dict[str, dict[date, float]]
) -> float | None:
    """Fills each priced group's risk_contribution_pct in place and returns
    the priced sub-portfolio's diversification ratio (weighted-average
    standalone volatility over actual portfolio volatility — 1.0 means no
    diversification benefit at all, i.e. every group moves in lockstep;
    higher means the correlation structure is doing real work). The
    annualization factor cancels out of the ratio, so daily variances are
    used directly, no √252 needed."""
    priced = [g for g in groups if g.key in group_returns]
    if len(priced) < 1:
        return None
    priced_total = sum((g.market_value_brl for g in priced), ZERO)
    if priced_total <= 0:
        return None
    weights = {g.key: float(g.market_value_brl / priced_total) for g in priced}

    # Covariance matrix among priced group baskets.
    cov: dict[tuple[str, str], float] = {}
    for a in priced:
        for b in priced:
            if a.key == b.key:
                var = _variance(group_returns[a.key])
                cov[(a.key, a.key)] = var if var is not None else 0.0
                continue
            if (b.key, a.key) in cov:
                cov[(a.key, b.key)] = cov[(b.key, a.key)]
                continue
            c = _covariance(group_returns[a.key], group_returns[b.key])
            cov[(a.key, b.key)] = c[0] if c is not None else 0.0

    portfolio_var = sum(
        weights[a.key] * weights[b.key] * cov[(a.key, b.key)]
        for a in priced
        for b in priced
    )
    if portfolio_var <= 0:
        return None
    for g in priced:
        marginal = sum(weights[b.key] * cov[(g.key, b.key)] for b in priced)
        contribution = weights[g.key] * marginal
        g.risk_contribution_pct = contribution / portfolio_var

    weighted_avg_vol = sum(weights[g.key] * math.sqrt(cov[(g.key, g.key)]) for g in priced)
    return weighted_avg_vol / math.sqrt(portfolio_var)


def _group_correlation(
    groups: list[RiskGroup], group_returns: dict[str, dict[date, float]]
) -> GroupCorrelation:
    labels = [g.key for g in groups if g.key in group_returns]
    # Correlation is symmetric — compute each unordered pair once and reuse
    # it for both (a, b) and (b, a), instead of re-deriving it twice.
    cache: dict[frozenset[str], float | None] = {}

    def corr(a: str, b: str) -> float | None:
        if a == b:
            return 1.0
        key = frozenset((a, b))
        if key not in cache:
            cache[key] = _pearson(group_returns[a], group_returns[b])
        return cache[key]

    matrix = [[corr(a, b) for b in labels] for a in labels]
    return GroupCorrelation(labels=labels, matrix=matrix)


def _stress_scenarios(
    db: Session, positions: list[ValuedPosition], period: str, total_value: Decimal
) -> list[StressScenario]:
    # capm.py has no "3M" window (beta needs more daily observations than
    # that to mean anything — see its own MIN_OBS gate); the closest capm.py
    # period is used instead so a "3M" risk view never silently mixes in a
    # 1A-fitted beta unlabeled.
    capm_period = _CAPM_PERIOD_FALLBACK.get(period, period)
    capm_result = build_capm(db, capm_period)
    betas = {m.key: m.beta for m in capm_result.segments}
    window_note = (
        f"beta ajustado numa janela de {capm_result.period_label} (mínima do CAPM); "
        f"a janela de risco selecionada aqui é mais curta ({PERIOD_LABEL[period]})"
        if capm_period != period
        else None
    )

    def capm_note(beta: float | None) -> str | None:
        if beta is None:
            return "beta indisponível no período; assumido 1,0 (choque 1:1)"
        return window_note

    def exposure(pred: Callable[[ValuedPosition], bool]) -> Decimal:
        return sum((p.market_value_brl for p in positions if pred(p)), ZERO)

    def scenario(
        key: str,
        label: str,
        shock_pct: float,
        exposure_value: Decimal,
        beta: float | None,
        note: str | None,
    ) -> StressScenario:
        used_beta = beta if beta is not None else 1.0
        # Zero exposure is a real, known answer (no impact) — only the
        # percentage needs a total_value guard, not the R$ impact itself.
        impact_brl = exposure_value * Decimal(str(shock_pct)) * Decimal(str(used_beta))
        impact_pct = float(impact_brl / total_value) if total_value > 0 else None
        return StressScenario(
            key=key,
            label=label,
            shock_pct=shock_pct,
            exposure_brl=_cents(exposure_value),
            beta=used_beta,
            beta_note=note,
            impact_brl=_cents(impact_brl),
            impact_pct=impact_pct,
        )

    br_stock_exposure = exposure(
        lambda p: p.market is Market.br and p.asset_class is AssetClass.stock
    )
    us_exposure = exposure(lambda p: p.market is Market.us)
    crypto_exposure = exposure(lambda p: p.market is Market.crypto)
    usd_exposure = us_exposure  # positions priced directly in USD (Avenue)

    ibov_beta = betas.get("br_stock")
    sp500_beta = betas.get("us")

    return [
        scenario("ibov_-20", "IBOV -20%", -0.20, br_stock_exposure, ibov_beta, capm_note(ibov_beta)),
        scenario("sp500_-20", "S&P 500 -20%", -0.20, us_exposure, sp500_beta, capm_note(sp500_beta)),
        scenario(
            "btc_-30",
            "BTC -30%",
            -0.30,
            crypto_exposure,
            1.0,
            "carteira cripto é quase toda BTC; choque aplicado 1:1",
        ),
        scenario(
            "usdbrl_+15",
            "Dólar +15%",
            0.15,
            usd_exposure,
            1.0,
            "impacto direto sobre posições cotadas em USD (EUA); cripto é cotada em BRL nesta plataforma e não entra aqui",
        ),
        scenario(
            "usdbrl_-15",
            "Dólar -15%",
            -0.15,
            usd_exposure,
            1.0,
            "impacto direto sobre posições cotadas em USD (EUA); cripto é cotada em BRL nesta plataforma e não entra aqui",
        ),
    ]


def _fixed_income_risk(positions: list[ValuedPosition]) -> FixedIncomeRisk | None:
    # Renda fixa PRIVADA only (CDB/LCI/LCA) — the at-cost concentration lens
    # this card exists for. Tesouro Direto is mark-to-market and already
    # gets real volatility/risk-contribution numbers via the sector/
    # sub-setor groups (see _is_priced); showing it here too, under an
    # at-cost lens, would misrepresent it and double up with the group view.
    rf = [
        p
        for p in positions
        if p.asset_class is AssetClass.fixed_income and parse_bond_ticker(p.ticker) is None
    ]
    if not rf:
        return None
    total = sum((p.market_value_brl for p in rf), ZERO)
    if total <= 0:
        return FixedIncomeRisk(total_brl=ZERO)

    by_indexer: dict[str, Decimal] = {}
    for p in rf:
        indexer = resolve_indexer(p.ticker, p.asset_name, p.indexer)
        by_indexer[indexer.value] = by_indexer.get(indexer.value, ZERO) + p.market_value_brl

    labels = {"ipca": "IPCA+", "prefixado": "Pré-fixado", "selic": "Selic/CDI"}
    indexer_slices = [
        IndexerSlice(
            key=key,
            label=labels.get(key, key),
            value_brl=_cents(value),
            weight_pct=float(value / total),
        )
        for key, value in sorted(by_indexer.items(), key=lambda kv: kv[1], reverse=True)
    ]

    by_institution: dict[str, Decimal] = {}
    for p in rf:
        key = p.institution or "Não informado"
        by_institution[key] = by_institution.get(key, ZERO) + p.market_value_brl
    institution_slices = [
        InstitutionSlice(
            label=key, value_brl=_cents(value), weight_pct=float(value / total)
        )
        for key, value in sorted(by_institution.items(), key=lambda kv: kv[1], reverse=True)
    ]
    hhi_institution = _hhi([float(v / total) for v in by_institution.values()])

    return FixedIncomeRisk(
        total_brl=_cents(total),
        by_indexer=indexer_slices,
        by_institution=institution_slices,
        hhi_institution=hhi_institution,
    )
