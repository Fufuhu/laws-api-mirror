"""一括ダウンロード Zip の展開・インベントリ化（Stage 1: Unpack、設計 §12.3）。

bulkdownload の Zip 構造（実機確認、§12.2.3）:

- 先頭に分類別の索引 CSV（例 ``1.csv``）。
- 法令リビジョンごとに ``{law_revision_id}/{law_revision_id}.xml``。
  フォルダ名＝``law_revision_id``（``{law_id}_{施行日}_{改正法令id}`` 形式）。
  同一 ``law_id`` に複数リビジョンが含まれることがある。

本モジュールは Zip から法令 XML エントリを 1 件ずつ取り出すイテレータを提供する。
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

#: 分類別 CSV のファイル名（例 1.csv）→ category_cd を取り出す
_CATEGORY_CSV = re.compile(r"^(\d+)\.csv$")


@dataclass
class ArchiveEntry:
    """Zip 内の 1 法令リビジョン。"""

    law_id: str
    law_revision_id: str
    xml: bytes


@dataclass
class RevisionMeta:
    """索引 CSV 由来の法令リビジョン・メタ（§A-1）。"""

    category_cd: str | None = None
    amendment_law_title: str | None = None
    amendment_law_num: str | None = None
    amendment_enforcement_comment: str | None = None
    un_enforced: bool = False


def _law_id_of(law_revision_id: str) -> str:
    """``law_revision_id`` から ``law_id``（先頭セグメント）を取り出す。"""
    return law_revision_id.split("_", 1)[0]


def _revision_id_from_url(url: str) -> str | None:
    """本文 URL（``.../law/{law_id}/{施行日}_{改正法令id}``）から law_revision_id を作る。"""
    parts = url.rstrip("/").split("/")
    if len(parts) < 2:
        return None
    return f"{parts[-2]}_{parts[-1]}"


def read_csv_meta(zip_path: Path) -> dict[str, RevisionMeta]:
    """Zip 内の索引 CSV を読み、law_revision_id → メタの辞書を返す。

    分類別 Zip（``{N}.csv``）はファイル名から category_cd を得る。全件 Zip
    （``all_law_list.csv``）は分類列が無いため category_cd は付かない。
    """
    result: dict[str, RevisionMeta] = {}
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():
            if not name.endswith(".csv"):
                continue
            match = _CATEGORY_CSV.match(Path(name).name)
            category_cd = match.group(1) if match else None
            text = archive.read(name).decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(text)))
            if not rows:
                continue
            index = {header: i for i, header in enumerate(rows[0])}
            for row in rows[1:]:
                revision_id = _revision_id_from_url(row[index["本文URL"]])
                if revision_id is None:
                    continue
                result[revision_id] = RevisionMeta(
                    category_cd=category_cd,
                    amendment_law_title=row[index["改正法令名"]] or None,
                    amendment_law_num=row[index["改正法令番号"]] or None,
                    amendment_enforcement_comment=row[index["施行日備考"]] or None,
                    un_enforced=bool(row[index["未施行"]].strip()),
                )
    return result


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
