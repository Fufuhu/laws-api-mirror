"""パース結果を DB に投入するローダ（Stage 4: Load、設計 §8 / §13）。

``parse_law`` の出力（``ParsedLaw``）を 1 法令単位で DB に投入する:

1. ``law`` を UPSERT（履歴非依存メタ）。
2. ``law_revision`` を UPSERT（XML から取れるメタのみ。category/改正/施行期間等は別途）。
3. ``law_node`` を当該リビジョン分だけ洗い替え（delete → bulk insert）。親子 ``parent_id``
   は前順リストの ``parent_index`` を、採番した id 列にマップして解決する。

冪等性: 同一 ``law_revision_id`` に対する再実行で同じ結果になる（§11.3 / §13.7）。

``law_node`` は既定で asyncpg の COPY で投入する（``use_copy=False`` で INSERT。§13.4）。
二次索引の DROP→後構築は全件オーケストレータ（bootstrap）が担う。
"""

from __future__ import annotations

import gzip
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import AmendmentLaw, Law, LawNode, LawRevision, LawXml
from laws_api_mirror.ingest.archive import RevisionMeta
from laws_api_mirror.ingest.parse import ParsedLaw, ParsedNode

#: 改正法令 id の「改正なし」を表す全ゼロ値
_NO_AMENDMENT = "000000000000000"


def _derive_from_revision_id(law_revision_id: str) -> tuple[date | None, str | None]:
    """``{law_id}_{施行日}_{改正法令id}`` から施行日と改正法令 id を取り出す。"""
    parts = law_revision_id.rsplit("_", 2)
    if len(parts) != 3:
        return None, None
    enforcement, amendment_id = parts[1], parts[2]
    try:
        enforcement_date: date | None = datetime.strptime(enforcement, "%Y%m%d").date()
    except ValueError:
        enforcement_date = None
    amendment_law_id = amendment_id if amendment_id != _NO_AMENDMENT else None
    return enforcement_date, amendment_law_id


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
    raw_xml: bytes | None = None,
    use_copy: bool = True,
    meta: RevisionMeta | None = None,
) -> LoadResult:
    """1 法令を DB に投入する。呼び出し側がトランザクション境界を管理する。

    ``raw_xml`` を渡すと原文 XML を ``law_xml`` に gzip 保存する（/law_data の再提供用、§4.6）。
    ``meta``（索引 CSV 由来）で category / 改正法令メタ等を充足する。施行日・改正法令 id は
    ``law_revision_id`` から導出する。``enforcement_period`` / ``is_current_latest`` は取り込み後の
    別パス（bootstrap）で計算する。
    """
    if parsed.law_id is None:
        raise ValueError("law_id が必要です（Zip のフォルダ名等から与える）")

    enforcement_date, amendment_law_id = _derive_from_revision_id(law_revision_id)

    await _upsert_law(session, parsed)
    if amendment_law_id is not None:
        await _upsert_amendment_law(session, amendment_law_id, meta)
    await _upsert_law_revision(
        session, parsed, law_revision_id, enforcement_date, amendment_law_id, meta
    )
    if raw_xml is not None:
        await _upsert_law_xml(session, law_revision_id, raw_xml)
    count = await _replace_nodes(session, parsed, law_revision_id, use_copy=use_copy)
    return LoadResult(parsed.law_id, law_revision_id, count)


async def _upsert_amendment_law(
    session: AsyncSession, amendment_law_id: str, meta: RevisionMeta | None
) -> None:
    """改正法令メタを amendment_law に UPSERT する（§4.5。law への厳格 FK は持たない）。"""
    stmt = pg_insert(AmendmentLaw).values(
        amendment_law_id=amendment_law_id,
        amendment_law_title=meta.amendment_law_title if meta else None,
        amendment_law_num=meta.amendment_law_num if meta else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[AmendmentLaw.amendment_law_id],
        set_={
            "amendment_law_title": stmt.excluded.amendment_law_title,
            "amendment_law_num": stmt.excluded.amendment_law_num,
            "last_seen_at": func.now(),
        },
    )
    await session.execute(stmt)


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
    enforcement_date: date | None,
    amendment_law_id: str | None,
    meta: RevisionMeta | None,
) -> None:
    original = amendment_law_id is None  # 改正法令 id が無い＝新規制定
    values = {
        "law_revision_id": law_revision_id,
        "law_id": parsed.law_id,
        "law_type": parsed.law_type,
        "law_title": parsed.law_title or parsed.law_num or law_revision_id,
        "law_title_kana": parsed.law_title_kana,
        "abbrev": parsed.abbrev,
        "category_cd": meta.category_cd if meta else None,
        "amendment_enforcement_date": enforcement_date,
        "amendment_enforcement_comment": meta.amendment_enforcement_comment if meta else None,
        "amendment_law_id": amendment_law_id,
        "amendment_type": "1" if original else "3",  # 1 新規 / 3 被改正（§4.1）
        "mission": "New" if original else "Partial",
        "current_revision_status": "UnEnforced" if (meta and meta.un_enforced) else None,
        # is_current_latest / enforcement_period は取り込み後の別パスで設定
    }
    stmt = pg_insert(LawRevision).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[LawRevision.law_revision_id],
        set_={key: stmt.excluded[key] for key in values if key != "law_revision_id"},
    )
    await session.execute(stmt)


async def _replace_nodes(
    session: AsyncSession,
    parsed: ParsedLaw,
    law_revision_id: str,
    *,
    use_copy: bool,
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
    if use_copy:
        await _copy_nodes(session, rows)
    else:
        await session.execute(insert(LawNode), rows)
    return len(rows)


async def _copy_nodes(session: AsyncSession, rows: list[dict[str, Any]]) -> None:
    """law_node を asyncpg の COPY で一括投入する（§13.4）。

    前順リストなので親が子より先に並び、自己参照 FK も満たされる。``path``(ltree) は
    接続時に登録したバイナリコーデック（db.session）で、``attrs``(jsonb) は JSON 文字列に
    直列化して、``num_branches`` は配列としてエンコードされる。
    """
    columns = list(rows[0].keys())
    # attrs(jsonb) は asyncpg 既定コーデックが JSON 文字列を期待するため直列化する
    records = [
        tuple(
            json.dumps(row[column])
            if column == "attrs" and row[column] is not None
            else row[column]
            for column in columns
        )
        for row in rows
    ]
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    asyncpg_connection = raw.driver_connection
    assert asyncpg_connection is not None
    await asyncpg_connection.copy_records_to_table("law_node", records=records, columns=columns)
