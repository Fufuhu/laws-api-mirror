"""PostgreSQL 固有のカスタム型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import cast
from sqlalchemy.sql.elements import BindParameter, ColumnElement
from sqlalchemy.types import UserDefinedType


class LTREE(UserDefinedType[str]):
    """PostgreSQL ``ltree`` 型（設計 §4.7.1 の elm パス解決に使用）。"""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "ltree"

    def bind_expression(self, bindvalue: BindParameter[str]) -> ColumnElement[str]:
        # バインドパラメータ（text）を ltree に明示キャストする。
        # text → ltree の暗黙キャストが無く、パラメータ化 INSERT が失敗するのを防ぐ。
        return cast(bindvalue, LTREE())
