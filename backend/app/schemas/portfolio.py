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
    segments: list[SegmentOut] = []
    segment_summaries: list[SegmentSummaryOut] = []
    usd_brl_rate: Decimal | None = None
    usd_brl_date: date | None = None
    fx_stale: bool = False
    positions: list[PositionOut]
    warnings: list[str]
