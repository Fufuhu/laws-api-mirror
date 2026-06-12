"""検索式パーサ／コンパイラ（DB 非依存）の単体テスト。"""

from __future__ import annotations

from sqlalchemy.sql.elements import ColumnElement

from laws_api_mirror.api.query import (
    And,
    Not,
    Or,
    Term,
    _like_pattern,
    compile_condition,
    highlight_terms,
    parse_query,
)
from laws_api_mirror.db.models import LawNode


def test_parse_implicit_and() -> None:
    """並置は暗黙 AND。"""
    assert parse_query("戦争 平和") == And(Term("戦争"), Term("平和"))


def test_parse_or_and_not() -> None:
    """OR / NOT を解析する。"""
    assert parse_query("国民 OR 天皇") == Or(Term("国民"), Term("天皇"))
    assert parse_query("NOT 戦争") == Not(Term("戦争"))


def test_parse_parentheses_precedence() -> None:
    """括弧でグルーピングできる。"""
    assert parse_query("(国民 OR 天皇) 主権") == And(Or(Term("国民"), Term("天皇")), Term("主権"))


def test_parse_quoted_phrase() -> None:
    """二重引用符は空白を含む句リテラル。"""
    assert parse_query('"戦争 の 放棄"') == Term("戦争 の 放棄")


def test_parse_empty() -> None:
    assert parse_query("   ") is None


def test_like_pattern_substring() -> None:
    """語は部分一致パターンになる。"""
    assert _like_pattern("戦争") == "%戦争%"


def test_like_pattern_wildcards() -> None:
    """``*``→``%``、``?``→``_`` に変換される。"""
    assert _like_pattern("戦*放?") == "%戦%放_%"


def test_like_pattern_escapes_like_specials() -> None:
    """LIKE 特殊文字（% _ \\）はエスケープされる。"""
    assert _like_pattern("a%b_c") == "%a\\%b\\_c%"


def test_compile_returns_boolean_condition() -> None:
    """AST は SQL 条件（ColumnElement）にコンパイルされる。"""
    cond = compile_condition(And(Term("a"), Not(Term("b"))), LawNode.text_plain)
    assert isinstance(cond, ColumnElement)


def test_highlight_terms_excludes_negated_and_wildcards() -> None:
    """NOT 配下は除外、ワイルドカードは除去して収集する。"""
    node = And(Term("国民*"), Not(Term("天皇")))
    assert highlight_terms(node) == ["国民"]
