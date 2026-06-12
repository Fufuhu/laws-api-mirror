"""procrastinate schema (ジョブキュー)

Revision ID: 0002procrastinate
Revises: 31643562a6c2
Create Date: 2026-06-13

Procrastinate のスキーマを専用の ``procrastinate`` スキーマに隔離して作成する
（設計 §11.7.5）。スキーマ SQL はインストール済み procrastinate パッケージ同梱の
``sql/schema.sql`` を適用する。downgrade は ``DROP SCHEMA ... CASCADE`` で完全撤去できる。

注: schema.sql は複数文から成る。asyncpg はプリペアド文で複数コマンドを実行できないため、
ドル引用符・行コメント・文字列リテラルを考慮して 1 文ずつに分割して実行する。
"""
import re
from importlib.resources import files
from typing import Sequence, Union

from alembic import op

revision: str = "0002procrastinate"
down_revision: Union[str, Sequence[str], None] = "31643562a6c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DOLLAR_TAG = re.compile(r"\$[A-Za-z0-9_]*\$")


def _split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    dollar: str | None = None
    in_squote = False
    in_line_comment = False
    while i < n:
        ch = sql[i]
        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
        elif dollar is not None:
            if sql.startswith(dollar, i):
                buf.append(dollar)
                i += len(dollar)
                dollar = None
            else:
                buf.append(ch)
                i += 1
        elif in_squote:
            buf.append(ch)
            if ch == "'":
                in_squote = False
            i += 1
        elif sql.startswith("--", i):
            buf.append("--")
            in_line_comment = True
            i += 2
        elif ch == "'":
            in_squote = True
            buf.append(ch)
            i += 1
        elif ch == "$" and (m := _DOLLAR_TAG.match(sql, i)) is not None:
            dollar = m.group(0)
            buf.append(dollar)
            i += len(dollar)
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS procrastinate")
    # 以降の DDL を procrastinate スキーマに作る（トランザクション内のみ有効）
    op.execute("SET LOCAL search_path TO procrastinate, public")
    schema_sql = files("procrastinate").joinpath("sql/schema.sql").read_text(encoding="utf-8")
    for statement in _split_statements(schema_sql):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS procrastinate CASCADE")
