"""add industry to asset_meta

Revision ID: a1c4e9f6b2d7
Revises: f4a1c9e2b7d3
Create Date: 2026-08-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c4e9f6b2d7'
down_revision: Union[str, Sequence[str], None] = 'f4a1c9e2b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sub-setor (indústria), para a seção Risco. NULL em toda linha de
    asset_meta já cacheada antes desta migração — o campo é preenchido
    naturalmente no próximo fetch de perfil de cada ticker novo. Só se
    aplica a stock/etf: fii/renda fixa/cripto ficam NULL por definição
    (sem classificação de indústria mais fina na fonte)."""
    op.add_column(
        "asset_meta",
        sa.Column("industry", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("asset_meta", "industry")
