"""Freeze the demo API into static JSON for the published showcase.

The public showcase has no backend: it is the same React app reading files
instead of an API. That removes every write endpoint and every moving part
from the public surface — nothing to attack, nothing to keep running, no
cost — at the price of enumerating what the UI can ask for.

Two endpoints have a parameter space too large to enumerate (the returns
chart toggles segments and benchmarks independently; the transactions list
filters, sorts and paginates), so those are frozen as a superset and the
static client filters them in the browser. Everything else is a small,
closed list, written here.

Usage (from backend/, with the demo database):
    APP_DATABASE_URL="sqlite:///$PWD/demo.db" \
    APP_SCHEDULER_ENABLED=false \
    .venv/bin/python scripts/prerender_static_demo.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

if os.environ.get("APP_SCHEDULER_ENABLED", "").lower() not in {"false", "0", "no"}:
    sys.exit("refuse to run with the scheduler on: set APP_SCHEDULER_ENABLED=false")

# Runnable as `python scripts/...` from backend/, like the demo generator.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "data"

RISK_PERIODS = ("3M", "6M", "YTD", "1A", "2A", "MAX")
RETURNS_PERIODS = ("1M", "3M", "6M", "YTD", "1A", "MAX")
CORRELATION_PERIODS = ("3M", "6M", "1A", "MAX")
CAPM_PERIODS = ("6M", "1A", "2A", "MAX")
GRANULARITIES = ("daily", "weekly", "monthly")
SEGMENTS = "total,br,us,crypto,rf"
BENCHMARKS = "cdi,ibov,sp500,btc,ipca6,dolar5"


def slug(path: str, query: str = "") -> str:
    """Same rule the static client uses to find a file: path and sorted
    query, everything that is not alphanumeric collapsed to a dash."""
    raw = path.strip("/")
    if query:
        raw += "--" + "&".join(sorted(query.split("&")))
    return re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-") + ".json"


def freeze(client: TestClient, path: str, query: str = "") -> None:
    url = f"{path}?{query}" if query else path
    response = client.get(url)
    if response.status_code != 200:
        raise SystemExit(f"{url} answered {response.status_code}: {response.text[:200]}")
    target = OUT / slug(path, query)
    target.write_text(json.dumps(response.json(), ensure_ascii=False), encoding="utf-8")
    print(f"  {url}  ->  {target.name}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in OUT.glob("*.json"):
        stale.unlink()

    with TestClient(app) as client:
        print("singles")
        for path in ("/health", "/portfolio", "/portfolio/usdbrl-market", "/market",
                     "/market/movers", "/reports/monthly"):
            freeze(client, path)

        print("history and performance")
        for granularity in GRANULARITIES:
            freeze(client, "/portfolio/history", f"granularity={granularity}")
            freeze(client, "/portfolio/performance", f"granularity={granularity}")

        print("contributions")
        for months in (6, 12, 24):
            freeze(client, "/portfolio/contributions", f"months={months}")

        print("capm")
        for period in CAPM_PERIODS:
            freeze(client, "/portfolio/capm", f"period={period}")

        print("correlation")
        for period in CORRELATION_PERIODS:
            freeze(client, "/portfolio/correlation", f"period={period}")
            for segment in ("br", "us", "crypto"):
                freeze(client, "/portfolio/correlation", f"period={period}&segment={segment}")

        print("risk")
        for period in RISK_PERIODS:
            for group_by in ("sector", "subsector"):
                freeze(client, "/portfolio/risk", f"period={period}&group_by={group_by}")

        print("returns (superset: every segment and benchmark, filtered in the browser)")
        for period in RETURNS_PERIODS:
            for currency in ("BRL", "USD"):
                freeze(
                    client,
                    "/portfolio/returns",
                    f"segments={SEGMENTS}&benchmarks={BENCHMARKS}&period={period}&currency={currency}",
                )

        print("monthly reports")
        listing = client.get("/reports/monthly").json()
        for snapshot in listing["items"]:
            freeze(client, f"/reports/monthly/{snapshot['year_month']}")

        print("transactions (superset: filtered, sorted and paged in the browser)")
        freeze(client, "/transactions", "limit=100000&offset=0")

        # The banner needs a date the visitor can trust: when this bundle was
        # built, plus the last day the demo book actually has data for.
        portfolio = client.get("/portfolio").json()
        history = client.get("/portfolio/history?granularity=daily").json()
        points = history.get("points") or history.get("series") or []
        last_day = points[-1].get("date") if points else None
        # Displayed to a Brazilian visitor, so dated in São Paulo — a build
        # finished at 22h here is still today, not tomorrow in UTC.
        today_br = datetime.now(ZoneInfo("America/Sao_Paulo")).date()
        (OUT / "meta.json").write_text(
            json.dumps(
                {
                    "generated_at": today_br.isoformat(),
                    "data_through": last_day,
                    "positions": len(portfolio.get("positions", [])),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"  meta.json  ->  gerado em {today_br}, dados até {last_day}")

    total = len(list(OUT.glob("*.json")))
    print(f"\n{total} arquivos em {OUT}")


if __name__ == "__main__":
    main()
