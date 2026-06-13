"""索引 CSV メタ読込・revision_id 導出（DB 非依存）の単体テスト。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from laws_api_mirror.ingest.archive import read_csv_meta
from laws_api_mirror.ingest.load import _derive_from_revision_id

_HEADER = (
    "法令種別,法令番号,法令名,法令名読み,旧法令名,公布日,改正法令名,改正法令番号,"
    "改正法令公布日,施行日,施行日備考,法令ID,本文URL,未施行"
)


def test_derive_enforcement_and_amendment() -> None:
    """law_revision_id から施行日・改正法令 id を取り出す。"""
    enf, amend = _derive_from_revision_id("415AC0000000057_20260521_504AC0000000048")
    assert enf is not None and enf.isoformat() == "2026-05-21"
    assert amend == "504AC0000000048"
    # 全ゼロは改正なし
    enf2, amend2 = _derive_from_revision_id("321CONSTITUTION_19470503_000000000000000")
    assert enf2 is not None and enf2.isoformat() == "1947-05-03"
    assert amend2 is None


def test_read_csv_meta_category_and_amendment(tmp_path: Path) -> None:
    """分類別 CSV（1.csv）から category_cd と改正法令メタを取り出す。"""
    rev = "322AC0000000099_20240401_505AC0000000010"
    url = "https://laws.e-gov.go.jp/law/322AC0000000099/20240401_505AC0000000010"
    row = ",".join(
        [
            "法律",
            "法令番号",
            "テスト法",
            "てすと",
            "",
            "公布日",
            "改正法",
            "令和五年法律第十号",
            "",
            "令和六年四月一日",
            "備考あり",
            "322AC0000000099",
            url,
            "",
        ]
    )
    zip_path = tmp_path / "1_xml.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("1.csv", f"{_HEADER}\n{row}\n")
        z.writestr(f"{rev}/{rev}.xml", b"<Law/>")

    meta = read_csv_meta(zip_path)
    assert rev in meta
    m = meta[rev]
    assert m.category_cd == "1"  # 1.csv → 分類 1
    assert m.amendment_law_title == "改正法"
    assert m.amendment_law_num == "令和五年法律第十号"
    assert m.amendment_enforcement_comment == "備考あり"


def test_read_csv_meta_full_zip_no_category(tmp_path: Path) -> None:
    """全件 CSV（all_law_list.csv）は category_cd を付けない。"""
    rev = "100AC0000000001_20000101_000000000000000"
    url = "https://laws.e-gov.go.jp/law/100AC0000000001/20000101_000000000000000"
    row = f"法律,n,t,,,,,,,,,100AC0000000001,{url},"
    zip_path = tmp_path / "all_xml.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("all_law_list.csv", f"{_HEADER}\n{row}\n")

    meta = read_csv_meta(zip_path)
    assert meta[rev].category_cd is None
