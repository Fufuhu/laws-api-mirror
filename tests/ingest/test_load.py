"""ローダの DB 非依存ロジック（行構築・parent_id 解決）の単体テスト。

実 DB への投入（UPSERT / COPY / ltree 検索）は compose の PostgreSQL に対する
end-to-end 確認で検証する。本ファイルは parent_index → parent_id のマッピングと
列の写しが正しいことを実 DB なしで検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from laws_api_mirror.ingest.load import build_node_rows
from laws_api_mirror.ingest.parse import parse_law

FIXTURE = Path(__file__).parent.parent / "fixtures" / "laws" / "322CO0000000014.xml"


def test_build_node_rows_resolves_parent_id() -> None:
    """parent_index が、採番した id 列にマップされて parent_id になることを確認する。"""
    law = parse_law(FIXTURE.read_bytes())
    # 採番を模した連番 id（前順と同順）
    ids = [1000 + i for i in range(len(law.nodes))]
    rows = build_node_rows(law.nodes, ids, "rev1")

    assert len(rows) == len(law.nodes)
    # 根ノードの parent_id は None、それ以外は親の採番 id
    for i, (node, row) in enumerate(zip(law.nodes, rows, strict=True)):
        assert row["id"] == ids[i]
        assert row["law_revision_id"] == "rev1"
        if node.parent_index is None:
            assert row["parent_id"] is None
        else:
            assert row["parent_id"] == ids[node.parent_index]

    # Sentence ノードの親は ParagraphSentence（id 経由で辿れる）
    by_id = {r["id"]: r for r in rows}
    sentence = next(r for r in rows if r["kind"] == "Sentence")
    assert by_id[sentence["parent_id"]]["kind"] == "ParagraphSentence"


def test_build_node_rows_copies_columns() -> None:
    """主要カラム（path/num/text_plain/フラグ）が行に写されることを確認する。"""
    law = parse_law(FIXTURE.read_bytes())
    ids = list(range(len(law.nodes)))
    rows = build_node_rows(law.nodes, ids, "rev1")

    para = next(r for r in rows if r["path"] == "MainProvision.Paragraph_1")
    assert para["num_int"] == 1
    assert para["old_num"] is True
    assert para["hide_flag"] is False

    sentence = next(
        r for r in rows if r["kind"] == "Sentence" and "勅令" in (r["text_plain"] or "")
    )
    assert sentence["path_text"].startswith("MainProvision-Paragraph_1")
    assert sentence["writing_mode"] == "vertical"


def test_build_node_rows_length_mismatch() -> None:
    """ids とノード数が不一致なら ValueError になることを確認する。"""
    law = parse_law(FIXTURE.read_bytes())
    with pytest.raises(ValueError, match="一致しません"):
        build_node_rows(law.nodes, [1, 2, 3], "rev1")
