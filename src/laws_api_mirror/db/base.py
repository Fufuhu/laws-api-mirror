"""SQLAlchemy 宣言ベース。

制約・インデックスの命名規則を固定し、Alembic の自動生成や差分比較を安定させる
（設計 §2.6）。全 ORM モデルはこの ``Base`` を継承する。
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

#: 制約・インデックスの命名規則（Alembic との整合のため明示）
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
