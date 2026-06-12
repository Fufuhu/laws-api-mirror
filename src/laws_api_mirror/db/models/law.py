"""法令メタ・履歴・改正法令・生 XML・添付（設計 §4.2〜§4.6, §4.8）。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import BYTEA, DATERANGE, ExcludeConstraint, Range
from sqlalchemy.orm import Mapped, mapped_column

from laws_api_mirror.db.base import Base


class Law(Base):
    """法令メタ（履歴非依存、§4.2）。"""

    __tablename__ = "law"

    law_id: Mapped[str] = mapped_column(Text, primary_key=True)  # 例: 322CO0000000016
    law_type: Mapped[str | None] = mapped_column(ForeignKey("law_type.code"))
    law_num: Mapped[str] = mapped_column(Text, nullable=False)  # 例: 昭和二十二年政令第十六号
    law_num_era: Mapped[str | None] = mapped_column(ForeignKey("era.code"))
    law_num_year: Mapped[int | None] = mapped_column(SmallInteger)
    law_num_type: Mapped[str | None] = mapped_column(ForeignKey("law_num_type.code"))
    law_num_num: Mapped[str | None] = mapped_column(Text)
    promulgation_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("law_num", name="uq_law_law_num"),
        Index(
            "ix_law_num_components",
            "law_num_era",
            "law_num_year",
            "law_num_type",
            "law_num_num",
        ),
        Index("ix_law_promulgation_date", "promulgation_date"),
    )


class AmendmentLaw(Base):
    """改正法令メタ（§4.5）。``law`` への厳格 FK は持たず Lazy Linking。"""

    __tablename__ = "amendment_law"

    amendment_law_id: Mapped[str] = mapped_column(Text, primary_key=True)
    amendment_law_title: Mapped[str | None] = mapped_column(Text)
    amendment_law_title_kana: Mapped[str | None] = mapped_column(Text)
    amendment_law_num: Mapped[str | None] = mapped_column(Text)
    amendment_promulgate_date: Mapped[date | None] = mapped_column(Date)
    linked_law_id: Mapped[str | None] = mapped_column(ForeignKey("law.law_id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index("ix_amendment_law_linked_law_id", "linked_law_id"),
        Index("ix_amendment_law_promulgate_date", "amendment_promulgate_date"),
    )


class LawRevision(Base):
    """法令履歴（時点依存メタ、§4.3）。"""

    __tablename__ = "law_revision"

    law_revision_id: Mapped[str] = mapped_column(Text, primary_key=True)
    law_id: Mapped[str] = mapped_column(ForeignKey("law.law_id"), nullable=False)
    law_type: Mapped[str | None] = mapped_column(ForeignKey("law_type.code"))
    law_title: Mapped[str] = mapped_column(Text, nullable=False)
    law_title_kana: Mapped[str | None] = mapped_column(Text)
    abbrev: Mapped[str | None] = mapped_column(Text)
    category_cd: Mapped[str | None] = mapped_column(ForeignKey("category.code"))
    updated_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    amendment_enforcement_date: Mapped[date | None] = mapped_column(Date)
    amendment_enforcement_comment: Mapped[str | None] = mapped_column(Text)
    amendment_scheduled_enforcement_date: Mapped[date | None] = mapped_column(Date)
    amendment_law_id: Mapped[str | None] = mapped_column(
        ForeignKey("amendment_law.amendment_law_id")
    )
    amendment_type: Mapped[str | None] = mapped_column(ForeignKey("amendment_type.code"))
    repeal_status: Mapped[str | None] = mapped_column(ForeignKey("repeal_status.code"))
    repeal_date: Mapped[date | None] = mapped_column(Date)
    remain_in_force: Mapped[bool | None] = mapped_column(Boolean)
    mission: Mapped[str | None] = mapped_column(ForeignKey("mission.code"))
    current_revision_status: Mapped[str | None] = mapped_column(
        ForeignKey("current_revision_status.code")
    )
    is_current_latest: Mapped[bool | None] = mapped_column(Boolean)
    enforcement_period: Mapped[Range[date] | None] = mapped_column(DATERANGE)

    __table_args__ = (
        # 同一法令の有効期間が重ならないことを保証（§4.3）。gist の等値比較に btree_gist が必要。
        ExcludeConstraint(
            ("law_id", "="),
            ("enforcement_period", "&&"),
            using="gist",
            name="enforcement_period_no_overlap",
            deferrable=True,
        ),
        Index(
            "ix_law_revision_law_id_enforcement",
            "law_id",
            "amendment_enforcement_date",
        ),
        Index("ix_law_revision_current_status", "current_revision_status"),
    )


class LawRevisionCategory(Base):
    """法令履歴 ⇄ 分類の多対多（§4.4）。"""

    __tablename__ = "law_revision_category"

    law_revision_id: Mapped[str] = mapped_column(
        ForeignKey("law_revision.law_revision_id", ondelete="CASCADE"), primary_key=True
    )
    category_cd: Mapped[str] = mapped_column(ForeignKey("category.code"), primary_key=True)


class LawXml(Base):
    """法令本文の生 XML（gzip 圧縮、リビジョン単位、§4.6）。"""

    __tablename__ = "law_xml"

    law_revision_id: Mapped[str] = mapped_column(
        ForeignKey("law_revision.law_revision_id", ondelete="CASCADE"), primary_key=True
    )
    xml_gz: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    xml_sha256: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    byte_size: Mapped[int | None] = mapped_column(Integer)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: 検証に成功した XSD バージョン（§11.12.5。過渡期の両バージョン対応）
    xsd_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="v3.0")


class AttachedFile(Base):
    """添付ファイルのメタ（本体はオブジェクトストレージ、§4.8 / §11.2）。"""

    __tablename__ = "attached_file"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    law_revision_id: Mapped[str] = mapped_column(
        ForeignKey("law_revision.law_revision_id", ondelete="CASCADE"), nullable=False
    )
    src: Mapped[str] = mapped_column(Text, nullable=False)  # 例: ./pict/M06SE065-001.jpg
    content_type: Mapped[str | None] = mapped_column(Text)
    byte_size: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[bytes] = mapped_column(BYTEA, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("law_revision_id", "src", name="uq_attached_file_revision_src"),
        Index("ix_attached_file_sha256", "sha256"),
    )
