from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AssetMeta(Base):
    """Sector/country per ticker. Effectively immutable: fetched once."""

    __tablename__ = "asset_meta"

    ticker: Mapped[str] = mapped_column(String(40), primary_key=True)
    sector: Mapped[str | None] = mapped_column(String(80))
    country: Mapped[str | None] = mapped_column(String(60))
    # Sub-setor (ex.: "Banks—Regional"), só para stock/etf. Sem tabela de
    # tradução pt-BR (setor já cobre essa camada); mantido como veio da fonte.
    industry: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(20))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
