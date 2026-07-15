"""Sector and country metadata per ticker, cached permanently.

Static rules first (a Tesouro bond has no profile API): fixed income is
Renda fixa/Brasil, FIIs are Fundos imobiliários/Brasil, crypto is
Criptomoedas/Global. Stocks/ETFs/BDRs are fetched from brapi's
summaryProfile module (B3) falling back to yfinance .SA, or yfinance for
US tickers. Values are normalized to pt-BR before storing — these are
display labels for the allocation charts.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.asset_meta import AssetMeta
from app.models.enums import AssetClass, Market
from app.services.quotes import QuoteFetchError, _get_json

FETCH_MEMO_WINDOW = timedelta(minutes=5)

# Keys cover both yfinance (English) and brapi (Portuguese) spellings so
# the two sources converge on one label per sector.
SECTOR_PT = {
    "financial services": "Financeiro",
    "serviços financeiros": "Financeiro",
    "utilities": "Utilidades públicas",
    "utilidade pública": "Utilidades públicas",
    "energy": "Energia",
    "petróleo, gás e biocombustíveis": "Energia",
    "basic materials": "Materiais básicos",
    "materiais básicos": "Materiais básicos",
    "industrials": "Industrial",
    "bens industriais": "Industrial",
    "consumer cyclical": "Consumo cíclico",
    "consumo cíclico": "Consumo cíclico",
    "consumer defensive": "Consumo não cíclico",
    "consumo não cíclico": "Consumo não cíclico",
    "technology": "Tecnologia",
    "tecnologia da informação": "Tecnologia",
    "healthcare": "Saúde",
    "saúde": "Saúde",
    "communication services": "Comunicações",
    "comunicações": "Comunicações",
    "real estate": "Imobiliário",
}

COUNTRY_PT = {
    "brasil": "Brasil",
    "brazil": "Brasil",
    "united states": "Estados Unidos",
    "usa": "Estados Unidos",
    "uruguay": "Uruguai",
    "argentina": "Argentina",
    "china": "China",
    "cayman islands": "Ilhas Cayman",
}


@dataclass
class AssetMetaResult:
    sector: str | None
    country: str | None


_fetch_attempts: dict[str, datetime] = {}


def reset_memo() -> None:
    _fetch_attempts.clear()


def get_asset_meta(
    db: Session, ticker: str, market: Market, asset_class: AssetClass
) -> AssetMetaResult:
    if asset_class is AssetClass.fixed_income:
        return AssetMetaResult(sector="Renda fixa", country="Brasil")
    if asset_class is AssetClass.fii:
        return AssetMetaResult(sector="Fundos imobiliários", country="Brasil")
    if asset_class is AssetClass.crypto:
        return AssetMetaResult(sector="Criptomoedas", country="Global")

    cached = db.get(AssetMeta, ticker)
    if cached is not None:
        return AssetMetaResult(sector=cached.sector, country=cached.country)

    fetcher = META_FETCHERS.get(market)
    if fetcher is None:
        return AssetMetaResult(sector=None, country=None)

    now = datetime.now(timezone.utc)
    attempted = _fetch_attempts.get(ticker)
    if attempted is not None and now - attempted < FETCH_MEMO_WINDOW:
        return AssetMetaResult(sector=None, country=None)
    _fetch_attempts[ticker] = now

    try:
        sector, country, source = fetcher(ticker)
    except QuoteFetchError:
        return AssetMetaResult(sector=None, country=None)

    sector = _normalize(sector, SECTOR_PT)
    country = _normalize(country, COUNTRY_PT)
    if country is None:
        # Listed-without-profile (typically ETFs, which the profile APIs
        # don't classify): default to the listing market's country. Stocks
        # and BDRs that do have a profile keep their real country.
        if market is Market.br:
            country = "Brasil"
        elif market is Market.us:
            country = "Estados Unidos"
    db.add(
        AssetMeta(
            ticker=ticker, sector=sector, country=country, source=source, fetched_at=now
        )
    )
    db.commit()
    return AssetMetaResult(sector=sector, country=country)


def fetch_b3_profile(ticker: str) -> tuple[str | None, str | None, str]:
    try:
        params = {"modules": "summaryProfile"}
        if settings.brapi_token:
            params["token"] = settings.brapi_token
        data = _get_json(f"https://brapi.dev/api/quote/{ticker}", params=params)
        results = data.get("results") or []
        profile = results[0].get("summaryProfile") if results else None
        if profile and (profile.get("sector") or profile.get("country")):
            return profile.get("sector"), profile.get("country"), "brapi"
    except QuoteFetchError:
        pass
    sector, country, _ = fetch_yfinance_profile(f"{ticker}.SA")
    return sector, country, "yfinance"


def fetch_yfinance_profile(ticker: str) -> tuple[str | None, str | None, str]:
    try:
        import yfinance

        info = yfinance.Ticker(ticker).info or {}
    except Exception as exc:
        raise QuoteFetchError(f"yfinance profile failed for {ticker}: {exc}") from exc
    # An ETF returns a populated info dict without sector/country; that is a
    # successful "no classification" answer (caller applies a default and
    # caches it), distinct from an empty dict, which means the lookup
    # itself failed and should be retried.
    if not info.get("symbol") and not info.get("quoteType"):
        raise QuoteFetchError(f"no profile data for {ticker}")
    return info.get("sector"), info.get("country"), "yfinance"


META_FETCHERS: dict[Market, Callable[[str], tuple[str | None, str | None, str]]] = {
    Market.br: fetch_b3_profile,
    Market.us: fetch_yfinance_profile,
}


def _normalize(value: str | None, table: dict[str, str]) -> str | None:
    if not value:
        return None
    return table.get(value.strip().lower(), value.strip())
