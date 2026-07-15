"""Parser for the Avenue account statement CSV export.

Layout: UTF-8 with BOM, header "Data transação,Data liquidação,Descrição,
Valor,Saldo". Dates are dd/mm/yyyy; the Valor/Saldo columns use dot
decimals (USD), while quantities and prices inside the Portuguese
descriptions use comma decimals.

Mapping decisions (from the real statements):
- "Compra/Venda de {qty} {TICKER} a $ {price} cada" -> buy/sell. The
  Valor column is the actual settled cash and becomes total_value.
- "Cobrança de taxa de corretagem de {TICKER}" is a separate row; it is
  merged into the same-day trade of that ticker (fees belong in the cost
  basis). A fee without a matching trade is skipped with a reason.
- "Dividendos", "Imposto sobre dividendo" and "Estorno de imposto" are
  recorded as individual dividend rows with signed total_value, so the
  position's income nets out without fragile row pairing.
- Cash-only rows (câmbio, transferência para conta corrente, aluguel de
  ativo sem ticker) do not affect positions and are skipped.

Statements are newest-first and overlap between exports; rows are
reversed to chronological order and deduplicated by the import hash.
"""

import csv
import io
import re
from datetime import datetime
from decimal import Decimal
from typing import BinaryIO

from app.models.enums import AssetClass, Operation
from app.parsers.base import ParseError, ParseResult, ParsedTransaction, SkippedRow

EXPECTED_HEADER = ["Data transação", "Data liquidação", "Descrição", "Valor", "Saldo"]

TICKER = r"([A-Z][A-Z0-9.]{0,9})"
NUMBER = r"([\d.,]+)"

BUY_RE = re.compile(rf"^Compra de {NUMBER} {TICKER} a \$ {NUMBER} cada$")
SELL_RE = re.compile(rf"^Venda de {NUMBER} {TICKER} a \$ {NUMBER} cada$")
DIVIDEND_RE = re.compile(rf"^Dividendos de {TICKER}$")
TAX_RE = re.compile(rf"^Imposto sobre dividendo de {TICKER}$")
REFUND_RE = re.compile(rf"^Estorno de imposto sobre dividendo de {TICKER}$")
FEE_RE = re.compile(rf"^Cobrança de taxa de corretagem de {TICKER}$")

SKIP_DESCRIPTIONS = {
    "câmbio de real para dólar": "currency exchange (cash), no position effect",
    "câmbio de dólar para real": "currency exchange (cash), no position effect",
    "transferência para conta corrente": "cash withdrawal, no position effect",
    "rentabilidade de aluguel de ativo": "lending income without ticker, not attributable",
    "estorno de imposto sobre dividendo de": "tax refund without ticker, not attributable",
}


class AvenueParseError(ParseError):
    pass


def parse_avenue_csv(file: BinaryIO | bytes) -> ParseResult:
    if not isinstance(file, bytes):
        file = file.read()
    try:
        text = file.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise AvenueParseError("File is not UTF-8 text; expected the Avenue CSV") from exc

    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or [h.strip() for h in header] != EXPECTED_HEADER:
        raise AvenueParseError(
            f"Unexpected header {header!r}; expected {EXPECTED_HEADER!r}. "
            "Is this an Avenue account statement export?"
        )

    transactions: list[ParsedTransaction] = []
    skipped: list[SkippedRow] = []
    fees: list[tuple[int, str, Decimal, str]] = []  # row, ticker, amount, date key

    for row_number, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue
        trade_date_raw, _, description, amount_raw, _ = row[:5]
        # Descriptions use a non-breaking space after "$".
        description = description.replace("\xa0", " ").strip()
        key = description.lower()
        trade_date = datetime.strptime(trade_date_raw.strip(), "%d/%m/%Y").date()
        amount = Decimal(amount_raw.strip())

        if key in SKIP_DESCRIPTIONS:
            skipped.append(SkippedRow(row_number, description, SKIP_DESCRIPTIONS[key]))
            continue

        if match := FEE_RE.match(description):
            fees.append((row_number, match.group(1), abs(amount), trade_date.isoformat()))
            continue

        if match := BUY_RE.match(description) or SELL_RE.match(description):
            operation = Operation.buy if description.startswith("Compra") else Operation.sell
            quantity = _pt_decimal(match.group(1))
            ticker = match.group(2)
            unit_price = _pt_decimal(match.group(3))
            transactions.append(
                ParsedTransaction(
                    row=row_number,
                    date=trade_date,
                    ticker=ticker,
                    asset_name=None,
                    asset_class=AssetClass.stock,
                    operation=operation,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_value=abs(amount),
                    notes=f"Avenue: {description}",
                    currency="USD",
                    institution="Avenue",
                )
            )
            continue

        income_match = (
            DIVIDEND_RE.match(description)
            or TAX_RE.match(description)
            or REFUND_RE.match(description)
        )
        if income_match:
            transactions.append(
                ParsedTransaction(
                    row=row_number,
                    date=trade_date,
                    ticker=income_match.group(1),
                    asset_name=None,
                    asset_class=AssetClass.stock,
                    operation=Operation.dividend,
                    quantity=Decimal("0"),
                    unit_price=Decimal("0"),
                    total_value=amount,  # signed: taxes net against dividends
                    notes=f"Avenue: {description}",
                    currency="USD",
                    institution="Avenue",
                )
            )
            continue

        skipped.append(
            SkippedRow(row_number, description, "unmapped description")
        )

    _attach_fees(transactions, fees, skipped)
    # Statements are newest-first; reverse to chronological order.
    transactions.reverse()
    return ParseResult(transactions=transactions, skipped=skipped)


def _attach_fees(
    transactions: list[ParsedTransaction],
    fees: list[tuple[int, str, Decimal, str]],
    skipped: list[SkippedRow],
) -> None:
    trades = [
        t
        for t in transactions
        if t.operation in (Operation.buy, Operation.sell)
    ]
    for row_number, ticker, amount, date_key in fees:
        match = next(
            (
                t
                for t in trades
                if t.ticker == ticker and t.date.isoformat() == date_key and t.fees == 0
            ),
            None,
        )
        if match is None:
            skipped.append(
                SkippedRow(
                    row_number,
                    f"Cobrança de taxa de corretagem de {ticker}",
                    "brokerage fee without a matching same-day trade",
                )
            )
            continue
        match.fees = amount
        match.notes += f"; corretagem $ {amount}"


def _pt_decimal(value: str) -> Decimal:
    # "1.234,56" -> 1234.56; quantities/prices inside descriptions use
    # Brazilian formatting even though the Valor column is dot-decimal.
    return Decimal(value.replace(".", "").replace(",", "."))
