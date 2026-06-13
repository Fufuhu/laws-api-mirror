"""law.law_num の UNIQUE 制約を撤廃（非ユニーク索引に）

Revision ID: 0003lawnum
Revises: 0002procrastinate
Create Date: 2026-06-13

全件取り込みで判明したとおり、異なる ``law_id`` が同一 ``law_num`` 文字列を持つ実データが
存在する（人事院規則・省令など）。設計 §4.2 の UNIQUE 想定を撤廃し、検索用の非ユニーク
索引に置き換える。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003lawnum"
down_revision: Union[str, Sequence[str], None] = "0002procrastinate"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_law_law_num", "law", type_="unique")
    op.create_index("ix_law_law_num", "law", ["law_num"])


def downgrade() -> None:
    op.drop_index("ix_law_law_num", table_name="law")
    op.create_unique_constraint("uq_law_law_num", "law", ["law_num"])
