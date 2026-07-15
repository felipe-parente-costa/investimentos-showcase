"""Mark-to-market for Tesouro Direto bonds.

Only Tesouro Direto bonds are marked to market. CDB/LCI/LCA and other
private fixed income have no public reference price and stay at cost.

Price source, in order of preference:
1. Official Tesouro Transparente CSV (free, authoritative). The endpoint
   returns 403 to non-browser clients, so we send a browser User-Agent.
   We use ``PU Base Manhã`` (the investor's sell/redemption price) as the
   mark-to-market unit price, refreshed once per business day.
2. brapi.dev /api/v2/treasury (fallback). Wired but currently gated behind
   a paid plan; on the free token it returns 403 and the fallback is a
   no-op. Its parser is based on brapi's published v2 treasury schema and
   is exercised only by tests (no live paid access to verify against).

The whole CSV is parsed once per day into an in-process table so pricing
every held bond triggers a single download.
"""

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Lock

import httpx

from app.core.config import settings

CSV_URL = (
    "https://www.tesourotransparente.gov.br/ckan/dataset/"
    "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
    "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/precotaxatesourodireto.csv"
)
BRAPI_TREASURY_URL = "https://brapi.dev/api/v2/treasury"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 30.0

# "Tesouro IPCA+ 2050" -> ("Tesouro IPCA+", 2050). The captured group equals
# the source's "Tipo Titulo" column verbatim. Tickers that do not start with
# "Tesouro " (CDB/LCI/LCA) return None and stay at cost.
_TICKER_RE = re.compile(r"^(Tesouro .+?)\s+(\d{4})$")


class TreasuryError(Exception):
    """No price source could be reached at all (distinct from a recognized
    bond simply being absent from the source, which returns None)."""


@dataclass
class TreasuryPrice:
    pu: Decimal
    reference_date: date
    source: str


# Source key: (Tipo Titulo, maturity year).
BondKey = tuple[str, int]


def parse_bond_ticker(ticker: str) -> BondKey | None:
    match = _TICKER_RE.match(ticker.strip())
    if not match:
        return None
    return match.group(1).strip(), int(match.group(2))


def fetch_treasury_price(key: BondKey, *, today: date | None = None) -> TreasuryPrice | None:
    """Most recent PU for a bond, official CSV first then brapi fallback.

    Returns None when the bond is recognized but absent from every reachable
    source (caller values it at cost). Raises TreasuryError only when no
    source could be reached at all.
    """
    csv_error: TreasuryError | None = None
    try:
        price = _table(today).get(key)
        if price is not None:
            return price
    except TreasuryError as exc:
        csv_error = exc

    # CSV unreachable, or bond not found in it: try the brapi fallback.
    try:
        price = _fetch_brapi_treasury(key)
        if price is not None:
            return price
    except TreasuryError as brapi_error:
        if csv_error is not None:
            raise TreasuryError(f"{csv_error}; {brapi_error}") from brapi_error

    if csv_error is not None:
        raise csv_error
    return None  # recognized type, no matching bond in any source


# --- Official CSV --------------------------------------------------------

_cache_lock = Lock()
_price_table: dict[BondKey, TreasuryPrice] | None = None
_price_table_day: date | None = None


_history_table: dict[BondKey, dict[date, Decimal]] | None = None
_history_table_day: date | None = None


def reset_cache() -> None:
    """Drop the in-process CSV memo (used by the scheduler day rollover and
    tests)."""
    global _price_table, _price_table_day, _history_table, _history_table_day
    with _cache_lock:
        _price_table = None
        _price_table_day = None
        _history_table = None
        _history_table_day = None


def _table(today: date | None = None) -> dict[BondKey, TreasuryPrice]:
    global _price_table, _price_table_day
    day = today or datetime.now(timezone.utc).date()
    with _cache_lock:
        if _price_table is not None and _price_table_day == day:
            return _price_table
        table = parse_csv(_download_csv())
        _price_table = table
        _price_table_day = day
        return table


def _history_full(today: date | None = None) -> dict[BondKey, dict[date, Decimal]]:
    """Full daily ``PU Base`` series per bond, parsed once per day from the
    same official CSV used for spot pricing (shares the download)."""
    global _history_table, _history_table_day
    day = today or datetime.now(timezone.utc).date()
    with _cache_lock:
        if _history_table is not None and _history_table_day == day:
            return _history_table
        table = parse_history_csv(_download_csv())
        _history_table = table
        _history_table_day = day
        return table


def treasury_pu_history(
    ticker: str, start: date, end: date, *, today: date | None = None
) -> dict[date, Decimal]:
    """Daily ``PU Base`` for a Tesouro bond over [start, end].

    Returns {} for a recognized bond absent from the CSV; raises
    TreasuryError only when the source cannot be reached. Private fixed
    income (parse_bond_ticker -> None) raises, since it has no public price.
    """
    key = parse_bond_ticker(ticker)
    if key is None:
        raise TreasuryError(f"{ticker!r} is not a Tesouro Direto bond")
    series = _history_full(today).get(key, {})
    return {d: pu for d, pu in series.items() if start <= d <= end}


def parse_history_csv(text: str) -> dict[BondKey, dict[date, Decimal]]:
    """Every daily ``PU Base`` per (Tipo Titulo, maturity year). Same columns
    and semantics as :func:`parse_csv`, but keeps the whole series instead of
    collapsing to the latest date."""
    table: dict[BondKey, dict[date, Decimal]] = {}
    reader = csv.reader(io.StringIO(text), delimiter=";")
    next(reader, None)  # header
    for row in reader:
        if len(row) < 8:
            continue
        tipo, venc, base = row[0].strip(), row[1].strip(), row[2].strip()
        try:
            year = int(venc.split("/")[2])
            base_date = datetime.strptime(base, "%d/%m/%Y").date()
            pu = _ptbr_decimal(row[7])
        except (ValueError, IndexError):
            continue
        table.setdefault((tipo, year), {})[base_date] = pu
    return table


def _download_csv() -> str:
    try:
        response = httpx.get(
            CSV_URL,
            headers={"User-Agent": BROWSER_UA},
            timeout=HTTP_TIMEOUT,
            follow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except httpx.HTTPError as exc:
        raise TreasuryError(f"Tesouro CSV download failed: {exc}") from exc


def parse_csv(text: str) -> dict[BondKey, TreasuryPrice]:
    """Latest ``PU Base Manhã`` per (Tipo Titulo, maturity year).

    Columns (semicolon-separated, pt-BR decimals):
    Tipo Titulo; Data Vencimento; Data Base; Taxa Compra; Taxa Venda;
    PU Compra; PU Venda; PU Base.
    """
    table: dict[BondKey, TreasuryPrice] = {}
    reader = csv.reader(io.StringIO(text), delimiter=";")
    next(reader, None)  # header
    for row in reader:
        if len(row) < 8:
            continue
        tipo, venc, base = row[0].strip(), row[1].strip(), row[2].strip()
        try:
            year = int(venc.split("/")[2])
            base_date = datetime.strptime(base, "%d/%m/%Y").date()
            pu = _ptbr_decimal(row[7])
        except (ValueError, IndexError):
            continue
        key = (tipo, year)
        existing = table.get(key)
        if existing is None or base_date > existing.reference_date:
            table[key] = TreasuryPrice(
                pu=pu, reference_date=base_date, source="tesouro_direto"
            )
    return table


def _ptbr_decimal(raw: str) -> Decimal:
    # "3.737,41" -> "3737.41"; "930,97" -> "930.97".
    return Decimal(raw.strip().replace(".", "").replace(",", "."))


# --- brapi fallback (wired, inactive on the free plan) -------------------


def _fetch_brapi_treasury(key: BondKey) -> TreasuryPrice | None:
    tipo, year = key
    name = f"{tipo} {year}"
    params: dict[str, str] = {}
    if settings.brapi_token:
        params["token"] = settings.brapi_token
    try:
        response = httpx.get(
            BRAPI_TREASURY_URL,
            params=params,
            headers={"User-Agent": BROWSER_UA},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        payload = json.loads(response.text, parse_float=Decimal)
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise TreasuryError(f"brapi treasury unavailable: {exc}") from exc

    items = payload.get("treasury") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        raise TreasuryError("brapi treasury: unexpected payload shape")
    for item in items:
        if str(item.get("name", "")).strip() != name:
            continue
        # sellPrice = redemption (PU Venda), matching our PU Base choice.
        raw = item.get("sellPrice", item.get("unitPrice"))
        if raw is None:
            return None
        return TreasuryPrice(
            pu=_as_decimal(raw),
            reference_date=_brapi_date(item.get("updatedAt")),
            source="brapi_treasury",
        )
    return None


def _brapi_date(value: object) -> date:
    if value:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            pass
    return datetime.now(timezone.utc).date()


def _as_decimal(value: object) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))
