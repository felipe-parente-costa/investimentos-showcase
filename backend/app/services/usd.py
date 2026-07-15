"""USD view for the EUA (Avenue) and Cripto sections.

These two sections are read in their native currency (USD); Brasil and the
consolidated total stay in BRL. The cost basis is computed in USD using the
USD/BRL (PTAX) of each transaction's date — never today's rate — so the P&L
is the real dollar return without currency contamination:

- EUA: Avenue transactions are already stored in USD, so the cost is direct.
- Cripto: transactions are stored in BRL (USDT buys were converted at import);
  each is repriced to USD by its own date's PTAX. The USDT-origin buys
  round-trip back to their original USDT amount.

Market value uses native USD quotes elsewhere (yfinance for US, Binance USDT
for crypto); this module only handles the cost side and the transaction
repricing, both of which depend on historical FX.
"""

from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models.enums import Market
from app.services.fx import get_usd_brl

ZERO = Decimal("0")


class FxUnavailable(Exception):
    """Raised when no PTAX rate exists for a transaction date, so a USD cost
    cannot be computed without silently using the wrong rate."""

    def __init__(self, on):
        super().__init__(f"USD/BRL (PTAX) indisponível para {on}")
        self.on = on


def _ptax(db: Session, on, cache: dict) -> Decimal:
    if on not in cache:
        result = get_usd_brl(db, on)
        if result is None:
            raise FxUnavailable(on)
        cache[on] = result.rate
    return cache[on]


def to_usd_transactions(db: Session, transactions) -> list:
    """US + crypto transactions denominated in USD.

    US rows pass through unchanged (already USD); crypto rows are repriced by
    the PTAX of their own date. Other markets are dropped — this stream is
    only for the USD sections.
    """
    cache: dict = {}
    out: list = []
    for tx in transactions:
        if tx.market is Market.us:
            out.append(tx)
        elif tx.market is Market.crypto:
            out.append(_reprice(tx, _ptax(db, tx.date, cache)))
    return out


def _reprice(tx, rate: Decimal) -> SimpleNamespace:
    return SimpleNamespace(
        date=tx.date,
        ticker=tx.ticker,
        asset_name=tx.asset_name,
        asset_class=tx.asset_class,
        market=tx.market,
        currency="USD",
        operation=tx.operation,
        quantity=tx.quantity,
        unit_price=(tx.unit_price or ZERO) / rate,
        total_value=(tx.total_value or ZERO) / rate,
        fees=(tx.fees or ZERO) / rate,
        custody=getattr(tx, "custody", None),
        custody_from=getattr(tx, "custody_from", None),
        custody_to=getattr(tx, "custody_to", None),
        indexer=getattr(tx, "indexer", None),
        institution=getattr(tx, "institution", None),
    )
