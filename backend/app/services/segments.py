"""Disjoint portfolio segments and their aggregation.

The four segments partition every open position exactly once, so their
market values sum to the portfolio total:

- br:     Brazilian variable income (B3 stocks/FIIs/ETFs)
- us:     US holdings (Avenue)
- crypto: crypto (Binance / cold wallet)
- rf:     fixed income (Tesouro Direto + private), regardless of market

Fixed income takes precedence over market, so Tesouro (market=br) lands in
``rf`` rather than ``br``. These keys match the per-segment TWR keys in
services/returns.py so the segment pages can reuse that endpoint.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.models.enums import AssetClass, Market

ZERO = Decimal("0")
CENTS = Decimal("0.01")
PCT = Decimal("0.000001")

SEGMENT_KEYS = ("br", "us", "crypto", "rf")
SEGMENT_LABELS = {
    "br": "Brasil (B3)",
    "us": "EUA (Avenue)",
    "crypto": "Cripto",
    "rf": "Renda Fixa",
}


def segment_of(market: Market, asset_class: AssetClass) -> str | None:
    """Which disjoint segment a position belongs to (None if unclassifiable)."""
    if asset_class is AssetClass.fixed_income:
        return "rf"
    if market is Market.br:
        return "br"
    if market is Market.us:
        return "us"
    if market is Market.crypto:
        return "crypto"
    return None


@dataclass
class SegmentRow:
    key: str
    market_value_brl: Decimal | None
    cost_brl: Decimal | None


@dataclass
class SegmentSummary:
    key: str
    label: str
    total_brl: Decimal
    cost_brl: Decimal
    unrealized_pnl_brl: Decimal
    pnl_pct: Decimal | None
    weight_pct: Decimal | None
    position_count: int


def aggregate_segments(rows: list[SegmentRow]) -> list[SegmentSummary]:
    """Sum market value, cost and P&L per segment, with each segment's weight
    relative to the priced grand total. Segments with no positions are
    omitted; order follows SEGMENT_KEYS."""
    totals = {key: ZERO for key in SEGMENT_KEYS}
    costs = {key: ZERO for key in SEGMENT_KEYS}
    counts = {key: 0 for key in SEGMENT_KEYS}
    grand_total = ZERO

    for row in rows:
        if row.key not in totals:
            continue
        counts[row.key] += 1
        if row.market_value_brl is not None:
            totals[row.key] += row.market_value_brl
            grand_total += row.market_value_brl
        if row.cost_brl is not None:
            costs[row.key] += row.cost_brl

    summaries: list[SegmentSummary] = []
    for key in SEGMENT_KEYS:
        if counts[key] == 0:
            continue
        total = totals[key]
        cost = costs[key]
        pnl = total - cost
        pnl_pct = (pnl / cost) if cost > 0 else None
        weight = (total / grand_total) if grand_total > 0 else None
        summaries.append(
            SegmentSummary(
                key=key,
                label=SEGMENT_LABELS[key],
                total_brl=total.quantize(CENTS, ROUND_HALF_UP),
                cost_brl=cost.quantize(CENTS, ROUND_HALF_UP),
                unrealized_pnl_brl=pnl.quantize(CENTS, ROUND_HALF_UP),
                pnl_pct=pnl_pct.quantize(PCT) if pnl_pct is not None else None,
                weight_pct=weight.quantize(PCT) if weight is not None else None,
                position_count=counts[key],
            )
        )
    return summaries
