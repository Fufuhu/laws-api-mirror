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
    highlight_text,
    parse_query,
    snippet_around,
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


def test_highlight_text_wraps_each_occurrence() -> None:
    """全出現箇所をタグで囲む。"""
    assert highlight_text("勅令と勅令", ["勅令"], "span") == "<span>勅令</span>と<span>勅令</span>"


def test_highlight_text_no_nested_wrap_for_overlapping_terms() -> None:
    """部分一致する語が重なっても入れ子のタグにならない（区間マージ）。"""
    # "勅" は "勅令" の一部。長短どちらの順でも一重のタグで囲む。
    assert highlight_text("勅令", ["勅", "勅令"], "span") == "<span>勅令</span>"


def test_highlight_text_returns_value_when_no_hit() -> None:
    assert highlight_text("政令", ["勅令"], "span") == "政令"


def test_snippet_around_returns_full_when_short() -> None:
    """``length`` 以下なら全文を返す。"""
    assert snippet_around("短い文", ["文"], 100) == "短い文"


def test_snippet_around_windows_first_hit() -> None:
    """ヒットを中心に窓を切り出し前後に省略記号を付す。"""
    value = "あ" * 50 + "勅令" + "い" * 50
    out = snippet_around(value, ["勅令"], 10)
    assert "勅令" in out
    assert out.startswith("…") and out.endswith("…")
    assert len(out) <= 10 + 2  # 窓 + 前後の省略記号
