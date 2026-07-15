"""add custody_from/custody_to to transactions

Revision ID: a7f1c2d4e5b6
Revises: eeb6775f0ac0
Create Date: 2026-06-21 18:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7f1c2d4e5b6"
down_revision: Union[str, Sequence[str], None] = "eeb6775f0ac0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_custody = sa.Enum("binance", "cold_wallet", native_enum=False, length=20)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transactions", sa.Column("custody_from", _custody, nullable=True)
    )
    op.add_column(
        "transactions", sa.Column("custody_to", _custody, nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("transactions", "custody_to")
    op.drop_column("transactions", "custody_from")
