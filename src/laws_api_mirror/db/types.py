"""PostgreSQL 固有のカスタム型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType


class LTREE(UserDefinedType[str]):
    """PostgreSQL ``ltree`` 型（設計 §4.7.1 の elm パス解決に使用）。"""

    cache_ok = True

    def get_col_spec(self, **kw: Any) -> str:
        return "ltree"
