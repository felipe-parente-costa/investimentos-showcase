from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from app.models.enums import AssetClass, Custody, Indexer, Market


class PositionOut(BaseModel):
    ticker: str
    asset_name: str | None
    asset_class: AssetClass
    market: Market
    institution: str | None = None
    custody: Custody | None = None
    # Resolved fixed-income indexer (manual override or derived); None for
    # non-fixed-income.
    indexer: Indexer | None = None
    sector: str | None = None
    country: str | None = None
    currency: str
    quantity: Decimal
    average_price: Decimal
    total_cost: Decimal
    realized_pnl: Decimal
    income: Decimal
    # priced=False means no quote source (e.g. fixed income) or fetch failed
    # with an empty cache; the position is then valued at cost.
    priced: bool
    quote_price: Decimal | None = None
    quote_currency: str | None = None
    quote_date: date | None = None
    quote_fetched_at: datetime | None = None
    quote_stale: bool = False
    market_value: Decimal | None = None
    market_value_brl: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    day_change_brl: Decimal | None = None
    day_change_pct: Decimal | None = None
    # Trailing-12-month income in the position's own currency, and the
    # dividend yield it implies over the current market value (both sides in
    # the native currency, so the ratio holds in the BRL and USD views).
    # dy is None for fixed income (no DY by definition) and unpriced positions.
    income_12m: Decimal = Decimal("0")
    dy_12m_pct: Decimal | None = None
    # USD view (EUA/Cripto sections): cost basis uses each transaction's PTAX,
    # market value uses native USD quotes. Null where USD is not applicable.
    usd_average_price: Decimal | None = None
    usd_total_cost: Decimal | None = None
    usd_market_value: Decimal | None = None
    usd_unrealized_pnl: Decimal | None = None


class HistoryPointOut(BaseModel):
    date: date
    total_brl: Decimal
    twr_index: Decimal


class PortfolioHistoryOut(BaseModel):
    points: list[HistoryPointOut]
    warnings: list[str]


class ContributionMonthOut(BaseModel):
    month: str  # YYYY-MM
    aportes: Decimal
    vendas: Decimal
    rendimentos: Decimal


class ContributionsOut(BaseModel):
    months: list[ContributionMonthOut]


class PerformancePointOut(BaseModel):
    date: date
    carteira: Decimal
    cdi: Decimal | None = None
    ibov: Decimal | None = None
    sp500: Decimal | None = None
    btc: Decimal | None = None


class PerformanceOut(BaseModel):
    points: list[PerformancePointOut]
    warnings: list[str]


class ReturnPointOut(BaseModel):
    date: date
    return_pct: Decimal | None


class ReturnSeriesOut(BaseModel):
    key: str
    label: str
    kind: str  # "segment" | "benchmark"
    points: list[ReturnPointOut]


class ReturnsOut(BaseModel):
    period: str
    start: date | None
    series: list[ReturnSeriesOut]
    warnings: list[str]


class CorrelationOut(BaseModel):
    period: str
    segment: str | None
    tickers: list[str]
    matrix: list[list[float | None]]
    warnings: list[str]


class CapmSegmentOut(BaseModel):
    key: str
    label: str
    benchmark_label: str
    risk_free_label: str
    period: str
    period_label: str
    frequency: str
    beta: float | None = None
    alpha_annual_pct: float | None = None
    correlation: float | None = None
    observations: int
    note: str | None = None
    warnings: list[str]


class CapmOut(BaseModel):
    period: str
    period_label: str
    frequency: str
    segments: list[CapmSegmentOut]
    warnings: list[str]


class SegmentOut(BaseModel):
    market: Market
    total_brl: Decimal
    position_count: int


class RiskOverallOut(BaseModel):
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
    observations: int
    hhi_position: float | None = None
    effective_positions: float | None = None
    top5_concentration_pct: float | None = None
    hhi_institution: float | None = None
    hhi_segment: float | None = None
    diversification_ratio: float | None = None
    usd_direct_exposure_pct: float | None = None
    total_value_brl: Decimal | None = None


class RiskPointOut(BaseModel):
    date: date
    value: float


class RiskGroupOut(BaseModel):
    key: str
    label: str
    weight_pct: float
    market_value_brl: Decimal
    position_count: int
    priced_position_count: int
    volatility_annual_pct: float | None = None
    risk_contribution_pct: float | None = None
    avg_intra_correlation: float | None = None


class GroupCorrelationOut(BaseModel):
    labels: list[str]
    matrix: list[list[float | None]]


class StressScenarioOut(BaseModel):
    key: str
    label: str
    shock_pct: float
    exposure_brl: Decimal
    beta: float
    beta_note: str | None = None
    impact_brl: Decimal | None = None
    impact_pct: float | None = None


class IndexerSliceOut(BaseModel):
    key: str
    label: str
    value_brl: Decimal
    weight_pct: float


class InstitutionSliceOut(BaseModel):
    label: str
    value_brl: Decimal
    weight_pct: float


class FixedIncomeRiskOut(BaseModel):
    total_brl: Decimal
    by_indexer: list[IndexerSliceOut]
    by_institution: list[InstitutionSliceOut]
    hhi_institution: float | None = None


class VarHorizonOut(BaseModel):
    days: int
    label: str
    var_hist_95_pct: float | None = None
    var_hist_95_brl: Decimal | None = None
    var_hist_99_pct: float | None = None
    var_hist_99_brl: Decimal | None = None
    cvar_hist_95_pct: float | None = None
    cvar_hist_95_brl: Decimal | None = None


class BenchmarkComparisonOut(BaseModel):
    key: str
    label: str
    months: int
    up_months: int
    down_months: int
    upside_capture: float | None = None
    downside_capture: float | None = None
    batting_average: float | None = None
    active_return_annual_pct: float | None = None
    tracking_error_annual_pct: float | None = None
    information_ratio: float | None = None


class RiskReturnPointOut(BaseModel):
    key: str
    label: str
    kind: str
    volatility_annual_pct: float
    return_annual_pct: float
    sharpe: float | None = None
    return_period_pct: float | None = None
    weight_pct: float | None = None
    market_value_brl: Decimal | None = None
    segment: str | None = None
    asset_class: str | None = None
    sector: str | None = None
    subsector: str | None = None
    observations: int = 0
    first_date: date | None = None
    partial_window: bool = False


class RiskReturnOut(BaseModel):
    risk_free_label: str
    risk_free_annual_pct: float | None = None
    assets: list[RiskReturnPointOut]
    groups: list[RiskReturnPointOut]
    segments: list[RiskReturnPointOut]
    portfolio: RiskReturnPointOut | None = None
    benchmarks: list[RiskReturnPointOut]


class RiskOut(BaseModel):
    period: str
    period_label: str
    group_by: str
    overall: RiskOverallOut
    drawdown_series: list[RiskPointOut]
    rolling_volatility_21d: list[RiskPointOut]
    rolling_volatility_63d: list[RiskPointOut]
    daily_returns: list[RiskPointOut]
    groups: list[RiskGroupOut]
    group_correlation: GroupCorrelationOut
    risk_universe_coverage_pct: float | None = None
    var_horizons: list[VarHorizonOut]
    benchmark_comparison: list[BenchmarkComparisonOut]
    risk_return: RiskReturnOut
    stress_scenarios: list[StressScenarioOut]
    fixed_income: FixedIncomeRiskOut | None = None
    warnings: list[str]


class SegmentSummaryOut(BaseModel):
    key: str
    label: str
    total_brl: Decimal
    cost_brl: Decimal
    unrealized_pnl_brl: Decimal
    pnl_pct: Decimal | None = None
    weight_pct: Decimal | None = None
    position_count: int
    # Display currency for this section: BRL for br/rf/total, USD for us/crypto.
    display_currency: str = "BRL"
    # USD totals for the EUA/Cripto sections (None for BRL sections).
    usd_total: Decimal | None = None
    usd_cost: Decimal | None = None
    usd_unrealized_pnl: Decimal | None = None
    usd_pnl_pct: Decimal | None = None


class UsdBrlMarketOut(BaseModel):
    # Commercial market USD/BRL (delayed, display-only) — not the cost PTAX.
    rate: Decimal | None = None
    quote_date: date | None = None
    fetched_at: datetime | None = None
    source: str | None = None
    stale: bool = False


class PortfolioOut(BaseModel):
    total_market_value_brl: Decimal
    day_change_brl: Decimal | None = None
    day_change_pct: Decimal | None = None
    income_ytd_brl: Decimal = Decimal("0")
    # Trailing-12-month income in BRL and the portfolio-level dividend yield
    # (income_12m_brl / total market value); None when the total is zero.
    income_12m_brl: Decimal = Decimal("0")
    dy_12m_pct: Decimal | None = None
    segments: list[SegmentOut] = []
    segment_summaries: list[SegmentSummaryOut] = []
    usd_brl_rate: Decimal | None = None
    usd_brl_date: date | None = None
    fx_stale: bool = False
    positions: list[PositionOut]
    warnings: list[str]
