"""Shared types for broker/exchange file parsers."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.models.enums import AssetClass, Custody, Indexer, Operation


@dataclass
class ParsedTransaction:
    row: int
    date: date
    ticker: str
    asset_name: str | None
    asset_class: AssetClass
    operation: Operation
    quantity: Decimal
    unit_price: Decimal
    total_value: Decimal
    notes: str
    # Quote currency of the row when the file mixes currencies (e.g. Binance
    # pairs); None means "use the import default".
    currency: str | None = None
    fees: Decimal = Decimal("0")
    institution: str | None = None
    custody: Custody | None = None
    indexer: Indexer | None = None


@dataclass
class SkippedRow:
    row: int
    movement_type: str
    reason: str


@dataclass
class ParserWarning:
    """A row the parser keeps as-is but flags for manual reconciliation.

    Used when the source data is insufficient to resolve a case
    deterministically (e.g. a priced stock-lending return leg that is
    indistinguishable from a real trade) — the parser signals, it does not
    guess.
    """

    row: int
    ticker: str
    date: date
    quantity: Decimal
    message: str


@dataclass
class ParseResult:
    transactions: list[ParsedTransaction]
    skipped: list[SkippedRow]
    warnings: list[ParserWarning] = field(default_factory=list)


class ParseError(Exception):
    pass
