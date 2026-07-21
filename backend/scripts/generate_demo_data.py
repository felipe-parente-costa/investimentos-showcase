"""Generate a fully synthetic demo portfolio and load it through the API.

Every transaction produced here is fictional: the tickers are real, liquid
symbols (so live quotes and the wealth-curve history work out of the box),
but the quantities, prices, dates and the portfolio composition itself are
random draws from plausibility bands — they do not describe any real
account. Prices follow a simple drift-plus-noise path inside a hardcoded
band per ticker; income events are sized as generic percentages.

Usage:
    uv run python scripts/generate_demo_data.py --dry-run
    uv run python scripts/generate_demo_data.py --api-url http://localhost:8001

The target API must be a fresh database: the script POSTs manual
transactions and never deletes anything.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

import httpx

# --------------------------------------------------------------------------
# Universe. Bands are (price at PERIOD_START, price at PERIOD_END) in the
# transaction currency: BRL for the B3 and crypto entries (crypto cost basis
# is BRL-denominated, mirroring the importer's PTAX conversion), USD for the
# US entries.
# --------------------------------------------------------------------------

PERIOD_START = date(2023, 8, 1)
PERIOD_END = date(2026, 6, 30)
US_START = date(2024, 8, 1)  # US/crypto sleeve starts later, like a real account
CRYPTO_START = date(2024, 10, 1)


@dataclass(frozen=True)
class AssetSpec:
    ticker: str
    asset_class: str
    market: str
    currency: str
    band: tuple[Decimal, Decimal]
    name: str
    quantum: Decimal  # quantity granularity (1 = whole shares)
    price_places: int = 2
    indexer: str | None = None


def _spec(t, cls, mkt, cur, lo, hi, name, quantum="1", places=2, indexer=None):
    return AssetSpec(
        t, cls, mkt, cur, (Decimal(lo), Decimal(hi)), name, Decimal(quantum), places, indexer
    )


BR_STOCKS = [
    _spec("RADL3", "stock", "br", "BRL", "27", "19", "Raia Drogasil ON"),
    _spec("RENT3", "stock", "br", "BRL", "62", "38", "Localiza ON"),
    _spec("TOTS3", "stock", "br", "BRL", "28", "38", "Totvs ON"),
    _spec("B3SA3", "stock", "br", "BRL", "12", "14", "B3 ON"),
    _spec("SUZB3", "stock", "br", "BRL", "48", "58", "Suzano ON"),
    _spec("EQTL3", "stock", "br", "BRL", "31", "36", "Equatorial ON"),
    _spec("PRIO3", "stock", "br", "BRL", "46", "42", "PetroRio ON"),
    _spec("SBSP3", "stock", "br", "BRL", "52", "95", "Sabesp ON"),
]

FIIS = [
    _spec("KNRI11", "fii", "br", "BRL", "152", "140", "Kinea Renda Imobiliária FII"),
    _spec("XPML11", "fii", "br", "BRL", "105", "99", "XP Malls FII"),
    _spec("BTLG11", "fii", "br", "BRL", "97", "103", "BTG Logística FII"),
    _spec("KNCR11", "fii", "br", "BRL", "102", "105", "Kinea Rendimentos FII"),
    _spec("HGRU11", "fii", "br", "BRL", "122", "118", "CSHG Renda Urbana FII"),
]

FIXED_INCOME = [
    _spec("Tesouro Selic 2029", "fixed_income", "br", "BRL", "13800", "16300",
          "Tesouro Selic 2029", quantum="0.01", indexer="selic"),
    _spec("Tesouro IPCA+ 2045", "fixed_income", "br", "BRL", "950", "1150",
          "Tesouro IPCA+ 2045", quantum="0.01", indexer="ipca"),
    _spec("Tesouro Prefixado 2031", "fixed_income", "br", "BRL", "620", "710",
          "Tesouro Prefixado 2031", quantum="0.01", indexer="prefixado"),
    _spec("CDB Banco Demo 110% CDI", "fixed_income", "br", "BRL", "1", "1",
          "CDB Banco Demo 110% CDI", quantum="0.01", indexer="selic"),
]

# Submitted as "stock" on purpose: ASSET_CLASS_OVERRIDES reclassifies the
# ETFs at read time, which is exactly the mechanism the demo showcases.
US_ASSETS = [
    _spec("NVDA", "stock", "us", "USD", "105", "165", "NVIDIA Corp", quantum="0.01"),
    _spec("AMZN", "stock", "us", "USD", "175", "225", "Amazon.com Inc", quantum="0.01"),
    _spec("JPM", "stock", "us", "USD", "210", "290", "JPMorgan Chase & Co", quantum="0.01"),
    _spec("KO", "stock", "us", "USD", "62", "70", "Coca-Cola Co", quantum="0.01"),
    _spec("QQQ", "stock", "us", "USD", "450", "560", "Invesco QQQ Trust", quantum="0.01"),
    _spec("VTI", "stock", "us", "USD", "265", "320", "Vanguard Total Stock Market ETF", quantum="0.01"),
]

CRYPTO = [
    _spec("SOL", "crypto", "crypto", "BRL", "620", "420", "Solana",
          quantum="0.0001", places=2),
    _spec("ADA", "crypto", "crypto", "BRL", "1.40", "0.90", "Cardano",
          quantum="0.1", places=4),
    _spec("DOT", "crypto", "crypto", "BRL", "16", "9", "Polkadot",
          quantum="0.01", places=2),
]

BR_BROKER = "Corretora Demo"
US_BROKER = "Broker Demo International"
EXCHANGE = "Exchange Demo"


# --------------------------------------------------------------------------
# Price path: geometric interpolation inside the band plus +-6% noise.
# Synthetic by construction — no real price series is consulted.
# --------------------------------------------------------------------------


def price_on(spec: AssetSpec, day: date, rng: random.Random) -> Decimal:
    lo, hi = spec.band
    span = (PERIOD_END - PERIOD_START).days
    progress = (day - PERIOD_START).days / span
    base = float(lo) * (float(hi) / float(lo)) ** progress
    noisy = base * rng.uniform(0.94, 1.06)
    q = Decimal(10) ** -spec.price_places
    return Decimal(str(noisy)).quantize(q, rounding=ROUND_HALF_UP)


def quantize_qty(spec: AssetSpec, raw: float) -> Decimal:
    q = (Decimal(str(raw)) / spec.quantum).to_integral_value(ROUND_HALF_UP) * spec.quantum
    return max(q, spec.quantum)


def month_starts(start: date, end: date) -> list[date]:
    out, cur = [], date(start.year, start.month, 1)
    while cur <= end:
        out.append(cur)
        cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return out


def business_day(rng: random.Random, month_start: date) -> date:
    day = month_start + timedelta(days=rng.randint(1, 24))
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return min(day, PERIOD_END)


# --------------------------------------------------------------------------
# Portfolio simulation
# --------------------------------------------------------------------------


def build_transactions(seed: int) -> list[dict]:
    rng = random.Random(seed)
    txs: list[dict] = []
    held: dict[str, Decimal] = {}  # ticker -> quantity (crypto: per custody)

    def emit(spec: AssetSpec, day: date, op: str, qty: Decimal, price: Decimal,
             custody: str | None = None, institution: str | None = None,
             note: str = "synthetic demo data") -> None:
        txs.append({
            "date": day.isoformat(),
            "ticker": spec.ticker,
            "asset_name": spec.name,
            "asset_class": spec.asset_class,
            "market": spec.market,
            "institution": institution or BR_BROKER,
            "custody": custody,
            "indexer": spec.indexer,
            "currency": spec.currency,
            "operation": op,
            "quantity": str(qty),
            "unit_price": str(price),
            "fees": "0",
            "notes": note,
        })

    # ---- B3 stocks: 2-3 buys per month across the sleeve, occasional sell.
    for month in month_starts(PERIOD_START, PERIOD_END):
        for spec in rng.sample(BR_STOCKS, rng.randint(2, 3)):
            day = business_day(rng, month)
            qty = quantize_qty(spec, rng.randint(5, 40))
            emit(spec, day, "buy", qty, price_on(spec, day, rng))
            held[spec.ticker] = held.get(spec.ticker, Decimal(0)) + qty
        # A profit-taking sell every ~5 months on something already held.
        if rng.random() < 0.2:
            candidates = [s for s in BR_STOCKS if held.get(s.ticker, 0) > 30]
            if candidates:
                spec = rng.choice(candidates)
                day = business_day(rng, month)
                qty = quantize_qty(spec, int(held[spec.ticker]) // 3)
                emit(spec, day, "sell", qty, price_on(spec, day, rng))
                held[spec.ticker] -= qty

    # ---- B3 stock income: semiannual dividend or JCP on held names.
    for spec in BR_STOCKS:
        for month in month_starts(PERIOD_START, PERIOD_END)[3::6]:
            qty = held.get(spec.ticker)
            if not qty:
                continue
            day = business_day(rng, month)
            per_share = (price_on(spec, day, rng) * Decimal(rng.uniform(0.005, 0.02)).quantize(Decimal("0.0001")))
            emit(spec, day, rng.choice(["dividend", "jcp"]), qty,
                 per_share.quantize(Decimal("0.0001")))

    # ---- FIIs: buys every other month, monthly yield on held quantity.
    for i, month in enumerate(month_starts(PERIOD_START, PERIOD_END)):
        if i % 2 == 0:
            spec = rng.choice(FIIS)
            day = business_day(rng, month)
            qty = quantize_qty(spec, rng.randint(3, 15))
            emit(spec, day, "buy", qty, price_on(spec, day, rng))
            held[spec.ticker] = held.get(spec.ticker, Decimal(0)) + qty
        for spec in FIIS:
            qty = held.get(spec.ticker)
            if not qty:
                continue
            day = business_day(rng, month)
            per_share = (price_on(spec, day, rng) * Decimal("0.008")).quantize(Decimal("0.01"))
            emit(spec, day, "yield", qty, per_share)

    # ---- Tesouro Direto: one buy per quarter, rotating titles. CDB: two lumps.
    tesouro = [s for s in FIXED_INCOME if s.ticker.startswith("Tesouro")]
    for i, month in enumerate(month_starts(PERIOD_START, PERIOD_END)[::3]):
        spec = tesouro[i % len(tesouro)]
        day = business_day(rng, month)
        qty = quantize_qty(spec, rng.uniform(0.3, 1.6))
        emit(spec, day, "buy", qty, price_on(spec, day, rng))
    cdb = FIXED_INCOME[-1]
    for month in (date(2024, 2, 1), date(2025, 9, 1)):
        day = business_day(rng, month)
        emit(cdb, day, "buy", Decimal(rng.randint(4000, 9000)), Decimal("1"))

    # ---- US sleeve (USD-native): monthly fractional buys, quarterly dividends.
    for month in month_starts(US_START, PERIOD_END):
        for spec in rng.sample(US_ASSETS, rng.randint(1, 2)):
            day = business_day(rng, month)
            qty = quantize_qty(spec, rng.uniform(0.2, 3.0))
            emit(spec, day, "buy", qty, price_on(spec, day, rng), institution=US_BROKER)
            held[spec.ticker] = held.get(spec.ticker, Decimal(0)) + qty
    for spec in (s for s in US_ASSETS if s.ticker in ("JPM", "KO")):
        for month in month_starts(US_START, PERIOD_END)[2::3]:
            qty = held.get(spec.ticker)
            if not qty:
                continue
            day = business_day(rng, month)
            emit(spec, day, "dividend", qty, Decimal(str(round(rng.uniform(0.3, 1.2), 4))),
                 institution=US_BROKER)

    # ---- Crypto (BRL cost basis, hot wallet), then a cold-storage sweep.
    for month in month_starts(CRYPTO_START, PERIOD_END):
        if rng.random() < 0.7:
            spec = rng.choice(CRYPTO)
            day = business_day(rng, month)
            qty = quantize_qty(spec, rng.uniform(0.5, 4.0) if spec.ticker != "ADA" else rng.uniform(100, 900))
            emit(spec, day, "buy", qty, price_on(spec, day, rng),
                 custody="binance", institution=EXCHANGE)
            held[spec.ticker] = held.get(spec.ticker, Decimal(0)) + qty
    # custody_transfer showcase: move ~60% of the SOL stack to self-custody.
    sol = next(s for s in CRYPTO if s.ticker == "SOL")
    if held.get("SOL"):
        sweep_qty = quantize_qty(sol, float(held["SOL"]) * 0.6)
        txs.append({
            "date": date(2026, 3, 10).isoformat(),
            "ticker": "SOL",
            "asset_name": sol.name,
            "asset_class": "crypto",
            "market": "crypto",
            "institution": EXCHANGE,
            "custody_from": "binance",
            "custody_to": "cold_wallet",
            "indexer": None,
            "currency": "BRL",
            "operation": "custody_transfer",
            "quantity": str(sweep_qty),
            "unit_price": "0",
            "fees": "0",
            "notes": "synthetic demo data — cold storage sweep",
        })

    txs.sort(key=lambda t: t["date"])
    return txs


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8001")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dry-run", action="store_true",
                        help="print a summary and a sample instead of POSTing")
    args = parser.parse_args()

    txs = build_transactions(args.seed)

    by_class: dict[str, int] = {}
    by_op: dict[str, int] = {}
    for t in txs:
        by_class[t["asset_class"]] = by_class.get(t["asset_class"], 0) + 1
        by_op[t["operation"]] = by_op.get(t["operation"], 0) + 1
    print(f"{len(txs)} synthetic transactions "
          f"({txs[0]['date']} .. {txs[-1]['date']})")
    print(f"  by class: {by_class}")
    print(f"  by operation: {by_op}")

    if args.dry_run:
        print("\nSample (first 12):")
        for t in txs[:12]:
            print(f"  {t['date']}  {t['operation']:<16} {t['ticker']:<26} "
                  f"qty={t['quantity']:<12} @ {t['unit_price']} {t['currency']}")
        return

    ok = 0
    with httpx.Client(base_url=args.api_url, timeout=30) as client:
        for t in txs:
            resp = client.post("/transactions", json=t)
            if resp.status_code == 201:
                ok += 1
            else:
                print(f"  FAILED {resp.status_code}: {t['date']} {t['ticker']} "
                      f"{t['operation']} -> {resp.text[:200]}")
    print(f"loaded {ok}/{len(txs)} transactions into {args.api_url}")


if __name__ == "__main__":
    main()
