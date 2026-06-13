"""ページング補助（設計 §7.3）。"""

from __future__ import annotations


def compute_next_offset(total_count: int, offset: int, limit: int, count: int) -> int | None:
    """次ページのオフセット。

    残りがあれば ``offset + limit``、なければ ``None``（§7.3）。
    """
    if total_count - (offset + count) > 0:
        return offset + limit
    return None
