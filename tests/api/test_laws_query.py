"""/laws の order パース（DB 非依存）の単体テスト。"""

from __future__ import annotations

from laws_api_mirror.api.routers.laws import parse_order


def test_parse_order_default() -> None:
    """未指定なら law_id 昇順 1 列。"""
    cols = parse_order(None)
    assert len(cols) == 1
    assert "law_id" in str(cols[0]).lower()


def test_parse_order_desc_and_multi() -> None:
    """- で降順、複数フィールドを順に解釈する。"""
    cols = parse_order("-law_info.promulgation_date,law_info.law_id")
    assert len(cols) == 2
    assert "DESC" in str(cols[0]).upper()
    assert "promulgation_date" in str(cols[0]).lower()


def test_parse_order_ignores_unknown() -> None:
    """ホワイトリスト外は無視し、有効分だけ残る（全滅なら既定）。"""
    cols = parse_order("revision_info.law_title,does.not.exist")
    assert len(cols) == 1
    assert "law_title" in str(cols[0]).lower()
    # 全て未知なら既定（law_id 昇順 1 列）に戻る
    fallback = parse_order("foo,bar")
    assert len(fallback) == 1
    assert "law_id" in str(fallback[0]).lower()
