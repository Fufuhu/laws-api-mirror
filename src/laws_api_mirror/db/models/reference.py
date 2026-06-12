"""参照（マスタ）テーブル（設計 §4.1）。

enum 文字列を主キーとした lookup テーブル群。値域の追加に Alembic で耐えるため
PostgreSQL ENUM ではなくテーブルとして持つ。初期データは Alembic リビジョンで投入。
"""

from __future__ import annotations

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from laws_api_mirror.db.base import Base


class _CodeLabel(Base):
    """``code`` を主キー、``label`` を説明とする参照テーブルの共通形。"""

    __abstract__ = True

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    label: Mapped[str | None] = mapped_column(Text)


class Era(_CodeLabel):
    """元号（Meiji / Taisho / Showa / Heisei / Reiwa）。"""

    __tablename__ = "era"


class LawNumType(_CodeLabel):
    """法令番号の種別（Constitution / Act / CabinetOrder / ...）。"""

    __tablename__ = "law_num_type"


class LawType(_CodeLabel):
    """法令種別（Constitution / Act / CabinetOrder / ...）。値域は法令番号種別と同じ。"""

    __tablename__ = "law_type"


class Category(_CodeLabel):
    """事項別分類（50 種。001 憲法 … 050 外事）。"""

    __tablename__ = "category"


class RepealStatus(_CodeLabel):
    """廃止状態（None / Repeal / Expire / Suspend / LossOfEffectiveness）。"""

    __tablename__ = "repeal_status"


class CurrentRevisionStatus(_CodeLabel):
    """現行リビジョン状態（CurrentEnforced / UnEnforced / PreviousEnforced / Repeal）。"""

    __tablename__ = "current_revision_status"


class AmendmentType(_CodeLabel):
    """改正種別（1 新規 / 3 被改正 / 8 廃止）。"""

    __tablename__ = "amendment_type"


class Mission(_CodeLabel):
    """制定種別（New / Partial）。"""

    __tablename__ = "mission"
