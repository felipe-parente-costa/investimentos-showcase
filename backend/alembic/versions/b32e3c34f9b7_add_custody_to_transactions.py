"""add custody to transactions

Revision ID: b32e3c34f9b7
Revises: 09d5243d085b
Create Date: 2026-06-18 21:17:51.342925

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b32e3c34f9b7'
down_revision: Union[str, Sequence[str], None] = '09d5243d085b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transactions",
        sa.Column(
            "custody",
            sa.Enum("binance", "cold_wallet", native_enum=False, length=20),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "custody")
