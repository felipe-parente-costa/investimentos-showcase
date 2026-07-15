"""Classify fixed-income bonds by their indexer (IPCA / Prefixado / Selic).

The indexer is derived from the ticker/name when the wording reveals it
(Tesouro IPCA+ -> IPCA, Tesouro Prefixado -> Prefixado, Tesouro Selic ->
Selic). A manual override on the transaction wins, for cases the name does
not reveal (e.g. a prefixed CDB). When neither the override nor the name
settles it, private fixed income is assumed CDI/post-fixed (the common
case for CDB/LCI/LCA), so it lands under ``selic``.
"""

from app.models.enums import Indexer

# Checked in order; first hit wins. "prefix" before "selic"/"cdi" so a
# "CDB prefixado" is not caught by an unrelated substring.
_KEYWORDS: list[tuple[Indexer, tuple[str, ...]]] = [
    (Indexer.ipca, ("ipca",)),
    (Indexer.prefixado, ("prefix", "pré-fix", "pre-fix", "préfix", "prefixado")),
    (Indexer.selic, ("selic", "cdi", "pós", "pos-fix", "pósfix", "pos fix")),
]


def derive_indexer(ticker: str | None, asset_name: str | None) -> Indexer | None:
    """Indexer inferred from the ticker/name, or None when the wording does
    not reveal it."""
    text = f"{ticker or ''} {asset_name or ''}".lower()
    for indexer, needles in _KEYWORDS:
        if any(needle in text for needle in needles):
            return indexer
    return None


def resolve_indexer(
    ticker: str | None,
    asset_name: str | None,
    manual: Indexer | None,
    *,
    default: Indexer = Indexer.selic,
) -> Indexer:
    """Final indexer for a fixed-income bond: the manual override if set,
    else what the name reveals, else the default (CDI/post-fixed)."""
    if manual is not None:
        return manual
    derived = derive_indexer(ticker, asset_name)
    if derived is not None:
        return derived
    return default
