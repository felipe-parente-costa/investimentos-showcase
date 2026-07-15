"""USD/BRL via the Central Bank PTAX API, cached in `exchange_rates`.

PTAX publishes one closing rate per business day; each date's rate is
cached forever. For dates without a bulletin (weekends, holidays, today
before publication) the most recent earlier rate is used — that is the
correct rate, not a stale one. stale=True only means the API call failed
and an older cached rate was returned.

A module-level memo prevents re-hitting the API more than once per window
when the requested date has no bulletin yet.
"""

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.exchange_rate import ExchangeRate

PTAX_URL = (
    "https://olinda.bcb.gov.br/olinda/servico/PTAX/versao/v1/odata/"
    "CotacaoDolarPeriodo(dataInicial=@dataInicial,dataFinalCotacao=@dataFinalCotacao)"
)
PAIR = "USDBRL"
LOOKBACK_DAYS = 10
FETCH_MEMO_WINDOW = timedelta(minutes=5)
HTTP_TIMEOUT = 10.0


class FxFetchError(Exception):
    pass


@dataclass
class FxResult:
    rate: Decimal
    rate_date: date
    stale: bool


_last_attempt: dict[date, datetime] = {}


def reset_memo() -> None:
    _last_attempt.clear()


def get_usd_brl(db: Session, on: date) -> FxResult | None:
    cached = _latest_cached(db, on)
    if cached is not None and cached.date == on:
        return FxResult(rate=cached.rate, rate_date=cached.date, stale=False)

    now = datetime.now(timezone.utc)
    attempted = _last_attempt.get(on)
    if attempted is not None and now - attempted < FETCH_MEMO_WINDOW:
        if cached is not None:
            return FxResult(rate=cached.rate, rate_date=cached.date, stale=False)
        return None
    _last_attempt[on] = now

    try:
        rates = _fetch_period(on - timedelta(days=LOOKBACK_DAYS), on)
    except FxFetchError:
        if cached is not None:
            return FxResult(rate=cached.rate, rate_date=cached.date, stale=True)
        return None

    _store_missing(db, rates)
    cached = _latest_cached(db, on)
    if cached is None:
        return None
    return FxResult(rate=cached.rate, rate_date=cached.date, stale=False)


def get_usd_brl_series(db: Session, start: date, end: date) -> dict[date, Decimal]:
    """Daily PTAX closing rates for [start, end], cached per date.

    Dates without a bulletin (weekends/holidays) are absent from the map;
    callers carry the previous rate forward.
    """
    series = _cached_range(db, start, end)
    if _covers(series, start, end):
        return series

    now = datetime.now(timezone.utc)
    memo_key = date.min  # single slot for range fetches
    attempted = _last_attempt.get(memo_key)
    if attempted is not None and now - attempted < FETCH_MEMO_WINDOW:
        return series
    _last_attempt[memo_key] = now

    try:
        rates = _fetch_period(start, end)
    except FxFetchError:
        return series
    _store_missing(db, rates)
    return _cached_range(db, start, end)


def _cached_range(db: Session, start: date, end: date) -> dict[date, Decimal]:
    rows = db.execute(
        select(ExchangeRate.date, ExchangeRate.rate).where(
            ExchangeRate.pair == PAIR,
            ExchangeRate.date >= start,
            ExchangeRate.date <= end,
        )
    ).all()
    return {row.date: row.rate for row in rows}


def _covers(series: dict[date, Decimal], start: date, end: date) -> bool:
    # PTAX has no bulletin on weekends/holidays; a week of slack on each
    # edge distinguishes "gap in cache" from "no bulletin yet".
    slack = timedelta(days=7)
    return bool(series) and min(series) <= start + slack and max(series) >= end - slack


def _fetch_period(start: date, end: date) -> dict[date, Decimal]:
    params = {
        "@dataInicial": f"'{start.strftime('%m-%d-%Y')}'",
        "@dataFinalCotacao": f"'{end.strftime('%m-%d-%Y')}'",
        "$top": "5000",
        "$format": "json",
    }
    try:
        response = httpx.get(PTAX_URL, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        data = json.loads(response.text, parse_float=Decimal)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise FxFetchError(f"PTAX request failed: {exc}") from exc

    rates: dict[date, Decimal] = {}
    for item in data.get("value", []):
        rate = item.get("cotacaoVenda")
        when = item.get("dataHoraCotacao")
        if rate is None or not when:
            continue
        rate = rate if isinstance(rate, Decimal) else Decimal(str(rate))
        rates[date.fromisoformat(str(when)[:10])] = rate
    return rates


def _store_missing(db: Session, rates: dict[date, Decimal]) -> None:
    if not rates:
        return
    existing = set(
        db.execute(
            select(ExchangeRate.date).where(
                ExchangeRate.pair == PAIR, ExchangeRate.date.in_(rates)
            )
        ).scalars()
    )
    for rate_date, rate in rates.items():
        if rate_date not in existing:
            db.add(ExchangeRate(pair=PAIR, date=rate_date, rate=rate, source="ptax"))
    db.commit()


def _latest_cached(db: Session, on: date) -> ExchangeRate | None:
    return db.execute(
        select(ExchangeRate)
        .where(ExchangeRate.pair == PAIR, ExchangeRate.date <= on)
        .order_by(ExchangeRate.date.desc())
        .limit(1)
    ).scalar_one_or_none()
