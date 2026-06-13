"""next_offset 計算（§7.3）の単体テスト。"""

from __future__ import annotations

from laws_api_mirror.api.pagination import compute_next_offset


def test_next_offset_when_more_remains() -> None:
    """残りがあれば offset + limit を返す。"""
    # total=250, offset=0, limit=100, count=100 → 残り150 → 100
    assert compute_next_offset(250, 0, 100, 100) == 100
    # 2ページ目 offset=100 → 200
    assert compute_next_offset(250, 100, 100, 100) == 200


def test_next_offset_on_last_page() -> None:
    """最終ページ（残りなし）は None。"""
    # total=250, offset=200, count=50 → 残り0 → None
    assert compute_next_offset(250, 200, 100, 50) is None
    # ちょうど割り切れる場合も残り0 → None
    assert compute_next_offset(200, 100, 100, 100) is None


def test_next_offset_empty() -> None:
    """0 件なら None。"""
    assert compute_next_offset(0, 0, 100, 0) is None
