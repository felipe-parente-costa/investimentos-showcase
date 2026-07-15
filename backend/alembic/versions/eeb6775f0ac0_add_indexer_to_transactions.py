"""add indexer to transactions

Revision ID: eeb6775f0ac0
Revises: b32e3c34f9b7
Create Date: 2026-06-18 22:29:29.478211

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'eeb6775f0ac0'
down_revision: Union[str, Sequence[str], None] = 'b32e3c34f9b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transactions",
        sa.Column(
            "indexer",
            sa.Enum("ipca", "prefixado", "selic", native_enum=False, length=20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "indexer")
