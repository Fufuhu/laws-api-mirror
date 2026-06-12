"""一括ダウンロード Zip の展開・インベントリ化（Stage 1: Unpack、設計 §12.3）。

bulkdownload の Zip 構造（実機確認、§12.2.3）:

- 先頭に分類別の索引 CSV（例 ``1.csv``）。
- 法令リビジョンごとに ``{law_revision_id}/{law_revision_id}.xml``。
  フォルダ名＝``law_revision_id``（``{law_id}_{施行日}_{改正法令id}`` 形式）。
  同一 ``law_id`` に複数リビジョンが含まれることがある。

本モジュールは Zip から法令 XML エントリを 1 件ずつ取り出すイテレータを提供する。
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ArchiveEntry:
    """Zip 内の 1 法令リビジョン。"""

    law_id: str
    law_revision_id: str
    xml: bytes


def _law_id_of(law_revision_id: str) -> str:
    """``law_revision_id`` から ``law_id``（先頭セグメント）を取り出す。"""
    return law_revision_id.split("_", 1)[0]


def iter_law_xml(zip_path: Path) -> Iterator[ArchiveEntry]:
    """一括 Zip から法令 XML エントリを順に取り出す。"""
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".xml"):
                continue
            law_revision_id = Path(name).stem
            yield ArchiveEntry(
                law_id=_law_id_of(law_revision_id),
                law_revision_id=law_revision_id,
                xml=archive.read(name),
            )


def count_law_xml(zip_path: Path) -> int:
    """Zip 内の法令 XML 件数（期待値、完全性検証用）。"""
    with zipfile.ZipFile(zip_path) as archive:
        return sum(1 for name in archive.namelist() if name.endswith(".xml"))
