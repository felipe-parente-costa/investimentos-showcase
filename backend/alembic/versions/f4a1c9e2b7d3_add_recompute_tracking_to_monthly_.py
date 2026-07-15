"""add recompute tracking to monthly_snapshots

Revision ID: f4a1c9e2b7d3
Revises: bc392bf97231
Create Date: 2026-07-14 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a1c9e2b7d3'
down_revision: Union[str, Sequence[str], None] = 'bc392bf97231'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """last_recomputed_at + recompute_reason: a snapshot regeneration must
    leave a visible trail (the row is a best-current-estimate of the month
    end with an audit trail, not an immutable photo — definition change
    sanctioned 2026-07-14 with the snapshot reconciler). NULL on rows never
    regenerated since creation."""
    op.add_column(
        "monthly_snapshots",
        sa.Column("last_recomputed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "monthly_snapshots",
        sa.Column("recompute_reason", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("monthly_snapshots", "recompute_reason")
    op.drop_column("monthly_snapshots", "last_recomputed_at")
