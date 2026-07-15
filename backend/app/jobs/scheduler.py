"""In-process APScheduler jobs.

- refresh_quotes: every 5 minutes (and once at startup). US (yfinance),
  crypto (Binance) and Tesouro Direto (market=br but asset_class=
  fixed_income, marked to market via Tesouro Transparente). Market.br
  stocks/FIIs are excluded — refresh_br_quotes_daily covers those. This is
  the only caller allowed to fetch quotes live (`get_quote(..., live=True)`);
  on-demand /portfolio requests read the cache only and never fetch.
- refresh_br_quotes_daily: once a day (06:00 BRT — see the Passo 0 timing
  investigation: COTAHIST publishes 20:17-23:59 BRT the session it covers,
  this leaves >6h of margin) AND once at startup, with a catch-up walk for
  official closes of sessions missed while the app was down/suspended
  (reconciler pattern — the cron instant alone is a lottery on a machine
  that sleeps). Batch-prices every open Market.br stock/FII from a single
  COTAHIST download instead of one brapi call per ticker per 5-minute tick
  (21 tickers x 288 ticks/day was ~12x brapi's 15k/month quota).
- refresh_br_stock_quotes_afternoon: once per weekday (15:00 BRT), one
  brapi call per open BR *stock* (FIIs stay on the daily close only) —
  brings an intraday price on top of the COTAHIST D-1 close for the rest
  of the afternoon. Budget: 13 tickers x ~22 trading days ~= 290/month,
  well under brapi's 1,000/month free quota even with fetch_ibov's
  ~150-310 on the same token. Additive by design: any failure (one ticker
  or the whole window) just leaves the COTAHIST close serving as before.
  Known limitation: the mon-fri cron does not know B3 holidays (no pregão
  calendar exists in the codebase — same gap as expected_previous_session);
  on a holiday brapi returns the previous session's close, a harmless
  duplicate.
- reconcile_monthly_snapshots: daily and at startup (replaces the old
  day-1 cron, which lost its only firing chance on 2026-07-01). Creates
  the previous month's snapshot when missing and regenerates any COMPLETED
  month whose stored numbers went stale (a close row dated inside its
  window, or a transaction dated up to its month end, landed after the
  snapshot was computed). The current month is excluded dynamically — its
  partial photo belongs to the manual button. Every regeneration records
  last_recomputed_at + recompute_reason.
- daily_backup: once a day, copies the SQLite database into backups/ and
  rotates to the most recent backups.
"""

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.enums import AssetClass, Market
from app.models.quote import Quote
from app.models.transaction import Transaction
from app.services.backup import BackupError, create_backup
from app.services.cotahist import (
    CotahistError,
    br_tickers_from_open_positions,
    close_watermark,
    expected_previous_session,
    fetch_cotahist,
    session_already_stored,
    store_cotahist_closes,
    store_cotahist_quotes,
    weekdays_between,
)
from app.services.fx import get_usd_brl
from app.services.portfolio import compute_positions
from app.services.quotes import (
    SAO_PAULO,
    QuoteFetchError,
    fetch_brapi,
    get_crypto_usd_quote,
    get_quote,
)
from app.models.monthly_snapshot import MonthlySnapshot
from app.services.reports import (
    generate_monthly_snapshot,
    month_bounds,
    previous_month,
)

logger = logging.getLogger(__name__)

REFRESH_MINUTES = 5
BR_QUOTES_HOUR_UTC = 9  # 06:00 BRT
BR_QUOTES_MINUTE_UTC = 0
# 15:00 BRT. Brazil abolished DST in 2019, so BRT is a fixed UTC-3 offset —
# a fixed UTC cron hour is safe (same convention as BR_QUOTES_HOUR_UTC).
BR_AFTERNOON_HOUR_UTC = 18
BR_AFTERNOON_MINUTE_UTC = 0
# Budget guard: the ticker list is derived live from open positions, so it
# grows silently with every new BR stock bought — exactly the unwatched
# growth that caused the original quota blowout (21 tickers in the 5-minute
# loop ~= 181k calls/month). 20 tickers x ~22 sessions ~= 440 calls/month,
# which still fits the 1,000/month hard limit next to fetch_ibov's estimated
# ~150-310; past that the margin is no longer a given. The job keeps pricing
# every ticker (never aborts, never truncates silently) but logs a loud
# warning so the growth is a conscious decision, not a surprise on the bill.
BR_AFTERNOON_TICKER_BUDGET = 20


def refresh_quotes() -> None:
    with SessionLocal() as db:
        transactions = db.execute(select(Transaction)).scalars().all()
        computed = compute_positions(transactions)
        fresh = 0
        served_stale = 0
        needs_fx = False
        crypto_usd_warmed: set[str] = set()
        for position in computed.positions.values():
            if not position.is_open:
                continue
            if position.market is Market.br and position.asset_class is not AssetClass.fixed_income:
                continue  # covered once/day by refresh_br_quotes_daily (COTAHIST)
            if position.currency != "BRL":
                needs_fx = True
            quote = get_quote(
                db, position.ticker, position.market, position.asset_class, live=True
            )
            if quote is not None:
                if quote.stale:
                    served_stale += 1
                else:
                    fresh += 1
                if quote.currency != "BRL":
                    needs_fx = True
            # The USD view of the Cripto section reads the {ticker}USDT cache
            # with live=False; this job is what keeps it warm. Positions are
            # keyed (ticker, custody) — hot/cold BTC share one USDT quote.
            if position.market is Market.crypto and position.ticker not in crypto_usd_warmed:
                crypto_usd_warmed.add(position.ticker)
                get_crypto_usd_quote(db, position.ticker, live=True)
        if needs_fx:
            get_usd_brl(db, datetime.now(timezone.utc).date())
        # "fresh" = current price, whether from a live fetch that just ran or
        # a cache hit inside its freshness window (get_quote does not report
        # which); the earlier label "fetched live" overcounted network
        # activity. "stale" = the fetch failed and an old cache row served.
        logger.info(
            "Quote refresh done: %d tickers fresh (fetched or cache hit), "
            "%d served from stale cache after fetch failure",
            fresh,
            served_stale,
        )


def refresh_br_quotes_daily() -> None:
    # The pregão calendar is São Paulo time; the UTC date is already
    # tomorrow between 21:00 BRT and midnight, which would request a
    # not-yet-existent file and skew the expected-session warning.
    today_sp = datetime.now(timezone.utc).astimezone(SAO_PAULO).date()
    expected = expected_previous_session(today_sp)
    with SessionLocal() as db:
        tickers = br_tickers_from_open_positions(db)
        if not tickers:
            logger.info("COTAHIST refresh skipped: no open Market.br positions")
            return
        # Watermark BEFORE the main store: the catch-up below must see the
        # gap the main fetch is about to close, or sessions between the old
        # watermark and today (missed days, holidays aside) are never probed.
        watermark = close_watermark(db)
        result = None
        if session_already_stored(db, tickers, expected):
            # Weekend/holiday: the cron fires daily, but the expected session
            # is already in the table — skip instead of re-inserting it.
            logger.info(
                "COTAHIST refresh skipped: session %s already stored for all "
                "%d tickers", expected.isoformat(), len(tickers),
            )
        else:
            try:
                result = fetch_cotahist(tickers, on=today_sp)
            except CotahistError as exc:
                logger.error("COTAHIST refresh failed: %s", exc)
            else:
                written = store_cotahist_quotes(db, result)

        # Catch-up: the walk-back above only ever lands the NEWEST published
        # file, so a day with the app down/suspended would leave that
        # session's official close missing forever — and the yfinance
        # backfill is blocked from writing BR closes past the cutoff. Probe
        # each candidate weekday exactly (no fallback); a failed download is
        # a holiday or a not-yet-published file, logged and retried on the
        # next run until the watermark passes it.
        stored_session = result.session_date if result is not None else None
        for session in weekdays_between(watermark, expected):
            if session == stored_session:
                continue
            try:
                catchup = fetch_cotahist(tickers, on=session, max_fallback_days=0)
            except CotahistError as exc:
                logger.warning(
                    "COTAHIST catch-up %s: no usable file (%s) — holiday, not "
                    "yet published, or parse failure; will retry next run",
                    session.isoformat(), exc,
                )
                continue
            closes = store_cotahist_closes(db, catchup)
            logger.info(
                "COTAHIST catch-up: session %s recovered, %d official close "
                "row(s) written", catchup.session_date.isoformat(), closes,
            )

    if result is None:
        return

    if result.session_date < expected:
        logger.warning(
            "COTAHIST session %s is %d day(s) older than expected (%s) — source "
            "may be delayed beyond a normal weekend/holiday gap",
            result.session_date.isoformat(),
            (expected - result.session_date).days,
            expected.isoformat(),
        )
    logger.info(
        "COTAHIST refresh done: %d tickers priced (session %s, %d fallback day(s))",
        written,
        result.session_date.isoformat(),
        result.fallback_days,
    )


def refresh_br_stock_quotes_afternoon() -> None:
    """One brapi quote per open BR stock (never FIIs), once per weekday at
    15:00 BRT. Writes source='brapi' rows that _latest_cached picks over the
    morning's COTAHIST close until the next 06:00 job supersedes them.
    Strictly additive: a failed ticker is logged and skipped, a fully failed
    window writes nothing — either way the COTAHIST close keeps serving."""
    with SessionLocal() as db:
        transactions = db.execute(select(Transaction)).scalars().all()
        computed = compute_positions(transactions)
        tickers = sorted(
            position.ticker
            for position in computed.positions.values()
            if position.is_open
            and position.market is Market.br
            and position.asset_class is AssetClass.stock
        )
        if not tickers:
            logger.info("brapi afternoon refresh skipped: no open BR stock positions")
            return
        if len(tickers) > BR_AFTERNOON_TICKER_BUDGET:
            logger.warning(
                "brapi afternoon window: %d open BR stocks exceed the budgeted "
                "%d (~%d calls/month at ~22 sessions, against the 1,000/month "
                "hard limit shared with fetch_ibov) — still pricing all of "
                "them; review the brapi budget in BACKLOG.md",
                len(tickers), BR_AFTERNOON_TICKER_BUDGET, len(tickers) * 22,
            )
        priced = 0
        failed: list[str] = []
        for ticker in tickers:
            try:
                fetched = fetch_brapi(ticker)
            except QuoteFetchError as exc:
                failed.append(ticker)
                logger.warning(
                    "%s: brapi afternoon fetch failed (%s); COTAHIST close keeps serving",
                    ticker, exc,
                )
                continue
            db.add(
                Quote(
                    ticker=ticker,
                    date=fetched.quote_date,
                    close_price=fetched.price,
                    currency=fetched.currency,
                    source=fetched.source,
                    kind="intraday",
                    fetched_at=datetime.now(timezone.utc),
                )
            )
            priced += 1
        db.commit()
    logger.info(
        "brapi afternoon refresh done: %d/%d BR stock tickers priced%s",
        priced,
        len(tickers),
        f" (failed: {', '.join(failed)})" if failed else "",
    )


def reconcile_monthly_snapshots() -> None:
    """Reconciler for the frozen monthly snapshots (Desenho A', 2026-07-14).

    Replaces the old day-1 cron whose single monthly firing was an uptime
    lottery (it provably missed its only chance, 2026-07-01). Two duties:

    1. Create the previous month's snapshot when missing, as_of its last
       day — on the first run of the new month that finds the app alive.
    2. Regenerate any COMPLETED month whose stored numbers are stale:
       a kind='close' row with date <= as_of, or a transaction dated up to
       the month end, landed AFTER the snapshot was computed. This covers
       late imports (observed: +6d and +13d after June closed), manual
       corrections via the transactions API (the M2 case), price
       corrections in quotes, and the month-end close that lands the
       morning after — without write-hooks in the import/quotes paths
       (rejected: 4 extra touchpoints; recursion risk in the quotes
       writer, which runs inside snapshot generation itself).

    The current month is excluded DYNAMICALLY (compared against today's
    São Paulo date, never a constant): its partial photo belongs to the
    manual button, and routine same-month closes would re-flag it daily.
    Every regeneration records last_recomputed_at + recompute_reason."""
    today_sp = datetime.now(timezone.utc).astimezone(SAO_PAULO).date()
    current_ym = f"{today_sp.year:04d}-{today_sp.month:02d}"
    prev_ym, prev_last_day = previous_month(today_sp)
    with SessionLocal() as db:
        missing = db.execute(
            select(MonthlySnapshot).where(MonthlySnapshot.year_month == prev_ym)
        ).scalar_one_or_none() is None
        if missing:
            snapshot = generate_monthly_snapshot(db, prev_last_day)
            if snapshot is None:
                logger.info("Monthly snapshot %s skipped: no transactions", prev_ym)
            else:
                logger.info(
                    "Monthly snapshot %s created (total R$ %s)",
                    prev_ym, snapshot.total_brl,
                )

        rows = db.execute(
            select(MonthlySnapshot)
            .where(MonthlySnapshot.year_month != current_ym)
            .order_by(MonthlySnapshot.year_month)
        ).scalars().all()
        for row in rows:
            month_end = month_bounds(row.as_of_date)[1]
            close_stale = db.execute(
                select(Quote.id).where(
                    Quote.kind == "close",
                    Quote.date <= row.as_of_date,
                    Quote.fetched_at > row.created_at,
                ).limit(1)
            ).first() is not None
            tx_stale = db.execute(
                select(Transaction.id).where(
                    Transaction.date <= month_end,
                    Transaction.created_at > row.created_at,
                ).limit(1)
            ).first() is not None
            if not (close_stale or tx_stale):
                continue
            # Specific reason, not a generic "reconciler ran": exemplar +
            # count per condition, enough to understand months later why the
            # number moved without re-running the investigation.
            reasons = []
            if close_stale:
                n = db.execute(
                    select(func.count()).select_from(Quote).where(
                        Quote.kind == "close",
                        Quote.date <= row.as_of_date,
                        Quote.fetched_at > row.created_at,
                    )
                ).scalar()
                ex = db.execute(
                    select(Quote.ticker, Quote.date).where(
                        Quote.kind == "close",
                        Quote.date <= row.as_of_date,
                        Quote.fetched_at > row.created_at,
                    ).order_by(Quote.fetched_at.desc()).limit(1)
                ).first()
                reasons.append(
                    f"{n} close(s) novo(s) p/ datas <= as_of "
                    f"(ex.: {ex.ticker} {ex.date.isoformat()})"
                )
            if tx_stale:
                n = db.execute(
                    select(func.count()).select_from(Transaction).where(
                        Transaction.date <= month_end,
                        Transaction.created_at > row.created_at,
                    )
                ).scalar()
                ex = db.execute(
                    select(Transaction.ticker, Transaction.date).where(
                        Transaction.date <= month_end,
                        Transaction.created_at > row.created_at,
                    ).order_by(Transaction.created_at.desc()).limit(1)
                ).first()
                reasons.append(
                    f"{n} transação(ões) nova(s) até o fim do mês "
                    f"(ex.: {ex.ticker} {ex.date.isoformat()})"
                )
            before_total = row.total_brl
            snapshot = generate_monthly_snapshot(
                db, row.as_of_date,
                recompute_reason=("reconciler: " + "; ".join(reasons))[:200],
            )
            logger.info(
                "Monthly snapshot %s regenerated (%s): total %s -> %s",
                row.year_month, snapshot.recompute_reason,
                before_total, snapshot.total_brl,
            )


def daily_backup() -> None:
    try:
        result = create_backup()
    except BackupError as exc:
        logger.warning("Daily backup skipped: %s", exc)
        return
    logger.info(
        "Daily backup saved: %s (%d kept, %d rotated out)",
        result.path.name,
        result.total_backups,
        len(result.deleted),
    )


def create_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(
        timezone="UTC",
        # A laptop suspend freezes the WSL VM and every timer fires late on
        # resume; APScheduler's default misfire_grace_time=1s then silently
        # DROPS the run (observed 2026-07-14: process up for 24h straight
        # and the 09:00 UTC cron never executed). Every job here is
        # idempotent, so a late run always beats a dropped one; coalesce
        # folds a multi-firing backlog into a single run.
        job_defaults={"misfire_grace_time": None, "coalesce": True},
    )
    scheduler.add_job(
        refresh_quotes,
        "interval",
        minutes=REFRESH_MINUTES,
        # misfire_grace_time=None is a documented no-op for this job: the
        # next 5-minute tick is minutes away anyway; after a suspend the
        # resumed firing just arrives up to ~5 min earlier (verdict of the
        # 2026-07-14 job-by-job review).
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        refresh_br_quotes_daily,
        "cron",
        hour=BR_QUOTES_HOUR_UTC,
        minute=BR_QUOTES_MINUTE_UTC,
        # Also once at startup: the cron instant is a lottery on a machine
        # that sleeps (down = the firing never existed, memory jobstore has
        # no catch-up). The job is a cheap no-op when nothing is missing;
        # combined with its own catch-up walk it reconciles missed sessions
        # on the first opportunity instead of a fixed hour.
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        refresh_br_stock_quotes_afternoon,
        "cron",
        day_of_week="mon-fri",
        hour=BR_AFTERNOON_HOUR_UTC,
        minute=BR_AFTERNOON_MINUTE_UTC,
        # No out-of-hours guard on purpose (2026-07-14 review): a late
        # firing during the pregão is a live price (the job's purpose);
        # after the close it captures the day's close hours before the
        # 06:00 COTAHIST job; pre-open it echoes the previous close as a
        # harmless session-dated duplicate (680c0fb semantics).
    )
    scheduler.add_job(
        reconcile_monthly_snapshots,
        "cron",
        hour=0,
        minute=30,
        # Same literal config that fixed the COTAHIST job: daily + at
        # startup (next_run_time=now), with the scheduler-wide
        # misfire_grace_time=None + coalesce=True — never a single
        # unattended monthly firing again.
        next_run_time=datetime.now(timezone.utc),
    )
    scheduler.add_job(
        daily_backup,
        "cron",
        hour=0,
        minute=20,
    )
    return scheduler
