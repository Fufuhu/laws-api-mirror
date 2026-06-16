"""法令本文の構造ノード（設計 §4.7）。

法令 XML の全要素を単一テーブル ``law_node`` にツリー格納する。要素種別は lookup
テーブル ``node_kind`` に切り出し、XSD バージョンアップに耐える設計（§4.7 / §11.12）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from laws_api_mirror.db.base import Base
from laws_api_mirror.db.types import LTREE


class NodeKind(Base):
    """XSD の要素種別（参照テーブル、§4.7）。"""

    __tablename__ = "node_kind"

    kind: Mapped[str] = mapped_column(Text, primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    is_container: Mapped[bool] = mapped_column(Boolean, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class LawNode(Base):
    """法令本文の構造ノード（隣接リスト + materialized path、§4.7）。"""

    __tablename__ = "law_node"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    law_revision_id: Mapped[str] = mapped_column(
        ForeignKey("law_revision.law_revision_id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("law_node.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(ForeignKey("node_kind.kind"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)  # 同一親内 0 始まり順序

    # 番号（Num 属性）
    num_text: Mapped[str | None] = mapped_column(Text)  # 原文（"21", "21_2" など）
    num_int: Mapped[int | None] = mapped_column(Integer)  # 主要番号（"21_2"→21）
    num_branches: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))  # {21,2}

    # タイトル・キャプション
    caption: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)

    # 構造系の属性（XSD 由来）
    delete_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    hide_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    old_style: Mapped[bool | None] = mapped_column(Boolean)
    old_num: Mapped[bool | None] = mapped_column(Boolean)
    extract_flag: Mapped[bool | None] = mapped_column(Boolean)

    # Sentence 専用
    sentence_function: Mapped[str | None] = mapped_column(Text)  # main | proviso
    sentence_indent: Mapped[str | None] = mapped_column(Text)
    writing_mode: Mapped[str | None] = mapped_column(Text)  # vertical | horizontal

    # SupplProvision 専用
    suppl_type: Mapped[str | None] = mapped_column(Text)  # New | Amend
    amend_law_num: Mapped[str | None] = mapped_column(Text)

    # Fig 専用
    fig_src: Mapped[str | None] = mapped_column(Text)

    # TableColumn 専用（疎なカラム）
    rowspan: Mapped[int | None] = mapped_column(Integer)
    colspan: Mapped[int | None] = mapped_column(Integer)
    border_top: Mapped[str | None] = mapped_column(Text)
    border_bottom: Mapped[str | None] = mapped_column(Text)
    border_left: Mapped[str | None] = mapped_column(Text)
    border_right: Mapped[str | None] = mapped_column(Text)
    align: Mapped[str | None] = mapped_column(Text)
    valign: Mapped[str | None] = mapped_column(Text)

    # レア属性 / インライン要素の格納
    attrs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    # 中身（葉ノードの XML 断片）
    #: Sentence の混在内容や QuoteStruct の任意 XML を原文保持（XML 型は断片を弾くため Text）
    raw_xml: Mapped[str | None] = mapped_column(Text)
    text_plain: Mapped[str | None] = mapped_column(Text)  # 検索・ハイライト用プレーンテキスト

    # パス（elm 解決用、§4.7.1）
    path: Mapped[str] = mapped_column(LTREE, nullable=False)
    path_text: Mapped[str] = mapped_column(Text, nullable=False)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Law

    # 検索（§5）。text_search は取り込み時に書き込む（STORED にしない、§11.1）
    text_search: Mapped[str | None] = mapped_column(TSVECTOR)

    __table_args__ = (
        UniqueConstraint("law_revision_id", "path", name="uq_law_node_revision_path"),
        Index("ix_law_node_path_gist", "path", postgresql_using="gist"),
        Index("ix_law_node_revision_parent_ordinal", "law_revision_id", "parent_id", "ordinal"),
        # 自己参照 FK (parent_id → law_node.id, ON DELETE CASCADE) のカスケード検査用。
        # 索引が無いと法令の洗い替え DELETE が削除行ごとに全表スキャンになる（§13.4 の
        # bootstrap 索引 DROP 対象には含めない）。
        Index("ix_law_node_parent_id", "parent_id"),
        Index("ix_law_node_revision_kind_num", "law_revision_id", "kind", "num_int"),
        Index("ix_law_node_text_search", "text_search", postgresql_using="gin"),
        Index(
            "ix_law_node_text_plain_bigm",
            "text_plain",
            postgresql_using="gin",
            postgresql_ops={"text_plain": "gin_bigm_ops"},
        ),
        Index(
            "ix_law_node_attrs",
            "attrs",
            postgresql_using="gin",
            postgresql_ops={"attrs": "jsonb_path_ops"},
        ),
    )
