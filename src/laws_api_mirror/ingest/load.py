"""パース結果を DB に投入するローダ（Stage 4: Load、設計 §8 / §13）。

``parse_law`` の出力（``ParsedLaw``）を 1 法令単位で DB に投入する:

1. ``law`` を UPSERT（履歴非依存メタ）。
2. ``law_revision`` を UPSERT（XML から取れるメタのみ。category/改正/施行期間等は別途）。
3. ``law_node`` を当該リビジョン分だけ洗い替え（delete → bulk insert）。親子 ``parent_id``
   は前順リストの ``parent_index`` を、採番した id 列にマップして解決する。

冪等性: 同一 ``law_revision_id`` に対する再実行で同じ結果になる（§11.3 / §13.7）。

注: 大規模ブートストラップ向けの COPY バルク投入・二次索引の DROP→後構築（§13.4）は
全件オーケストレーション側の最適化として後段で導入する。本モジュールは 1 法令単位の
正しい投入を担う。
"""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import Law, LawNode, LawRevision, LawXml
from laws_api_mirror.ingest.parse import ParsedLaw, ParsedNode


@dataclass
class LoadResult:
    law_id: str
    law_revision_id: str
    node_count: int


def build_node_rows(
    nodes: list[ParsedNode],
    ids: list[int],
    law_revision_id: str,
) -> list[dict[str, Any]]:
    """前順ノード列を law_node の行 dict 列に変換する（DB 非依存の純粋関数）。

    ``ids`` は各ノードに採番した law_node.id（前順と同順）。``parent_index`` を
    この id 列にマップして ``parent_id`` を解決する。
    """
    if len(ids) != len(nodes):
        raise ValueError("ids とノード数が一致しません")
    return [
        {
            "id": ids[i],
            "parent_id": ids[n.parent_index] if n.parent_index is not None else None,
            "law_revision_id": law_revision_id,
            "kind": n.kind,
            "ordinal": n.ordinal,
            "depth": n.depth,
            "path": n.path,
            "path_text": n.path_text,
            "num_text": n.num_text,
            "num_int": n.num_int,
            "num_branches": n.num_branches,
            "delete_flag": n.delete_flag,
            "hide_flag": n.hide_flag,
            "old_style": n.old_style,
            "old_num": n.old_num,
            "extract_flag": n.extract_flag,
            "sentence_function": n.sentence_function,
            "sentence_indent": n.sentence_indent,
            "writing_mode": n.writing_mode,
            "suppl_type": n.suppl_type,
            "amend_law_num": n.amend_law_num,
            "fig_src": n.fig_src,
            "rowspan": n.rowspan,
            "colspan": n.colspan,
            "border_top": n.border_top,
            "border_bottom": n.border_bottom,
            "border_left": n.border_left,
            "border_right": n.border_right,
            "align": n.align,
            "valign": n.valign,
            "attrs": n.attrs,
            "raw_xml": n.raw_xml,
            "text_plain": n.text_plain,
            # text_search は取り込み後の別パスで生成（§13.6）。ここでは NULL。
        }
        for i, n in enumerate(nodes)
    ]


async def load_parsed_law(
    session: AsyncSession,
    parsed: ParsedLaw,
    *,
    law_revision_id: str,
    is_current_latest: bool | None = True,
    raw_xml: bytes | None = None,
) -> LoadResult:
    """1 法令を DB に投入する。呼び出し側がトランザクション境界を管理する。

    ``raw_xml`` を渡すと原文 XML を ``law_xml`` に gzip 保存する（/law_data の再提供用、§4.6）。
    """
    if parsed.law_id is None:
        raise ValueError("law_id が必要です（Zip のフォルダ名等から与える）")

    await _upsert_law(session, parsed)
    await _upsert_law_revision(session, parsed, law_revision_id, is_current_latest)
    if raw_xml is not None:
        await _upsert_law_xml(session, law_revision_id, raw_xml)
    count = await _replace_nodes(session, parsed, law_revision_id)
    return LoadResult(parsed.law_id, law_revision_id, count)


async def _upsert_law_xml(session: AsyncSession, law_revision_id: str, raw_xml: bytes) -> None:
    stmt = pg_insert(LawXml).values(
        law_revision_id=law_revision_id,
        xml_gz=gzip.compress(raw_xml),
        xml_sha256=hashlib.sha256(raw_xml).digest(),
        byte_size=len(raw_xml),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[LawXml.law_revision_id],
        set_={
            "xml_gz": stmt.excluded.xml_gz,
            "xml_sha256": stmt.excluded.xml_sha256,
            "byte_size": stmt.excluded.byte_size,
        },
    )
    await session.execute(stmt)


async def _upsert_law(session: AsyncSession, parsed: ParsedLaw) -> None:
    stmt = pg_insert(Law).values(
        law_id=parsed.law_id,
        law_type=parsed.law_type,
        law_num=parsed.law_num,
        law_num_era=parsed.law_num_era,
        law_num_year=parsed.law_num_year,
        law_num_type=parsed.law_type,  # XML の LawType を番号種別にも流用（同一値域）
        law_num_num=parsed.law_num_num,
        promulgation_date=parsed.promulgation_date,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Law.law_id],
        set_={
            "law_type": stmt.excluded.law_type,
            "law_num": stmt.excluded.law_num,
            "law_num_era": stmt.excluded.law_num_era,
            "law_num_year": stmt.excluded.law_num_year,
            "law_num_type": stmt.excluded.law_num_type,
            "law_num_num": stmt.excluded.law_num_num,
            "promulgation_date": stmt.excluded.promulgation_date,
            "updated_at": func.now(),
        },
    )
    await session.execute(stmt)


async def _upsert_law_revision(
    session: AsyncSession,
    parsed: ParsedLaw,
    law_revision_id: str,
    is_current_latest: bool | None,
) -> None:
    stmt = pg_insert(LawRevision).values(
        law_revision_id=law_revision_id,
        law_id=parsed.law_id,
        law_type=parsed.law_type,
        law_title=parsed.law_title or parsed.law_num or law_revision_id,
        law_title_kana=parsed.law_title_kana,
        abbrev=parsed.abbrev,
        is_current_latest=is_current_latest,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[LawRevision.law_revision_id],
        set_={
            "law_id": stmt.excluded.law_id,
            "law_type": stmt.excluded.law_type,
            "law_title": stmt.excluded.law_title,
            "law_title_kana": stmt.excluded.law_title_kana,
            "abbrev": stmt.excluded.abbrev,
            "is_current_latest": stmt.excluded.is_current_latest,
        },
    )
    await session.execute(stmt)


async def _replace_nodes(
    session: AsyncSession,
    parsed: ParsedLaw,
    law_revision_id: str,
) -> int:
    # 洗い替え（冪等性）。CASCADE で子ノードも消える。
    await session.execute(delete(LawNode).where(LawNode.law_revision_id == law_revision_id))
    nodes = parsed.nodes
    if not nodes:
        return 0

    # law_node.id を一括採番し、parent_index → 採番済み id でツリーを解決する。
    seq = await session.scalar(select(func.pg_get_serial_sequence("law_node", "id")))
    result = await session.execute(
        text("SELECT nextval(:seq ::regclass) FROM generate_series(1, :n)"),
        {"seq": seq, "n": len(nodes)},
    )
    ids = [row[0] for row in result]

    rows = build_node_rows(nodes, ids, law_revision_id)
    await session.execute(insert(LawNode), rows)
    return len(rows)
