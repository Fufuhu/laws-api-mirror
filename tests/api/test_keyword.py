"""キーワード検索のハイライト（DB 非依存）の単体テスト。

検索クエリ自体（pg_bigm + tsvector）は compose の PostgreSQL に対する
end-to-end 確認で検証する。
"""

from __future__ import annotations

from laws_api_mirror.api.routers.keyword import highlight_text


def test_highlight_phrase_match() -> None:
    """語句が部分一致するなら、その語句を囲む。"""
    result = highlight_text("第二章　戦争の放棄", "戦争の放棄", ["戦争", "放棄"], "span")
    assert result == "第二章　<span>戦争の放棄</span>"


def test_highlight_falls_back_to_tokens() -> None:
    """語句が連続一致しない場合は各トークンを囲む。"""
    result = highlight_text("戦争を永久に放棄する", "戦争の放棄", ["戦争", "放棄"], "span")
    assert "<span>戦争</span>" in result
    assert "<span>放棄</span>" in result


def test_highlight_custom_tag() -> None:
    """ハイライトタグ名を差し替えられる。"""
    result = highlight_text("国民主権", "国民", ["国民"], "mark")
    assert result == "<mark>国民</mark>主権"
