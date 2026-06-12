"""ORM スキーマ定義のメタデータ・テスト（実 DB を必要としない）。

§4 の全テーブルが Base.metadata に登録されていること、主要な特殊カラムが
意図した型・索引で定義されていることを確認し、誤削除や定義崩れを検知する。
"""

from __future__ import annotations

import laws_api_mirror.db.models  # noqa: F401  メタデータ登録のため import
from laws_api_mirror.db.base import Base
from laws_api_mirror.db.types import LTREE

EXPECTED_TABLES = {
    # 参照（§4.1）
    "era",
    "law_num_type",
    "law_type",
    "category",
    "repeal_status",
    "current_revision_status",
    "amendment_type",
    "mission",
    "node_kind",
    # ドメイン（§4.2〜§4.9）
    "law",
    "law_revision",
    "law_revision_category",
    "amendment_law",
    "law_xml",
    "law_node",
    "attached_file",
    "ingest_run",
    "ingest_law_event",
}


def test_all_expected_tables_registered() -> None:
    """§4 の全 18 テーブルが metadata に登録されていることを確認する。"""
    assert EXPECTED_TABLES <= set(Base.metadata.tables)


def test_law_node_path_is_ltree() -> None:
    """law_node.path が ltree 型で NOT NULL であることを確認する（elm 解決、§4.7.1）。"""
    path = Base.metadata.tables["law_node"].columns["path"]
    assert isinstance(path.type, LTREE)
    assert path.nullable is False


def test_law_revision_has_exclude_constraint() -> None:
    """law_revision に有効期間の重複防止 EXCLUDE 制約があることを確認する（§4.3）。"""
    constraints = Base.metadata.tables["law_revision"].constraints
    assert any(c.name == "enforcement_period_no_overlap" for c in constraints)


def test_law_node_has_search_indexes() -> None:
    """law_node に検索系の特殊インデックスが定義されていることを確認する（§5）。"""
    index_names = {idx.name for idx in Base.metadata.tables["law_node"].indexes}
    assert {
        "ix_law_node_path_gist",
        "ix_law_node_text_search",
        "ix_law_node_text_plain_bigm",
        "ix_law_node_attrs",
    } <= index_names
