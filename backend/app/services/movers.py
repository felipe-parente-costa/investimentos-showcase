"""Maiores Variações do Dia — ranks the portfolio's own holdings by their
daily variation for the Mercado card.

Read-only/display: never touches transactions, average price or quantity.

Variation source per segment (matches what the rest of the app already shows):
- br / us: (current quote - previous daily close) / previous close, reusing
  get_quote + get_previous_close — the same formula as the position table.
- crypto: Binance's REAL rolling 24h change (ticker/24hr), to match the BTC
  dominance card; the value shown is the USD spot from the same snapshot.

Excluded from the ranking: renda fixa (segment "rf"), unpriced assets, and
flat/zero variations. The count of skipped assets is reported so the card can
note it (Mercado convention: a dead source shows "—" and never breaks the rest).

The whole payload is cached for 15 min (same window as the BTC card); switching
chips on the frontend reuses it without a refetch.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.transaction import Transaction
from app.schemas.market import MoverOut, MoversBucketOut, MoversOut
from app.services.market import fetch_crypto_24h
from app.services.portfolio import compute_positions
from app.services.quotes import get_crypto_usd_quote, get_previous_close, get_quote
from app.services.segments import segment_of

CACHE_TTL = timedelta(minutes=15)
MAX_PER_SIDE = 6

# Which segments each chip filter's MAIN ranking covers. Crypto is deliberately
# absent from "all": its variation is Binance 24h-rolling, a different metric
# from the stocks' close-to-close, so it must not compete for the gainer/loser
# slots (on a divergent day it would float to the wrong end). Under "all" crypto
# goes to a separate informational band (see crypto_band); under "crypto" it
# ranks normally among itself.
FILTER_SEGMENTS: dict[str, frozenset[str]] = {
    "all": frozenset({"br", "us"}),
    "br": frozenset({"br"}),
    "us": frozenset({"us"}),
    "crypto": frozenset({"crypto"}),
}

_cache: dict = {"at": None, "out": None}


def reset_cache() -> None:
    _cache["at"] = None
    _cache["out"] = None


@dataclass
class Mover:
    ticker: str
    asset_name: str | None
    segment: str
    change_pct: Decimal
    price: Decimal
    currency: str


def eligible_movers(
    db: Session, transactions: list[Transaction]
) -> tuple[list[Mover], int, list[str]]:
    """Build the pool of rankable assets. Returns (movers, skipped, warnings).

    Skips renda fixa, unpriced assets, and flat (zero) variations. Each asset
    is fetched independently: a single failing source is skipped, not fatal.
    """
    computed = compute_positions(transactions)
    movers: list[Mover] = []
    skipped = 0
    warnings: list[str] = []
    # The portfolio engine keys by (ticker, custody), so a coin split across
    # custodies (e.g. BTC hot + cold) yields two positions with the same price
    # and variation. Rank each ticker once.
    seen: set[str] = set()

    for position in computed.positions.values():
        if not position.is_open:
            continue
        segment = segment_of(position.market, position.asset_class)
        # Renda fixa is excluded by spec; only br/us/crypto are rankable.
        if segment not in ("br", "us", "crypto"):
            continue
        if position.ticker in seen:
            continue
        seen.add(position.ticker)

        try:
            mover = _build_mover(db, position, segment)
        except Exception as exc:  # noqa: BLE001 - one dead source must not kill the rest
            warnings.append(
                f"{position.ticker}: variação indisponível ({type(exc).__name__})"
            )
            skipped += 1
            continue

        if mover is None:
            skipped += 1
            continue
        movers.append(mover)

    return movers, skipped, warnings


def _build_mover(db, position, segment: str) -> Mover | None:
    """Variation + current native-currency price for one position, or None when
    it cannot be priced or its variation is zero/unavailable (then it is
    excluded from the ranking)."""
    if segment == "crypto":
        # Binance rolling 24h: price (USD) and change come from one snapshot.
        # Deliberate exception to "only the scheduler fetches live": the
        # rolling 24h change exists in no cache (quotes has no change column),
        # Binance's public API is unmetered, and the 15-min whole-payload
        # cache above bounds the call volume.
        price, change_pct = fetch_crypto_24h(position.ticker)
        currency = "USD"
    else:
        # Cache only, never a live fetch on the request path: the 5-min
        # scheduler keeps US quotes warm and the daily COTAHIST job keeps BR;
        # ranking on a ≤5-min-old cache is indistinguishable for this card.
        quote = get_quote(
            db, position.ticker, position.market, position.asset_class, live=False
        )
        if quote is None:
            return None
        previous_close = get_previous_close(db, position.ticker, quote.quote_date)
        if previous_close is None or previous_close <= 0:
            return None
        change_pct = (quote.price - previous_close) / previous_close
        price = quote.price
        currency = quote.currency

    if change_pct == 0:
        return None
    return Mover(
        ticker=position.ticker,
        asset_name=position.asset_name,
        segment=segment,
        change_pct=Decimal(change_pct).quantize(Decimal("0.000001")),
        price=price,
        currency=currency,
    )


def rank_movers(movers: list[Mover], filter_key: str) -> MoversBucketOut:
    """Top gainers (change_pct desc) and losers (change_pct asc) for a chip
    filter, capped at 6 per side. Fewer than 6 on a side just returns what
    exists — never padded."""
    segments = FILTER_SEGMENTS[filter_key]
    pool = [m for m in movers if m.segment in segments]
    gainers = sorted(
        (m for m in pool if m.change_pct > 0),
        key=lambda m: m.change_pct,
        reverse=True,
    )[:MAX_PER_SIDE]
    losers = sorted(
        (m for m in pool if m.change_pct < 0),
        key=lambda m: m.change_pct,
    )[:MAX_PER_SIDE]
    return MoversBucketOut(
        gainers=[_to_out(m) for m in gainers],
        losers=[_to_out(m) for m in losers],
    )


def crypto_band(movers: list[Mover]) -> list[MoverOut]:
    """Crypto movers for the "all" view's separate band (BTC/ETH …), sorted by
    24h change desc. Informational — not ranked against the stocks."""
    cryptos = sorted(
        (m for m in movers if m.segment == "crypto"),
        key=lambda m: m.change_pct,
        reverse=True,
    )
    return [_to_out(m) for m in cryptos]


def _to_out(m: Mover) -> MoverOut:
    return MoverOut(
        ticker=m.ticker,
        asset_name=m.asset_name,
        segment=m.segment,
        change_pct=m.change_pct,
        price=m.price,
        currency=m.currency,
    )


def build_movers(db: Session, refresh: bool = False) -> MoversOut:
    now = datetime.now(timezone.utc)
    if (
        not refresh
        and _cache["out"] is not None
        and _cache["at"] is not None
        and now - _cache["at"] < CACHE_TTL
    ):
        return _cache["out"]

    transactions = db.execute(select(Transaction)).scalars().all()
    movers, skipped, warnings = eligible_movers(db, list(transactions))
    out = MoversOut(
        filters={key: rank_movers(movers, key) for key in FILTER_SEGMENTS},
        crypto_info=crypto_band(movers),
        skipped=skipped,
        fetched_at=now,
        warnings=warnings,
    )
    _cache["out"] = out
    _cache["at"] = now
    return out
