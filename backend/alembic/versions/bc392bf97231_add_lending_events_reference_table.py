"""add lending_events reference table

Revision ID: bc392bf97231
Revises: 1debe6392766
Create Date: 2026-07-08 11:43:35.463201

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc392bf97231'
down_revision: Union[str, Sequence[str], None] = '1debe6392766'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reference data for the B3 lending reconciler (design doc §3.8):
    Empréstimo/Atualização events from the filtered exports. No import_hash
    on purpose — classification context, not portfolio facts; idempotency is
    timeline extension via the natural unique key."""
    op.create_table(
        "lending_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticker", sa.String(length=40), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 10), nullable=False),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("kind", sa.String(length=15), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "ticker", "date", "quantity", "direction", "kind",
            name="uq_lending_event",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("lending_events")
