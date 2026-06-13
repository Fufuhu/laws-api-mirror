"""キーワード検索のハイライト（DB 非依存）の単体テスト。

検索式の解析・コンパイルは test_query.py、実検索は統合テストで検証する。
"""

from __future__ import annotations

from laws_api_mirror.api.query import highlight_text


def test_highlight_wraps_terms() -> None:
    """肯定リテラルを囲む。"""
    result = highlight_text("第二章　戦争の放棄", ["戦争", "放棄"], "span")
    assert result == "第二章　<span>戦争</span>の<span>放棄</span>"


def test_highlight_custom_tag() -> None:
    """ハイライトタグ名を差し替えられる。"""
    assert highlight_text("国民主権", ["国民"], "mark") == "<mark>国民</mark>主権"


def test_highlight_no_terms() -> None:
    """対象語が無ければそのまま。"""
    assert highlight_text("国民主権", [], "span") == "国民主権"
