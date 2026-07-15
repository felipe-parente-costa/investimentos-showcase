"""add kind to quotes

Revision ID: 1debe6392766
Revises: a7f1c2d4e5b6
Create Date: 2026-07-04 15:57:06.684123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1debe6392766'
down_revision: Union[str, Sequence[str], None] = 'a7f1c2d4e5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add quotes.kind: 'close' (official daily close, history backfill) vs
    'intraday' (live spot snapshot, quote service). Existing rows — a mix of
    both, written before the split — are deliberately left as 'close' so the
    historical series keeps valuing exactly as before; re-classifying or
    re-backfilling the contaminated past is a separate follow-up task."""
    op.add_column(
        "quotes",
        sa.Column("kind", sa.String(length=10), nullable=False, server_default="close"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("quotes", "kind")
