"""ORM モデル（設計 §4 データモデル）。

``Base.metadata`` に全テーブルを登録するため、各モジュールをここで import する。
初期スキーマの作成は手書きの Alembic リビジョン（migrations/versions/）が行う（§2.6）。
"""

from laws_api_mirror.db.models.ingest import IngestLawEvent, IngestRun
from laws_api_mirror.db.models.law import (
    AmendmentLaw,
    AttachedFile,
    Law,
    LawRevision,
    LawRevisionCategory,
    LawXml,
)
from laws_api_mirror.db.models.node import LawNode, NodeKind
from laws_api_mirror.db.models.reference import (
    AmendmentType,
    Category,
    CurrentRevisionStatus,
    Era,
    LawNumType,
    LawType,
    Mission,
    RepealStatus,
)

__all__ = [
    "AmendmentLaw",
    "AmendmentType",
    "AttachedFile",
    "Category",
    "CurrentRevisionStatus",
    "Era",
    "IngestLawEvent",
    "IngestRun",
    "Law",
    "LawNode",
    "LawNumType",
    "LawRevision",
    "LawRevisionCategory",
    "LawType",
    "LawXml",
    "Mission",
    "NodeKind",
    "RepealStatus",
]
