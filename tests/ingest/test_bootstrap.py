"""ブートストラップの DB 非依存ロジック（シャード分配）の単体テスト。

実 DB への並行投入は compose / testcontainers の end-to-end で検証する。本ファイルは
law_id 単位のシャード分配が「同一 law_id を同一シャードに集約する」ことを検証する。
"""

from __future__ import annotations

from laws_api_mirror.ingest.archive import LawEntryName
from laws_api_mirror.ingest.bootstrap import _assign_shards


def _entry(law_id: str, rev_suffix: str) -> LawEntryName:
    rev = f"{law_id}_{rev_suffix}"
    return LawEntryName(law_id=law_id, law_revision_id=rev, name=f"{rev}/{rev}.xml")


def test_assign_shards_groups_same_law_id() -> None:
    """同一 law_id の複数リビジョンは必ず同一シャードに入る（並行 UPSERT 競合の回避）。"""
    entries = [
        _entry("A", "1"),
        _entry("B", "1"),
        _entry("A", "2"),  # A の 2 本目
        _entry("C", "1"),
        _entry("B", "2"),  # B の 2 本目
    ]
    shards = _assign_shards(entries, concurrency=2)

    # law_id ごとに、その全エントリ名が単一シャードに集約されていること
    name_to_shard = {name: i for i, names in enumerate(shards) for name in names}
    for law_id in ("A", "B", "C"):
        rev_names = [e.name for e in entries if e.law_id == law_id]
        assert len({name_to_shard[n] for n in rev_names}) == 1

    # 全エントリが過不足なく分配される
    assert sum(len(s) for s in shards) == len(entries)


def test_assign_shards_round_robin_distributes_law_ids() -> None:
    """law_id は round-robin で分散する（偏りなく複数シャードに割り当てる）。"""
    entries = [_entry(law_id, "1") for law_id in ("A", "B", "C", "D")]
    shards = _assign_shards(entries, concurrency=2)
    assert len(shards) == 2
    assert all(len(s) == 2 for s in shards)  # 4 law_id を 2 シャードへ均等


def test_assign_shards_handles_more_shards_than_laws() -> None:
    """law_id 数よりシャード数が多くても破綻しない（空シャードが出るだけ）。"""
    entries = [_entry("A", "1"), _entry("B", "1")]
    shards = _assign_shards(entries, concurrency=4)
    assert len(shards) == 4
    assert sum(len(s) for s in shards) == 2
