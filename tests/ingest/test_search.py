"""日本語トークナイザ（text_search 生成の前段）の単体テスト。

DB への書き込み（populate_text_search）は compose の PostgreSQL に対する
end-to-end 確認で検証する。本ファイルはトークナイズ結果のみを検証する。
"""

from __future__ import annotations

from laws_api_mirror.ingest.search import tokenize


def test_tokenize_splits_japanese() -> None:
    """日本語文が形態素の表層形で空白区切りになることを確認する。"""
    tokens = tokenize("個人情報の保護に関する法律")
    parts = tokens.split(" ")
    assert len(parts) >= 3  # 複数トークンに分割される
    assert "個人" in parts
    assert "情報" in parts
    assert "法律" in parts


def test_tokenize_empty() -> None:
    """空文字は空文字を返す。"""
    assert tokenize("") == ""
