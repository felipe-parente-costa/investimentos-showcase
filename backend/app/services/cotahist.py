"""B3 COTAHIST daily file: one download prices every held BR stock/FII,
replacing the 1-request-per-ticker loop against brapi (see docs/backlog
investigation — 21 BR tickers x every 5 min blew brapi's 15k/month quota
~12x over).

Source: B3's SerHist archive, one ZIP per session, published same evening
(observed window 20:17-23:59 BRT the trading day it covers; see the Passo 0
timing investigation for Commit 3). URL pattern:
https://bvmf.bmfbovespa.com.br/InstDados/SerHist/COTAHIST_D{DDMMYYYY}.ZIP

Layout (fixed-width, latin-1, no separator; only '01' quote rows matter
here):
- CODNEG (ticker): cols 13-24
- TPMERC (market type): cols 25-27 — only '010' (mercado à vista / lote
  padrão) is priced; options, forward and fraction markets are skipped.
- PREULT (close): cols 109-121, 2 implied decimals.
- The '00' header row carries DATGER (the session date) at cols 24-31 —
  this is what gets written to Quote.date, not "today": a fallback to an
  older file must be visible in the data itself, not just in this call's
  return value (Commit 3 logs a warning when the caller compares this
  against the expected last business day).

Fail-loud: a ticker this module was asked to price and that a successfully
downloaded, successfully parsed file simply doesn't mention (at TPMERC=010)
raises immediately — that is a parser or coverage bug (wrong column offset,
delisted/renamed ticker, source layout change), never something to shrug
off as "priced at cost". The day-to-day, expected case (file not published
yet, weekend, holiday) is a download failure, not a missing ticker, and is
the only thing the fallback walk-back retries.
"""

import logging
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import AssetClass, Market
from app.models.quote import Quote
from app.models.transaction import Transaction
from app.services.portfolio import compute_positions

logger = logging.getLogger(__name__)

BASE_URL = "https://bvmf.bmfbovespa.com.br/InstDados/SerHist"
HTTP_TIMEOUT = 30.0
MAX_FALLBACK_DAYS = 5
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 1-indexed B3 layout columns, expressed as 0-indexed Python slices.
_TICKER = slice(12, 24)  # CODNEG, cols 13-24
_MARKET_TYPE = slice(24, 27)  # TPMERC, cols 25-27
_CLOSE = slice(108, 121)  # PREULT, cols 109-121 (2 implied decimals)
_HEADER_DATE = slice(23, 31)  # DATGER on the '00' header row, cols 24-31
_LOT_MARKET = "010"  # mercado à vista / lote padrão — the only priced one
_MIN_ROW_LEN = 121
_CENTS = Decimal(100)

# First B3 session whose official close is written by this module (see
# store_cotahist_quotes). From this session on, COTAHIST is the ONLY writer
# of kind='close' rows for Market.br tickers: the yfinance backfill
# (services/history.py) imports this constant and skips BR dates on/after
# it. One shared constant on both sides closes the overnight race — the
# backfill's "today" boundary is the UTC date, so it releases the current
# session's bar at 21:00 BRT (observed live: the 2026-07-13 session's
# yfinance closes landed at 00:03 UTC), hours before the 06:00 job runs.
# Dates compared here are B3 session dates (São Paulo calendar). The cutoff
# is 07-14, not the 07-13 deploy date, because 07-13 already had yfinance
# close rows for all 21 BR tickers when this landed — the audit invariant
# ("every BR close on/after the cutoff has source='cotahist'") must hold
# from its first date.
BR_COTAHIST_CLOSE_CUTOFF = date(2026, 7, 14)


class CotahistError(Exception):
    pass


@dataclass
class CotahistFetchResult:
    session_date: date  # trading date the downloaded file actually covers
    requested_date: date  # date we first tried
    fallback_days: int  # requested_date - session_date, in calendar days
    quotes: dict[str, Decimal]  # ticker -> close price (BRL)


def expected_previous_session(requested: date) -> date:
    """Last weekday (Mon-Fri) strictly before `requested` — a baseline for
    the caller to detect an abnormal fallback (session_date older than
    this). Does not know about B3 holidays (full pregão-calendar checking
    is deferred — see BACKLOG), so it is deliberately conservative: the day
    after a holiday shows one extra fallback day versus this baseline,
    which is an acceptable false positive for a warning log — a human sees
    one unexplained day, not a wall of noise every single Monday from the
    (correctly expected) weekend gap."""
    day = requested - timedelta(days=1)
    while day.weekday() >= 5:  # Saturday=5, Sunday=6
        day -= timedelta(days=1)
    return day


def _download(on: date) -> bytes:
    url = f"{BASE_URL}/COTAHIST_D{on.strftime('%d%m%Y')}.ZIP"
    try:
        # follow_redirects: httpx does not follow by default; if B3 ever
        # fronts the archive with a 301/302, every fallback day would fail
        # with "HTTP 30x" instead of downloading.
        response = httpx.get(
            url,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": BROWSER_UA},
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        raise CotahistError(f"{url}: {exc}") from exc
    if response.status_code != 200:
        raise CotahistError(f"{url}: HTTP {response.status_code}")
    return response.content


def _parse(content: bytes, tickers: set[str]) -> tuple[date, dict[str, Decimal]]:
    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            names = zf.namelist()
            if not names:
                raise CotahistError("COTAHIST zip has no member file")
            text = zf.read(names[0]).decode("latin-1")
    except zipfile.BadZipFile as exc:
        raise CotahistError(f"response was not a valid zip: {exc}") from exc

    lines = text.splitlines()
    header = lines[0] if lines else ""
    if not header.startswith("00COTAHIST"):
        raise CotahistError("missing '00' header row — unexpected file layout")
    session_date = datetime.strptime(header[_HEADER_DATE], "%Y%m%d").date()

    found: dict[str, Decimal] = {}
    for line in lines:
        if line[0:2] != "01" or len(line) < _MIN_ROW_LEN:
            continue
        codneg = line[_TICKER].strip()
        if codneg not in tickers or line[_MARKET_TYPE] != _LOT_MARKET:
            continue
        found[codneg] = Decimal(line[_CLOSE]) / _CENTS

    missing = sorted(tickers - found.keys())
    if missing:
        raise CotahistError(
            f"COTAHIST {session_date.isoformat()} did not include expected "
            f"ticker(s) at TPMERC={_LOT_MARKET}: {', '.join(missing)}"
        )
    return session_date, found


def fetch_cotahist(
    tickers: set[str],
    *,
    on: date | None = None,
    max_fallback_days: int = MAX_FALLBACK_DAYS,
) -> CotahistFetchResult:
    """Download the most recent published COTAHIST daily file, walking back
    day by day (not-yet-published, weekend, holiday) up to
    `max_fallback_days`, then parse `tickers` out of it.

    `on` defaults to today (UTC date): called first thing in the morning
    (before today's own session exists on the source), this naturally lands
    on yesterday's file after one fallback step — no special-casing needed
    by the caller for the ordinary case.
    """
    if not tickers:
        raise CotahistError("no tickers requested")
    requested_date = on or datetime.now(timezone.utc).date()
    download_errors: list[str] = []
    for offset in range(max_fallback_days + 1):
        candidate = requested_date - timedelta(days=offset)
        try:
            content = _download(candidate)
        except CotahistError as exc:
            download_errors.append(str(exc))
            continue
        session_date, quotes = _parse(content, tickers)
        return CotahistFetchResult(
            session_date=session_date,
            requested_date=requested_date,
            fallback_days=(requested_date - session_date).days,
            quotes=quotes,
        )
    raise CotahistError(
        f"no COTAHIST file published for {requested_date.isoformat()} or the "
        f"{max_fallback_days} day(s) before it. Attempts: {'; '.join(download_errors)}"
    )


def br_tickers_from_open_positions(db: Session) -> set[str]:
    """The ticker set this module prices today: open Market.br positions,
    excluding Tesouro Direto (renda fixa trades OTC via the Tesouro system,
    never on the B3 pregão — it is not on COTAHIST at all). Recomputed from
    live transactions on every call — never hardcoded — same source the
    scheduler's brapi loop already reads from."""
    transactions = db.execute(select(Transaction)).scalars().all()
    computed = compute_positions(transactions)
    return {
        position.ticker
        for position in computed.positions.values()
        if position.is_open
        and position.market is Market.br
        and position.asset_class is not AssetClass.fixed_income
    }


def session_already_stored(db: Session, tickers: set[str], session: date) -> bool:
    """True when every requested ticker already has a cotahist quote for
    `session` or newer — lets the daily job skip the download on weekends
    and holidays instead of re-inserting the same session's rows (the cron
    fires every day; Sat+Sun would otherwise re-store Friday twice). A
    ticker with no cotahist row at all (new position) returns False so the
    job runs for it."""
    if not tickers:
        return False
    rows = db.execute(
        select(Quote.ticker, func.max(Quote.date))
        .where(Quote.ticker.in_(tickers), Quote.source == "cotahist")
        .group_by(Quote.ticker)
    ).all()
    latest = {ticker: newest for ticker, newest in rows}
    return all(latest.get(t) is not None and latest[t] >= session for t in tickers)


def _close_row_exists(db: Session, ticker: str, on: date) -> bool:
    return (
        db.execute(
            select(Quote.id)
            .where(Quote.ticker == ticker, Quote.date == on, Quote.kind == "close")
            .limit(1)
        ).first()
        is not None
    )


def close_watermark(db: Session) -> date:
    """Newest official-close session this module has written, clamped to the
    cutoff eve. Sessions at or below the clamp belong to the yfinance era
    (including the 2026-07-13 one-off correction rows, which are
    source='cotahist' but dated June) — the catch-up must never walk back
    past the cutoff."""
    newest = db.execute(
        select(func.max(Quote.date)).where(
            Quote.source == "cotahist", Quote.kind == "close"
        )
    ).scalar()
    floor = BR_COTAHIST_CLOSE_CUTOFF - timedelta(days=1)
    return newest if newest is not None and newest > floor else floor


def weekdays_between(after: date, upto: date) -> list[date]:
    """Mon-Fri dates in (after, upto], ascending — candidate B3 sessions the
    daily job may have missed. Holidays are included on purpose: probing an
    exact day whose file never exists just fails one download and is how a
    holiday is told apart from a missed session (no pregão calendar exists
    in the codebase)."""
    out = []
    day = after + timedelta(days=1)
    while day <= upto:
        if day.weekday() < 5:
            out.append(day)
        day += timedelta(days=1)
    return out


def store_cotahist_closes(db: Session, result: CotahistFetchResult) -> int:
    """Official close rows only — the catch-up path for sessions missed
    while the app was down or the VM suspended. Deliberately writes NO
    intraday row: _latest_cached serves the newest-FETCHED intraday, so
    writing an old session's intraday now would hijack the current-price
    display back to that stale close. Same per-(ticker, date) guard and
    cutoff gate as the main store."""
    if result.session_date < BR_COTAHIST_CLOSE_CUTOFF:
        return 0
    now = datetime.now(timezone.utc)
    written = 0
    for ticker, price in result.quotes.items():
        if _close_row_exists(db, ticker, result.session_date):
            continue
        db.add(
            Quote(
                ticker=ticker,
                date=result.session_date,
                close_price=price,
                currency="BRL",
                source="cotahist",
                kind="close",
                fetched_at=now,
            )
        )
        written += 1
    db.commit()
    return written


def store_cotahist_quotes(db: Session, result: CotahistFetchResult) -> int:
    """Write one intraday Quote row per priced ticker (source='cotahist',
    same table/shape fetch_brapi already writes) and, for sessions on/after
    BR_COTAHIST_CLOSE_CUTOFF, a second row with kind='close' — the official
    daily close that feeds the historical series (TWR/correlation) and
    get_previous_close. The close insert carries its own per-(ticker, date)
    guard: the quotes table has no uniqueness constraint and the history
    backfill's dedup only protects the backfill's own write path, so
    skipping an already-closed pair here is what keeps re-runs (weekend
    cron firings, manual replays) from duplicating rows. Quote.date is the
    file's actual session_date, not "today": a fallback to an older file
    stays visible in the stored data itself, not just in the
    CotahistFetchResult returned here — Commit 3's scheduler compares it
    against the expected last business day and logs a warning when they
    diverge."""
    now = datetime.now(timezone.utc)
    write_close = result.session_date >= BR_COTAHIST_CLOSE_CUTOFF
    closes_written = 0
    for ticker, price in result.quotes.items():
        db.add(
            Quote(
                ticker=ticker,
                date=result.session_date,
                close_price=price,
                currency="BRL",
                source="cotahist",
                kind="intraday",
                fetched_at=now,
            )
        )
        if write_close and not _close_row_exists(db, ticker, result.session_date):
            db.add(
                Quote(
                    ticker=ticker,
                    date=result.session_date,
                    close_price=price,
                    currency="BRL",
                    source="cotahist",
                    kind="close",
                    fetched_at=now,
                )
            )
            closes_written += 1
    db.commit()
    if write_close:
        logger.info(
            "COTAHIST session %s: %d official close row(s) written (%d pair(s) "
            "already had a close row and were left untouched)",
            result.session_date.isoformat(),
            closes_written,
            len(result.quotes) - closes_written,
        )
    return len(result.quotes)
