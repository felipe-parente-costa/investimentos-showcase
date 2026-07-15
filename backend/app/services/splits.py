"""As-traded price reconstruction.

yfinance returns split-ADJUSTED closes (a synthetic series back-adjusted so
past prices are in today's post-split units). Our share counts are
as-traded (splits are carried as separate transactions, like B3), so the
two are inconsistent around split dates and produce spurious returns.

This module un-applies the split adjustment so cached closes become
as-traded:

    as_traded(t) = adjusted(t) * prod(ratio for split_date > t)

Fail-loud principle (option 2): when the split source is unavailable, or
the result fails a consistency guard, we DO NOT write an unverified
as-traded series — we keep the adjusted one and mark it, so downstream can
warn instead of trusting silently-wrong data.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.models.enums import Market

# Price-basis markers stored alongside cached closes (Quote.source suffix).
AS_TRADED = "as_traded"
ADJUSTED = "adjusted"

# Events the split source reports but that never happened to this account.
# yfinance's split LIST occasionally carries a phantom event that is not
# embedded in its price adjustment; keeping such an event blocks the
# as-traded reconciliation of the ticker's REAL splits and leaves the whole
# series -adj. Add an entry only after refuting the event against the
# account's own records (income paid on the pre-split quantity, continuous
# prices across the date). Pointwise, documented exceptions — not generic
# bogus-split detection. Keyed by (ticker, event date).
BOGUS_SPLITS: dict[tuple[str, date], str] = {}

# A buy should land within this band of the same-day as-traded close.
TRADE_TOL = Decimal("0.30")
# At a split date the ADJUSTED series must be ~continuous (yfinance already
# absorbed the split); if it already jumps by ~ratio, it is not adjusted and
# must not be un-adjusted again.
CONTINUITY_BAND = (Decimal("0.70"), Decimal("1.30"))


def yf_symbol(ticker: str, market: Market) -> str:
    return ticker if market is Market.us else f"{ticker}.SA"


def fetch_splits(ticker: str, market: Market) -> list[tuple[date, Decimal]] | None:
    """Splits for a ticker from yfinance. Returns None on ANY failure
    (unresolved symbol, network, parse) — the caller must treat None as
    "source unavailable" and keep the adjusted series."""
    try:
        import yfinance

        series = yfinance.Ticker(yf_symbol(ticker, market)).splits
        return [
            (stamp.date(), Decimal(str(ratio)))
            for stamp, ratio in series.items()
            if float(ratio) != 1.0 and (ticker, stamp.date()) not in BOGUS_SPLITS
        ]
    except Exception:
        return None


def cumulative_factor(day: date, splits: list[tuple[date, Decimal]]) -> Decimal:
    factor = Decimal("1")
    for split_date, ratio in splits:
        if split_date > day:
            factor *= ratio
    return factor


def to_as_traded(
    series: dict[date, Decimal], splits: list[tuple[date, Decimal]]
) -> dict[date, Decimal]:
    """Multiply each close before a split by the cumulative split ratio."""
    return {day: close * cumulative_factor(day, splits) for day, close in series.items()}


def adjusted_is_continuous_at_splits(
    series: dict[date, Decimal], splits: list[tuple[date, Decimal]]
) -> bool:
    """Guard: the ADJUSTED series must be ~continuous at each split date
    (yfinance already absorbed the split). If it already jumps by ~ratio,
    the series is NOT adjusted and we must not un-adjust it again."""
    days = sorted(series)
    for split_date, ratio in splits:
        before = [d for d in days if d < split_date]
        after = [d for d in days if d >= split_date]
        if not before or not after:
            continue  # split outside the cached window; nothing to check
        b = series[before[-1]]
        a = series[after[0]]
        if a == 0:
            return False
        jump = b / a
        lo, hi = CONTINUITY_BAND
        if not (lo <= jump <= hi):
            return False  # discontinuity already present -> not adjusted
    return True


def prices_match_trades(
    series: dict[date, Decimal], buys: list[tuple[date, Decimal]]
) -> bool:
    """Guard: every buy price is within TRADE_TOL of the nearest as-traded
    close (±5 days). A split-factor mismatch makes this fail loudly."""
    days = sorted(series)
    for buy_date, price in buys:
        if price <= 0:
            continue
        near = [d for d in days if abs((d - buy_date).days) <= 5]
        if not near:
            continue
        close = series[min(near, key=lambda d: abs((d - buy_date).days))]
        if close <= 0:
            return False
        if abs(price / close - 1) > TRADE_TOL:
            return False
    return True
