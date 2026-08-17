"""Portfolio risk analytics: the "Risco" section (replaces Correlação, which
now lives inside it as one of its analyses via the existing /portfolio/
correlation endpoint — this module does not touch that one).

Everything price-based (volatility, VaR/CVaR, drawdown, beta, sector/
sub-setor volatility and risk contribution) is derived from the existing
patrimony engine, never refit here. One `load_market_data` feeds both:

- The whole-portfolio daily TWR index (`compute_value_and_twr` over every
  transaction) — the same series behind the Dashboard's "Rentabilidade
  total (TWR)".
- One daily TWR series per ticker (the same engine over that ticker's
  transactions, the pattern `capm.py` uses per segment), for the sector/
  sub-setor basket series.

Reading raw closes instead would get three things wrong at once, each
measured before this was changed: it drops proventos (a dividend-heavy
ticker can return twice as much with them as without, and every FII
changes sign over a 1A window), it mixes currencies on one axis (a US
position compounds differently in USD and in BRL, and a short-duration
bond ETF that is almost flat natively carries the whole exchange-rate
volatility in BRL), and it reads a split as a return (a 6:1 shows up as
-83%). The engine has none of those: it prices in BRL, treats income as
a flow, and applies splits to quantity — on a split day it records the
real move, a fraction of a percent. Dividend-per-share is not derivable
anyway (most `dividend` rows carry `quantity=0`; the broker statement
records only the amount), so the engine is the only path to a
total-return series.

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
from app.services.history import MarketData, compute_value_and_twr, load_market_data
from app.services.indexer import resolve_indexer
from app.services.portfolio import compute_positions
from app.services.quotes import get_quote
from app.services.segments import SEGMENT_KEYS, SEGMENT_LABELS, segment_of
from app.services.tesouro import parse_bond_ticker

ZERO = Decimal("0")
CENTS = Decimal("0.01")

# One grid for the whole module: every series here comes off the engine,
# which carries a point for *every* calendar day — 366 observations in a
# 1-year window, not 252 — so the annualisation factor is 365 and no
# statistic drops a day. Weekends are not padding: with 13% of the book in
# crypto they carry real moves, and over the last year the 115 days outside
# the CDI calendar compounded to +0,808%. A statistic restricted to
# business days reproduces +5,625% of the book's actual +6,479% for the
# window; the full grid reproduces it exactly. Where a business-day input
# is involved (the CDI), it contributes zero on the days it does not
# exist, which is what it in fact pays.
CALENDAR_DAYS = 365

# ... com UMA exceção deliberada, e ela tem convenção própria: VaR, CVaR,
# assimetria e curtose descrevem a forma da distribuição de perda de UM DIA,
# e "um dia" num relatório de risco significa um dia de NEGOCIAÇÃO (Holton,
# Value-at-Risk: "when a horizon is expressed in days without qualification,
# these are understood to be trading days"; Basel usa 10 dias de negociação).
# Não é incoerência com a grade acima — são perguntas diferentes: volatilidade
# e Sharpe medem o CAMINHO do retorno (e descartar fim de semana perderia
# +0,808%/ano de retorno real), enquanto o VaR é um quantil, não acumula nada.
# Incluir os fins de semana empurra o corte de 5% para o meio da distribuição
# (VaR 95% lia -0,95% em vez de -1,04%) e finge uma cauda gorda que é só o
# acúmulo de zeros de sábado: a curtose caía de +1,35 para +0,25 ao usar só
# dias úteis. Dia útil aqui é seg-sex — B3 e NYSE negociam nos mesmos dias da
# semana, e feriado de um é dia útil do outro.
TRADING_DAYS = 252
MIN_OBS = 20  # minimum daily observations to report a statistic (matches capm.py)
MIN_BASKET_OVERLAP = 10  # minimum shared dates to correlate/covary two baskets

PERIODS = ("3M", "6M", "YTD", "1A", "2A", "MAX")
PERIOD_DAYS = {"3M": 91, "6M": 182, "1A": 365, "2A": 730}
PERIOD_LABEL = {
    "3M": "3 meses",
    "6M": "6 meses",
    "YTD": "no ano",
    "1A": "1 ano",
    "2A": "2 anos",
    "MAX": "máximo",
}

# Horizontes do VaR/CVaR. O horizonte é OUTRA coisa que a janela de
# estimação (o seletor de período): a janela diz quanto histórico alimenta a
# conta, o horizonte diz em quanto tempo a perda pode acontecer. A conversão
# é a regra da raiz do tempo (VaR_h = VaR_1 x sqrt(h)), que supõe retornos
# independentes e ignora a tendência — vale para poucos dias e passa a mentir
# em horizontes longos, por isso a lista para em 1 mês. Contados em dias de
# NEGOCIAÇÃO (1 / 5 / 21), como o VaR de base e como o horizonte de 10 dias
# de Basel.
VAR_HORIZONS = ((1, "1 dia"), (5, "1 semana"), (21, "1 mês"))

# capm.py's own PERIODS has no "3M" or "YTD" (see app/services/capm.py);
# stress scenarios need a CAPM-compatible window to fetch betas from.
_CAPM_PERIOD_FALLBACK = {"3M": "6M", "YTD": "6M"}

GROUP_LEVELS = ("sector", "subsector")
NO_CLASS_LABEL = "Sem classificação"
NO_SUBSECTOR_SUFFIX = " (sem sub-setor)"
SUBSECTOR_ELIGIBLE = (AssetClass.stock, AssetClass.etf)

Z_95 = 1.6448536269514722  # one-tailed 95% normal quantile


# --- output dataclasses -------------------------------------------------------


@dataclass
class RiskOverall:
    volatility_annual_pct: float | None = None
    trading_observations: int = 0
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
class VarHorizon:
    """VaR/CVaR at a horizon other than one day, by the square-root-of-time
    rule. Kept as its own list instead of replacing the 1-day fields so the
    cards stay comparable and the assumption is visible where it is used."""

    days: int
    label: str
    var_hist_95_pct: float | None = None
    var_hist_95_brl: Decimal | None = None
    var_hist_99_pct: float | None = None
    var_hist_99_brl: Decimal | None = None
    cvar_hist_95_pct: float | None = None
    cvar_hist_95_brl: Decimal | None = None


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
class BenchmarkComparison:
    """The "versus benchmark" block every professional risk report carries:
    upside/downside capture, batting average and information ratio.

    These are **monthly** by definition — Morningstar's capture ratios are
    the geometric average of the fund's monthly returns in the months the
    index rose (or fell) over the index's own, and a batting average counts
    months. Computing them on daily data would not be the same statistic
    under a different name; it would be a different one.
    """

    key: str
    label: str
    months: int
    up_months: int
    down_months: int
    upside_capture: float | None = None  # 1.0 = capturou 100% da alta
    downside_capture: float | None = None
    batting_average: float | None = None
    active_return_annual_pct: float | None = None
    tracking_error_annual_pct: float | None = None
    information_ratio: float | None = None


@dataclass
class RiskReturnPoint:
    key: str
    label: str
    kind: str  # "asset" | "group" | "segment" | "portfolio" | "benchmark"
    volatility_annual_pct: float
    return_annual_pct: float
    sharpe: float | None = None
    return_period_pct: float | None = None  # realised over the measured span
    weight_pct: float | None = None
    market_value_brl: Decimal | None = None
    segment: str | None = None  # br | us | crypto | rf — for filtering
    asset_class: str | None = None
    sector: str | None = None
    subsector: str | None = None
    observations: int = 0
    first_date: date | None = None
    partial_window: bool = False


@dataclass
class RiskReturn:
    risk_free_label: str = "CDI"
    risk_free_annual_pct: float | None = None
    assets: list[RiskReturnPoint] = field(default_factory=list)
    groups: list[RiskReturnPoint] = field(default_factory=list)
    segments: list[RiskReturnPoint] = field(default_factory=list)
    portfolio: RiskReturnPoint | None = None
    benchmarks: list[RiskReturnPoint] = field(default_factory=list)


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
    var_horizons: list[VarHorizon] = field(default_factory=list)
    benchmark_comparison: list[BenchmarkComparison] = field(default_factory=list)
    risk_return: RiskReturn = field(default_factory=RiskReturn)
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
    """Compounds a mean daily return of the calendar-daily engine series."""
    return (1 + mean_daily) ** CALENDAR_DAYS - 1


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
    """Rolling volatility of the portfolio series — calendar-daily, so the
    window is `window` calendar days and the factor is CALENDAR_DAYS."""
    ordered = [(d, returns[d]) for d in dates if d in returns]
    points: list[RiskPoint] = []
    for i in range(window - 1, len(ordered)):
        chunk = [r for _, r in ordered[i - window + 1 : i + 1]]
        std = _sample_std(chunk)
        if std is not None:
            points.append(RiskPoint(ordered[i][0], std * math.sqrt(CALENDAR_DAYS)))
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
    if period == "YTD":
        return date(end.year, 1, 1)
    return end - timedelta(days=PERIOD_DAYS[period])


def _trading_only(returns: dict[date, float]) -> dict[date, float]:
    """Weekdays only — the grid a one-day VaR is defined on."""
    return {d: v for d, v in returns.items() if d.weekday() < 5}


def _twr_returns(
    totals: list[Decimal], twr: list[Decimal], days: list[date]
) -> dict[date, float]:
    """Daily TWR returns of whatever transaction subset produced `totals`/
    `twr`, guarded the same way capm.py guards a segment's: only days where
    both ends actually held value, so the pre-existence flat lead-in injects
    no fake returns. For a single ticker this also means the series covers
    exactly the holding period — an asset bought mid-window is measured from
    the day it entered the book, not before."""
    out: dict[date, float] = {}
    for i in range(1, len(days)):
        if totals[i - 1] > 0 and totals[i] > 0 and twr[i - 1] > 0:
            out[days[i]] = float(twr[i] / twr[i - 1]) - 1
    return out


def _asset_return_series(
    transactions: list[Transaction], data: MarketData, tickers: set[str]
) -> dict[str, dict[date, float]]:
    """One daily total-return series per ticker, in BRL, from the same
    engine that values the portfolio — so proventos, splits, custody moves
    and FX are all handled exactly once, in one place."""
    by_ticker: dict[str, list[Transaction]] = {}
    for tx in transactions:
        if tx.ticker in tickers:
            by_ticker.setdefault(tx.ticker, []).append(tx)

    out: dict[str, dict[date, float]] = {}
    for ticker, subset in by_ticker.items():
        totals, twr = compute_value_and_twr(subset, data)
        out[ticker] = _twr_returns(totals, twr, data.days)
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


def _risk_return_stats(
    returns: dict[date, float], risk_free: dict[date, float]
) -> tuple[float, float, float | None, float, int, date] | None:
    """(volatility, annual return, sharpe, realised return, n, first date).

    Everything on the module's single calendar grid, so the three numbers
    are one geometry: sharpe is exactly the slope of the line from the
    risk-free anchor (0, rf) to the point (volatility, return). Plotting a
    realised/compounded return on the vertical axis instead would break
    that — the slope would stop being the sharpe by a volatility-drag term
    — so the realised figure travels alongside as its own field, for the
    tooltip, rather than as the coordinate.
    """
    days = sorted(returns)
    if len(days) < MIN_OBS:
        return None
    values = [returns[d] for d in days]
    std = _sample_std(values)
    if std is None or std <= 0:
        return None
    volatility = std * math.sqrt(CALENDAR_DAYS)
    annual = _annualize_return(_mean(values))
    excess = [returns[d] - risk_free.get(d, 0.0) for d in days]
    sharpe = _annualize_return(_mean(excess)) / volatility
    realised = math.prod(1 + v for v in values) - 1
    return volatility, annual, sharpe, realised, len(days), days[0]


def _risk_return_point(
    key: str,
    label: str,
    kind: str,
    returns: dict[date, float],
    risk_free: dict[date, float],
    reference_start: date,
    **extra,
) -> RiskReturnPoint | None:
    stats = _risk_return_stats(returns, risk_free)
    if stats is None:
        return None
    volatility, annual, sharpe, realised, n, first = stats
    return RiskReturnPoint(
        key=key,
        label=label,
        kind=kind,
        volatility_annual_pct=volatility,
        return_annual_pct=annual,
        sharpe=sharpe,
        return_period_pct=realised,
        observations=n,
        first_date=first,
        # A holding bought inside the window is measured from the day it
        # entered the book, so the UI can say so instead of implying the
        # figure covers the same span as everything around it. The reference
        # is where the *portfolio's* own series starts in this window, not
        # the window's first day: on a book younger than the window every
        # point would otherwise be flagged, which says nothing.
        partial_window=first > reference_start + timedelta(days=1),
        **extra,
    )


def _segment_key(position: ValuedPosition) -> str:
    """The position's segment, by the project's single definition (fixed
    income wins over market, so Tesouro lands in `rf`, not `br`)."""
    return segment_of(position.market, position.asset_class) or "outros"


def _segment_return_series(
    transactions: list[Transaction], data: MarketData
) -> dict[str, dict[date, float]]:
    """One TWR series per segment (Brasil, EUA, Cripto, Renda Fixa), from the
    same engine over the segment's own transactions — the *realised* path of
    that book, exactly like the whole-portfolio point, not a synthetic basket
    re-weighted to today."""
    subsets: dict[str, list[Transaction]] = {}
    for tx in transactions:
        key = segment_of(tx.market, tx.asset_class)
        if key is not None:
            subsets.setdefault(key, []).append(tx)

    out: dict[str, dict[date, float]] = {}
    for key, subset in subsets.items():
        totals, twr = compute_value_and_twr(subset, data)
        out[key] = _twr_returns(totals, twr, data.days)
    return out


def _build_risk_return(
    positions: list[ValuedPosition],
    asset_returns: dict[str, dict[date, float]],
    group_returns: dict[str, dict[date, float]],
    segment_returns: dict[str, dict[date, float]],
    groups: list[RiskGroup],
    portfolio_returns: dict[date, float],
    cdi_returns: dict[date, float],
    benchmark_returns: dict[str, dict[date, float]],
    start: date,
    total_value: Decimal,
) -> RiskReturn:
    out = RiskReturn()

    # The anchor the whole chart is read against, at zero volatility. It has
    # to be compounded over the same calendar grid as every point around it:
    # the CDI only has a rate on business days, so averaging those ~251 rates
    # and compounding them 365 times would invent yield the anchor never paid
    # (21,97% a year instead of 14,59% on the real book). Zero on the days it
    # does not accrue, which is what it in fact pays.
    grid = sorted(portfolio_returns)
    reference_start = grid[0] if grid else start
    if len(grid) >= MIN_OBS:
        out.risk_free_annual_pct = _annualize_return(
            _mean([cdi_returns.get(d, 0.0) for d in grid])
        )

    by_ticker: dict[str, list[ValuedPosition]] = {}
    for p in positions:
        if _is_priced(p):
            by_ticker.setdefault(p.ticker, []).append(p)

    for ticker, held in sorted(
        by_ticker.items(),
        key=lambda kv: sum((p.market_value_brl for p in kv[1]), ZERO),
        reverse=True,
    ):
        # Custodies of the same ticker share one price story; their value
        # is summed so the bubble is the whole holding.
        value = sum((p.market_value_brl for p in held), ZERO)
        first = held[0]
        point = _risk_return_point(
            ticker,
            first.asset_name or ticker,
            "asset",
            _restrict(asset_returns.get(ticker, {}), start),
            cdi_returns,
            reference_start,
            weight_pct=float(value / total_value) if total_value > 0 else None,
            market_value_brl=_cents(value),
            segment=_segment_key(first),
            asset_class=first.asset_class.value,
            sector=first.sector or NO_CLASS_LABEL,
            subsector=first.industry,
        )
        if point is not None:
            out.assets.append(point)

    for group in groups:
        point = _risk_return_point(
            group.key,
            group.label,
            "group",
            group_returns.get(group.key, {}),
            cdi_returns,
            reference_start,
            weight_pct=group.weight_pct,
            market_value_brl=group.market_value_brl,
        )
        if point is not None:
            out.groups.append(point)

    by_segment: dict[str, Decimal] = {}
    for p in positions:
        key = _segment_key(p)
        by_segment[key] = by_segment.get(key, ZERO) + p.market_value_brl
    for key in SEGMENT_KEYS:
        series = _restrict(segment_returns.get(key, {}), start)
        value = by_segment.get(key, ZERO)
        if value <= 0:
            continue
        point = _risk_return_point(
            key,
            SEGMENT_LABELS.get(key, key),
            "segment",
            series,
            cdi_returns,
            reference_start,
            weight_pct=float(value / total_value) if total_value > 0 else None,
            market_value_brl=_cents(value),
            segment=key,
        )
        if point is not None:
            out.segments.append(point)

    out.portfolio = _risk_return_point(
        "portfolio",
        "Carteira",
        "portfolio",
        portfolio_returns,
        cdi_returns,
        reference_start,
        weight_pct=1.0,
        market_value_brl=_cents(total_value),
    )

    for key, label in (("ibov", "IBOV"), ("sp500", "S&P 500 (em BRL)")):
        point = _risk_return_point(
            key, label, "benchmark", _restrict(benchmark_returns.get(key, {}), start),
            cdi_returns, reference_start,
        )
        if point is not None:
            out.benchmarks.append(point)

    return out


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

    # One market-data load feeds the portfolio series and every per-ticker
    # series below (same closes, same FX, same days).
    market_data = load_market_data(db, transactions)
    result.warnings.extend(w for w in market_data.warnings if w not in result.warnings)
    days = market_data.days
    if len(days) < 2:
        result.warnings.append("Histórico patrimonial insuficiente para métricas de risco.")
        _fill_concentration(result.overall, positions, total_value)
        result.fixed_income = _fixed_income_risk(positions)
        return result

    portfolio_totals, portfolio_twr = compute_value_and_twr(transactions, market_data)
    full_returns = _twr_returns(portfolio_totals, portfolio_twr, days)
    end = days[-1]
    start = _window_start(period, end)
    window_returns = _restrict(full_returns, start)
    window_dates = [d for d in days if d >= start]
    window_index = [
        float(value) for day, value in zip(days, portfolio_twr) if day >= start
    ]

    _fill_overall_stats(result.overall, window_returns, window_index, window_dates, total_value)
    _fill_concentration(result.overall, positions, total_value)
    _fill_fx_exposure(result.overall, positions, total_value)

    if window_index:
        result.drawdown_series = _drawdown_series(window_index, window_dates)
        result.rolling_volatility_21d = _rolling_volatility(window_returns, window_dates, 21)
        result.rolling_volatility_63d = _rolling_volatility(window_returns, window_dates, 63)
        result.daily_returns = [RiskPoint(d, window_returns[d]) for d in sorted(window_returns)]

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

    asset_returns = _asset_return_series(
        transactions, market_data, {p.ticker for p in positions if _is_priced(p)}
    )
    groups, group_returns, priced_value = _build_groups(
        positions, group_by, asset_returns, start, total_value
    )
    result.groups = groups
    result.risk_universe_coverage_pct = (
        float(priced_value / total_value) if total_value > 0 else None
    )
    result.overall.diversification_ratio = _fill_risk_contribution(groups, group_returns)
    result.group_correlation = _group_correlation(groups, group_returns)

    # The S&P is quoted in USD; every other point on the risk-return chart
    # is a BRL return, and mixing the two on one axis would credit the index
    # with a currency move the holder never had. Converted at the same PTAX
    # series the engine values USD positions with.
    sp500_brl: dict[date, float] = {}
    sp500_brl_full: dict[date, float] = {}
    sp500_index = bm_index.get("sp500")
    if sp500_index is not None and market_data.fx is not None:
        converted = [
            (level * rate) if (level is not None and rate is not None) else None
            for level, rate in zip(sp500_index, market_data.fx)
        ]
        sp500_brl_full = _index_daily_returns(converted, days)
        sp500_brl = _restrict(sp500_brl_full, start)

    result.risk_return = _build_risk_return(
        positions,
        asset_returns,
        group_returns,
        _segment_return_series(transactions, market_data),
        groups,
        window_returns,
        cdi_returns,
        {"ibov": ibov_returns, "sp500": sp500_brl},
        start,
        total_value,
    )

    result.var_horizons = _var_horizons(result.overall, total_value)
    # Séries cheias, recortadas por MÊS COMPLETO (não pela janela em dias):
    # ver PERIOD_MONTHS. YTD são os meses completos do ano corrente.
    if period == "YTD":
        months_wanted = max(0, end.month - 1)
    else:
        months_wanted = PERIOD_MONTHS.get(period)
    for key, label, series in (
        ("ibov", "IBOV", bm_returns.get("ibov", {})),
        ("sp500", "S&P 500 (em BRL)", sp500_brl_full),
    ):
        comparison = _benchmark_comparison(
            key, label, full_returns, series, months_wanted
        )
        if comparison is not None:
            result.benchmark_comparison.append(comparison)
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
        # Calendar-daily series -> CALENDAR_DAYS (see the constants above).
        overall.volatility_annual_pct = std * math.sqrt(CALENDAR_DAYS)
    # Sharpe/Sortino need the CDI series (risk-free), fetched by the caller
    # alongside the benchmarks; filled in by _fill_beta_and_tracking_error.

    # Daqui para baixo, a grade é a de dias de negociação (ver o bloco de
    # constantes): estas quatro descrevem a distribuição de perda de um dia.
    trading = [returns[d] for d in sorted(_trading_only(returns))]
    overall.trading_observations = len(trading)
    if len(trading) < MIN_OBS:
        return
    std_t = _sample_std(trading)
    mean_t = _mean(trading)

    var95, cvar95 = _historical_var_cvar(trading, 0.95)
    var99, _cvar99 = _historical_var_cvar(trading, 0.99)
    if var95 is not None:
        overall.var_hist_95_pct = var95
        overall.var_hist_95_brl = _cents(Decimal(str(var95)) * total_value)
    if cvar95 is not None:
        overall.cvar_hist_95_pct = cvar95
        overall.cvar_hist_95_brl = _cents(Decimal(str(cvar95)) * total_value)
    if var99 is not None:
        overall.var_hist_99_pct = var99
        overall.var_hist_99_brl = _cents(Decimal(str(var99)) * total_value)
    if std_t is not None:
        overall.var_parametric_95_pct = mean_t - Z_95 * std_t

    skew, kurt = _skew_kurtosis(trading)
    overall.skewness = skew
    overall.kurtosis_excess = kurt


MIN_MONTHS = 12  # menos que isso não sustenta captura/batting (Morningstar usa 12)
MONTHS_PER_YEAR = 12

# Quantos meses COMPLETOS cada janela vale. A métrica é mensal e alinhada a
# fim de mês, não a uma janela de N dias: "captura de 1 ano" são os 12 meses
# completos anteriores, como Morningstar reporta. Contar 365 dias corridos
# deixaria 11 meses completos (a janela começa no meio de um mês e termina no
# meio de outro) e o número simplesmente não sairia.
PERIOD_MONTHS = {"3M": 3, "6M": 6, "1A": 12, "2A": 24}


def _monthly_returns(daily: dict[date, float]) -> dict[tuple[int, int], float]:
    """Compounds a daily series into calendar months. A month is kept only
    if it has a return for every day the series covers within it, so a
    half-month at either edge of the window never poses as a full one."""
    if not daily:
        return {}
    days = sorted(daily)
    start, end = days[0], days[-1]
    buckets: dict[tuple[int, int], list[float]] = {}
    for day in days:
        buckets.setdefault((day.year, day.month), []).append(daily[day])

    # Only the window's first and last months can be partial. The 3-day
    # tolerance is for an edge landing on a weekend.
    first_key, last_key = (start.year, start.month), (end.year, end.month)
    out: dict[tuple[int, int], float] = {}
    for key, values in buckets.items():
        if key == first_key and start.day > 3:
            continue
        if key == last_key:
            next_month = date(key[0] + key[1] // 12, key[1] % 12 + 1, 1)
            if (next_month - end).days > 3:
                continue
        out[key] = math.prod(1 + v for v in values) - 1
    return out


def _geometric_mean(values: list[float]) -> float | None:
    if not values:
        return None
    product = math.prod(1 + v for v in values)
    if product <= 0:
        return None
    return product ** (1 / len(values)) - 1


def _benchmark_comparison(
    key: str,
    label: str,
    portfolio_daily: dict[date, float],
    benchmark_daily: dict[date, float],
    months_wanted: int | None = None,
) -> BenchmarkComparison | None:
    """Capture ratios, batting average and information ratio, on the months
    both series actually share — the last `months_wanted` of them."""
    port = _monthly_returns(portfolio_daily)
    bench = _monthly_returns(benchmark_daily)
    common = sorted(port.keys() & bench.keys())
    if months_wanted is not None:
        common = common[-months_wanted:]
    if len(common) < MIN_MONTHS:
        return None

    up = [m for m in common if bench[m] > 0]
    down = [m for m in common if bench[m] < 0]
    out = BenchmarkComparison(
        key=key,
        label=label,
        months=len(common),
        up_months=len(up),
        down_months=len(down),
        batting_average=sum(1 for m in common if port[m] >= bench[m]) / len(common),
    )

    # Morningstar's definition: geometric average of each side over the same
    # months, then the ratio. A capture ratio needs a non-zero denominator,
    # which is why each side is gated on its own month count.
    if up:
        p_up, b_up = _geometric_mean([port[m] for m in up]), _geometric_mean([bench[m] for m in up])
        if p_up is not None and b_up not in (None, 0):
            out.upside_capture = p_up / b_up
    if down:
        p_dn, b_dn = _geometric_mean([port[m] for m in down]), _geometric_mean([bench[m] for m in down])
        if p_dn is not None and b_dn not in (None, 0):
            out.downside_capture = p_dn / b_dn

    active = [port[m] - bench[m] for m in common]
    te = _sample_std(active)
    out.active_return_annual_pct = (1 + _mean(active)) ** MONTHS_PER_YEAR - 1
    if te is not None and te > 0:
        out.tracking_error_annual_pct = te * math.sqrt(MONTHS_PER_YEAR)
        out.information_ratio = out.active_return_annual_pct / out.tracking_error_annual_pct
    return out


def _var_horizons(overall: RiskOverall, total_value: Decimal) -> list[VarHorizon]:
    """Scales the 1-day figures out to the other horizons.

    The square-root-of-time rule holds while daily returns are roughly
    independent and the drift is negligible against the noise — true for
    days, not for quarters. That is why the list stops at a month: an
    "annual VaR" scaled this way would be dominated by the drift it ignores,
    and is not a quantity anyone reports.
    """
    out: list[VarHorizon] = []
    for days, label in VAR_HORIZONS:
        factor = math.sqrt(days)

        def scaled(pct: float | None) -> tuple[float | None, Decimal | None]:
            if pct is None:
                return None, None
            value = pct * factor
            return value, _cents(Decimal(str(value)) * total_value)

        v95, v95_brl = scaled(overall.var_hist_95_pct)
        v99, v99_brl = scaled(overall.var_hist_99_pct)
        c95, c95_brl = scaled(overall.cvar_hist_95_pct)
        out.append(
            VarHorizon(
                days=days,
                label=label,
                var_hist_95_pct=v95,
                var_hist_95_brl=v95_brl,
                var_hist_99_pct=v99,
                var_hist_99_brl=v99_brl,
                cvar_hist_95_pct=c95,
                cvar_hist_95_brl=c95_brl,
            )
        )
    return out


def _fill_beta_and_tracking_error(
    overall: RiskOverall,
    portfolio_returns: dict[date, float],
    ibov_returns: dict[date, float],
    sp500_returns: dict[date, float],
    cdi_returns: dict[date, float],
) -> None:
    overall.beta_ibov = _beta(portfolio_returns, ibov_returns)
    overall.beta_sp500 = _beta(portfolio_returns, sp500_returns)

    # Excess return over the *whole* portfolio series, not only the days the
    # CDI has a rate for. Restricting to CDI-paired dates silently deletes
    # every weekend and holiday from the measurement, and those days are not
    # empty: crypto trades all seven, and over the last year the 115 days
    # outside the CDI calendar compounded to +0,808% — real return the ratio
    # never saw. Compounding the paired subset reproduces +5,625% against the
    # book's actual +6,479%; the full calendar grid reproduces it exactly.
    # The risk-free is zero on those days because that is the fact — the CDI
    # accrues on business days only.
    common = sorted(portfolio_returns)
    if len(common) >= MIN_OBS:
        excess = [portfolio_returns[d] - cdi_returns.get(d, 0.0) for d in common]
        std_excess = _sample_std(excess)
        if std_excess is not None:
            overall.tracking_error_cdi_pct = std_excess * math.sqrt(CALENDAR_DAYS)
        annual_excess = _annualize_return(_mean(excess))

        # Numerator and denominator now share one sample by construction, so
        # the denominator *is* the volatility card — no second, subtly
        # different volatility living inside the ratio.
        if overall.volatility_annual_pct:
            overall.sharpe = annual_excess / overall.volatility_annual_pct

        downside = [min(e, 0.0) for e in excess]
        downside_std = math.sqrt(sum(d * d for d in downside) / len(downside))
        if downside_std > 0:
            overall.sortino = annual_excess / (downside_std * math.sqrt(CALENDAR_DAYS))


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
    # By ticker, not by position row: the engine keys crypto by custody, so
    # BTC held hot *and* cold arrives as two rows. They are the same asset at
    # the same price — correlation 1 by construction — and counting them
    # separately invents diversification — it understates top-5 weight and
    # overstates the effective number of positions by roughly one whole
    # position. Institution and segment below are already aggregations, so
    # they never had the problem.
    by_ticker: dict[str, Decimal] = {}
    for p in positions:
        by_ticker[p.ticker] = by_ticker.get(p.ticker, ZERO) + p.market_value_brl
    weights = sorted(
        (float(value / total_value) for value in by_ticker.values()), reverse=True
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
    positions: list[ValuedPosition],
    group_by: str,
    asset_returns: dict[str, dict[date, float]],
    start: date,
    total_value: Decimal,
) -> tuple[list[RiskGroup], dict[str, dict[date, float]], Decimal]:
    by_group: dict[str, list[ValuedPosition]] = {}
    for p in positions:
        by_group.setdefault(_group_key(p, group_by), []).append(p)

    windowed: dict[str, dict[date, float]] = {}

    def ticker_returns(ticker: str) -> dict[date, float]:
        if ticker not in windowed:
            windowed[ticker] = _restrict(asset_returns.get(ticker, {}), start)
        return windowed[ticker]

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
                volatility = math.sqrt(var) * math.sqrt(CALENDAR_DAYS)
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
