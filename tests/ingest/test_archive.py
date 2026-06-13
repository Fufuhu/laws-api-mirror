"""一括 Zip 展開イテレータ（Stage 1）の単体テスト。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from laws_api_mirror.ingest.archive import count_law_xml, iter_law_xml


def _make_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("1.csv", "index,data\n")  # 索引 CSV（スキップ対象）
        rev1 = "141IO0000000291_20250601_507CO0000000193"
        rev2 = "321CONSTITUTION_19470503_000000000000000"
        z.writestr(f"{rev1}/{rev1}.xml", b"<Law/>")
        z.writestr(f"{rev2}/{rev2}.xml", b"<Law/>")


def test_iter_law_xml_parses_ids(tmp_path: Path) -> None:
    """フォルダ名から law_revision_id と law_id を取り出し、CSV をスキップする。"""
    zip_path = tmp_path / "bulk.zip"
    _make_zip(zip_path)

    entries = list(iter_law_xml(zip_path))
    assert len(entries) == 2  # CSV は含まれない

    by_rev = {e.law_revision_id: e for e in entries}
    e1 = by_rev["141IO0000000291_20250601_507CO0000000193"]
    assert e1.law_id == "141IO0000000291"  # 先頭セグメント
    assert e1.xml == b"<Law/>"

    e2 = by_rev["321CONSTITUTION_19470503_000000000000000"]
    assert e2.law_id == "321CONSTITUTION"


def test_count_law_xml(tmp_path: Path) -> None:
    """XML 件数（期待値）を数える（完全性検証用）。"""
    zip_path = tmp_path / "bulk.zip"
    _make_zip(zip_path)
    assert count_law_xml(zip_path) == 2
