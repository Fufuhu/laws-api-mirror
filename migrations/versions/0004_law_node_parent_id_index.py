"""law_node.parent_id に索引を追加（ON DELETE CASCADE のカスケード検査用）

Revision ID: 0004parentidx
Revises: 0003lawnum
Create Date: 2026-06-16

law_node は隣接リスト（parent_id → law_node.id, ON DELETE CASCADE）。参照側カラム
parent_id を先頭に持つ索引が無いため、ノード削除のたびに PostgreSQL のカスケード検査
（WHERE parent_id = ?）が law_node 全表スキャンになる。法令の洗い替え（DELETE → COPY）
を行う bootstrap / 日次差分の再取り込みで、既存データがあると 1 法令あたり数分かかり
事実上停止する。parent_id への索引でカスケード検査を index scan 化する。

既存の ix_law_node_revision_parent_ordinal は (law_revision_id, parent_id, ordinal) で
parent_id が先頭でないため WHERE parent_id = ? には使えない。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0004parentidx"
down_revision: Union[str, Sequence[str], None] = "0003lawnum"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_law_node_parent_id", "law_node", ["parent_id"])


def downgrade() -> None:
    op.drop_index("ix_law_node_parent_id", table_name="law_node")
