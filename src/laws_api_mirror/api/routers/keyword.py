"""キーワード検索 API（`GET /api/2/keyword`、設計 §5 / §7.1 / §7.2）。

検索式（AND / OR / NOT・括弧・ワイルドカード ``*`` ``?``・句）を解析し、pg_bigm が効く
``text_plain`` の LIKE ブール条件にコンパイルしてヒットした law_node を、法令
（リビジョン）ごとにまとめて返す（§5 / §7.1）。

- **ランキング（D-1）**: ヒット文数（マッチした law_node 数）の降順で法令を並べる。
  辞書順より関連度の高い法令を上位に出す。tsvector の ``ts_rank`` 合成は後続に委ねる。
- **ファセット絞り込み（D-2）**: ``law_type`` / ``category_cd`` / ``asof``（施行時点）/
  ``current``（現行最新）でヒット法令を絞り込む。
- **スニペット/ハイライト（D-3）**: ``snippet_length`` 指定でヒット周辺の窓を切り出し、
  区間マージ方式のハイライトで二重ラップを防ぐ。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.pagination import compute_next_offset
from laws_api_mirror.api.query import (
    compile_condition,
    highlight_terms,
    highlight_text,
    parse_query,
    snippet_around,
)
from laws_api_mirror.api.schemas import KeywordItem, KeywordResponse, KeywordSentence
from laws_api_mirror.api.xml import negotiate
from laws_api_mirror.db.models import Law, LawNode, LawRevision
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["keyword"])


def render_sentence(text_plain: str, terms: list[str], tag: str, snippet_length: int | None) -> str:
    """ヒット文を（必要ならスニペット化して）ハイライトする。"""
    body = snippet_around(text_plain, terms, snippet_length) if snippet_length else text_plain
    return highlight_text(body, terms, tag)


@router.get("/keyword", response_model=KeywordResponse, summary="キーワード検索")
async def keyword_search(
    keyword: str = Query(..., min_length=1, description="検索語句"),
    limit: int = Query(100, ge=1, le=1000, description="法令件数"),
    offset: int = Query(0, ge=0),
    sentences_limit: int | None = Query(None, ge=1, description="法令あたりの文数上限"),
    highlight_tag: str = Query("span", description="ハイライトに使うタグ名"),
    snippet_length: int | None = Query(
        None, ge=1, description="ヒット周辺をこの文字数で切り出す（未指定はノード全文）"
    ),
    law_type: str | None = Query(None, description="法令種別で絞り込み（Constitution / Act 等）"),
    category_cd: str | None = Query(None, description="事項別分類コードで絞り込み（1..50）"),
    asof: date | None = Query(
        None, description="時点（YYYY-MM-DD）。施行期間が当該日を含む版に限定"
    ),
    current: bool = Query(False, description="現行最新の版のみに限定"),
    response_format: str = Query("json", pattern="^(json|xml)$"),
    session: AsyncSession = Depends(get_session),
) -> KeywordResponse | Response:
    node = parse_query(keyword)
    if node is None:
        empty = KeywordResponse(total_count=0, sentence_count=0, next_offset=None, items=[])
        return negotiate(response_format, "keyword_response", empty)

    terms = highlight_terms(node)
    match = and_(
        LawNode.text_plain.is_not(None),
        compile_condition(node, LawNode.text_plain),
    )

    # ファセット条件（D-2）。ヒット法令（リビジョン）側に対して効かせる。
    rev_conds = []
    if law_type:
        rev_conds.append(LawRevision.law_type == law_type)
    if category_cd:
        rev_conds.append(LawRevision.category_cd == category_cd)
    if asof:
        rev_conds.append(LawRevision.enforcement_period.op("@>")(asof))
    if current:
        rev_conds.append(LawRevision.is_current_latest.is_(True))

    # リビジョンごとのヒット文数（ランキング・件数の基礎）。
    matched = (
        select(LawNode.law_revision_id, func.count().label("match_count"))
        .where(match)
        .group_by(LawNode.law_revision_id)
        .subquery()
    )
    qualified = select(matched.c.law_revision_id, matched.c.match_count).join(
        LawRevision, LawRevision.law_revision_id == matched.c.law_revision_id
    )
    if rev_conds:
        qualified = qualified.where(*rev_conds)
    qual = qualified.subquery()

    total_count = await session.scalar(select(func.count()).select_from(qual)) or 0
    sentence_count = (
        await session.scalar(select(func.coalesce(func.sum(qual.c.match_count), 0))) or 0
    )

    # ヒット文数の降順（同数は revision_id 昇順）で法令を並べる（D-1）。
    revision_ids = list(
        await session.scalars(
            select(qual.c.law_revision_id)
            .order_by(qual.c.match_count.desc(), qual.c.law_revision_id)
            .limit(limit)
            .offset(offset)
        )
    )

    items: list[KeywordItem] = []
    if revision_ids:
        meta_rows = (
            await session.execute(
                select(Law, LawRevision)
                .join(LawRevision, LawRevision.law_id == Law.law_id)
                .where(LawRevision.law_revision_id.in_(revision_ids))
            )
        ).all()
        meta_by_revision = {
            revision.law_revision_id: (law, revision) for law, revision in meta_rows
        }

        sentence_rows = (
            await session.execute(
                select(LawNode.law_revision_id, LawNode.path_text, LawNode.text_plain)
                .where(match, LawNode.law_revision_id.in_(revision_ids))
                .order_by(LawNode.law_revision_id, LawNode.id)
            )
        ).all()
        sentences_by_revision: dict[str, list[KeywordSentence]] = defaultdict(list)
        for revision_id, path_text, text_plain in sentence_rows:
            bucket = sentences_by_revision[revision_id]
            if sentences_limit is not None and len(bucket) >= sentences_limit:
                continue
            bucket.append(
                KeywordSentence(
                    position=path_text,
                    text=render_sentence(text_plain, terms, highlight_tag, snippet_length),
                )
            )

        for revision_id in revision_ids:  # ランキング順を保つ
            if revision_id not in meta_by_revision:
                continue
            law, revision = meta_by_revision[revision_id]
            items.append(
                KeywordItem(
                    law_info=build_law_info(law),
                    revision_info=build_revision_info(revision),
                    sentences=sentences_by_revision[revision_id],
                )
            )

    model = KeywordResponse(
        total_count=total_count,
        sentence_count=sentence_count,
        next_offset=compute_next_offset(total_count, offset, limit, len(items)),
        items=items,
    )
    return negotiate(response_format, "keyword_response", model)
