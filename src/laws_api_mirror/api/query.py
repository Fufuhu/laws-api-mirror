"""キーワード検索式のパーサとコンパイラ（設計 §5 / §7.1）。

ブール検索式（AND / OR / NOT・括弧・ワイルドカード ``*`` ``?``・``"..."`` 句）を
解析して AST にし、pg_bigm が効く ``text_plain`` の LIKE 条件にコンパイルする。

構文（緩く解釈し、不正でも可能な範囲で受理する）:

- ``A B`` / ``A AND B`` / ``A & B``: AND（並置は暗黙 AND）
- ``A OR B`` / ``A | B``: OR
- ``NOT A`` / ``! A``: NOT
- ``( ... )``: グルーピング
- ``"語 句"``: 空白を含む句リテラル
- 語中の ``*`` は任意長、``?`` は任意 1 文字のワイルドカード
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import ColumnElement, and_, not_, or_
from sqlalchemy.orm import InstrumentedAttribute


@dataclass(frozen=True)
class Term:
    value: str


@dataclass(frozen=True)
class Not:
    child: Node


@dataclass(frozen=True)
class And:
    left: Node
    right: Node


@dataclass(frozen=True)
class Or:
    left: Node
    right: Node


Node = Term | Not | And | Or


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
        elif ch == "(":
            tokens.append(("LPAREN", ch))
            i += 1
        elif ch == ")":
            tokens.append(("RPAREN", ch))
            i += 1
        elif ch == '"':
            end = text.find('"', i + 1)
            if end == -1:
                tokens.append(("TERM", text[i + 1 :]))
                i = n
            else:
                tokens.append(("TERM", text[i + 1 : end]))
                i = end + 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in '()"':
                i += 1
            word = text[start:i]
            upper = word.upper()
            if word == "&" or upper == "AND":
                tokens.append(("AND", word))
            elif word == "|" or upper == "OR":
                tokens.append(("OR", word))
            elif word == "!" or upper == "NOT":
                tokens.append(("NOT", word))
            else:
                tokens.append(("TERM", word))
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _advance(self) -> None:
        self._pos += 1

    def parse(self) -> Node | None:
        if not self._tokens:
            return None
        return self._parse_or()

    def _parse_or(self) -> Node | None:
        left = self._parse_and()
        while (tok := self._peek()) is not None and tok[0] == "OR":
            self._advance()
            right = self._parse_and()
            left = Or(left, right) if left is not None and right is not None else (left or right)
        return left

    def _parse_and(self) -> Node | None:
        left = self._parse_not()
        while (tok := self._peek()) is not None and tok[0] in {"AND", "NOT", "TERM", "LPAREN"}:
            if tok[0] == "AND":
                self._advance()
            right = self._parse_not()
            if right is None:
                break
            left = And(left, right) if left is not None else right
        return left

    def _parse_not(self) -> Node | None:
        if (tok := self._peek()) is not None and tok[0] == "NOT":
            self._advance()
            child = self._parse_atom()
            return Not(child) if child is not None else None
        return self._parse_atom()

    def _parse_atom(self) -> Node | None:
        tok = self._peek()
        if tok is None:
            return None
        if tok[0] == "LPAREN":
            self._advance()
            node = self._parse_or()
            if (close := self._peek()) is not None and close[0] == "RPAREN":
                self._advance()
            return node
        if tok[0] == "TERM":
            self._advance()
            return Term(tok[1])
        # 行き場のない演算子・閉じ括弧は読み飛ばす
        self._advance()
        return self._parse_atom()


def parse_query(text: str) -> Node | None:
    """検索式を AST に解析する。空・無意味なら None。"""
    return _Parser(_tokenize(text)).parse()


def _like_pattern(term: str) -> str:
    """検索語を LIKE パターンに変換する（``*``→``%``、``?``→``_``、部分一致）。"""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    body = escaped.replace("*", "%").replace("?", "_")
    return f"%{body}%"


def compile_condition(node: Node, column: InstrumentedAttribute[str | None]) -> ColumnElement[bool]:
    """AST を ``column`` に対する SQL 条件にコンパイルする。"""
    if isinstance(node, Term):
        return column.like(_like_pattern(node.value), escape="\\")
    if isinstance(node, Not):
        return not_(compile_condition(node.child, column))
    if isinstance(node, And):
        return and_(compile_condition(node.left, column), compile_condition(node.right, column))
    return or_(compile_condition(node.left, column), compile_condition(node.right, column))


def highlight_terms(node: Node, *, negated: bool = False) -> list[str]:
    """ハイライト対象の肯定リテラル（ワイルドカードを除去）を集める。"""
    if isinstance(node, Term):
        if negated:
            return []
        literal = node.value.replace("*", "").replace("?", "")
        return [literal] if literal else []
    if isinstance(node, Not):
        return highlight_terms(node.child, negated=not negated)
    return [
        *highlight_terms(node.left, negated=negated),
        *highlight_terms(node.right, negated=negated),
    ]
