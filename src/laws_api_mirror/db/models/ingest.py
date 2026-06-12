"""取り込み管理テーブル（設計 §4.9）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from laws_api_mirror.db.base import Base


class IngestRun(Base):
    """取り込み実行単位（§4.9）。"""

    __tablename__ = "ingest_run"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str | None] = mapped_column(Text)  # 'full' | 'delta'
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str | None] = mapped_column(Text)  # 'running' | 'success' | 'failed'
    source_date: Mapped[date | None] = mapped_column(Date)  # delta の場合
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class IngestLawEvent(Base):
    """法令単位の取り込みイベント（§4.9）。完全性検証・再投入の起点。"""

    __tablename__ = "ingest_law_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ingest_run_id: Mapped[int | None] = mapped_column(ForeignKey("ingest_run.id"))
    law_revision_id: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str | None] = mapped_column(Text)  # inserted | updated | skipped | failed
    error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_ingest_law_event_run", "ingest_run_id"),)
