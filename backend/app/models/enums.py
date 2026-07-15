import enum


class Source(str, enum.Enum):
    cei = "cei"
    avenue = "avenue"
    binance = "binance"
    manual = "manual"


class Custody(str, enum.Enum):
    """Where a crypto asset is held. Orthogonal to `source` (how the record
    was imported): the same BTC can sit in a hot exchange wallet or in
    self-custody. Null for non-crypto assets."""

    binance = "binance"  # hot wallet (exchange)
    cold_wallet = "cold_wallet"  # cold/self-custody

    @property
    def is_cold(self) -> bool:
        return self is Custody.cold_wallet


class Indexer(str, enum.Enum):
    """What a fixed-income bond is indexed to. Derived from the name when
    possible (Tesouro IPCA+ -> ipca) and overridable per transaction for
    cases the name does not reveal (e.g. a prefixed CDB). Null for
    non-fixed-income assets. `selic` covers Selic/CDI post-fixed."""

    ipca = "ipca"
    prefixado = "prefixado"
    selic = "selic"  # Selic / CDI / pós-fixado


class AssetClass(str, enum.Enum):
    stock = "stock"
    fii = "fii"
    etf = "etf"
    fixed_income = "fixed_income"
    crypto = "crypto"


class Market(str, enum.Enum):
    br = "br"
    us = "us"
    crypto = "crypto"


class Operation(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"
    jcp = "jcp"
    yield_ = "yield"
    transfer = "transfer"
    split = "split"
    bonus = "bonus"
    # Pure custody move (crypto hot<->cold): redistributes quantity between
    # custodies of the same ticker at the origin's current average price,
    # without buy/sell semantics or realized P&L. Kept distinct from the
    # overloaded `transfer` (B3 lending settlements) on purpose.
    custody_transfer = "custody_transfer"
