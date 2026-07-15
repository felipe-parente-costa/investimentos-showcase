"""Idempotent transaction importer.

import_hash = sha256(source|date|ticker|operation|quantity|unit_price|seq).
`seq` is the occurrence index of identical rows within one file: B3 exports
legitimately contain repeated rows (e.g. three equal dividend payments on
the same day), which must all be imported, while reimporting the same file
must not duplicate anything. Counting occurrences in file order keeps the
hash deterministic across reimports.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import Market, Operation, Source
from app.models.transaction import Transaction
from app.parsers.base import ParsedTransaction


@dataclass
class ImportSummary:
    imported: int
    duplicates: int


def compute_import_hash(
    source: Source,
    tx_date: date,
    ticker: str,
    operation: Operation,
    quantity: Decimal,
    unit_price: Decimal,
    seq: int,
) -> str:
    payload = "|".join(
        [
            source.value,
            tx_date.isoformat(),
            ticker,
            operation.value,
            f"{quantity.normalize():f}",
            f"{unit_price.normalize():f}",
            str(seq),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def import_transactions(
    db: Session,
    parsed: list[ParsedTransaction],
    source: Source,
    market: Market,
    currency: str,
) -> ImportSummary:
    occurrences: Counter[tuple] = Counter()
    imported = 0
    duplicates = 0
    for item in parsed:
        key = (item.date, item.ticker, item.operation, item.quantity, item.unit_price)
        seq = occurrences[key]
        occurrences[key] += 1
        import_hash = compute_import_hash(
            source, item.date, item.ticker, item.operation, item.quantity, item.unit_price, seq
        )
        exists = db.execute(
            select(Transaction.id).where(Transaction.import_hash == import_hash)
        ).first()
        if exists:
            duplicates += 1
            continue
        db.add(
            Transaction(
                source=source,
                date=item.date,
                ticker=item.ticker,
                asset_name=item.asset_name,
                asset_class=item.asset_class,
                market=market,
                institution=item.institution,
                custody=item.custody,
                indexer=item.indexer,
                currency=item.currency or currency,
                operation=item.operation,
                quantity=item.quantity,
                unit_price=item.unit_price,
                fees=item.fees,
                total_value=item.total_value,
                import_hash=import_hash,
                notes=item.notes,
            )
        )
        imported += 1
    db.commit()
    return ImportSummary(imported=imported, duplicates=duplicates)
