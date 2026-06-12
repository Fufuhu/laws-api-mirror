"""キーワード検索 API（`GET /api/2/keyword`、設計 §5 / §7.1 / §7.2）。

検索式（AND / OR / NOT・括弧・ワイルドカード ``*`` ``?``・句）を解析し、pg_bigm が効く
``text_plain`` の LIKE ブール条件にコンパイルしてヒットした law_node を、法令
（リビジョン）ごとにまとめて返す（§5 / §7.1）。tsvector（``text_search``）は別経路の
索引として保持し、関連度ランキング等は後続に委ねる。
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.pagination import compute_next_offset
from laws_api_mirror.api.query import compile_condition, highlight_terms, parse_query
from laws_api_mirror.api.schemas import KeywordItem, KeywordResponse, KeywordSentence
from laws_api_mirror.db.models import Law, LawNode, LawRevision
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["keyword"])


def highlight_text(value: str, terms: list[str], tag: str) -> str:
    """ヒット箇所（肯定リテラル）をハイライトタグで囲む。"""
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    result = value
    for term in terms:
        if term and term in result:
            result = result.replace(term, f"{open_tag}{term}{close_tag}")
    return result


@router.get("/keyword", response_model=KeywordResponse, summary="キーワード検索")
async def keyword_search(
    keyword: str = Query(..., min_length=1, description="検索語句"),
    limit: int = Query(100, ge=1, le=1000, description="法令件数"),
    offset: int = Query(0, ge=0),
    sentences_limit: int | None = Query(None, ge=1, description="法令あたりの文数上限"),
    highlight_tag: str = Query("span", description="ハイライトに使うタグ名"),
    session: AsyncSession = Depends(get_session),
) -> KeywordResponse:
    node = parse_query(keyword)
    if node is None:
        return KeywordResponse(total_count=0, sentence_count=0, next_offset=None, items=[])

    terms = highlight_terms(node)
    match = and_(
        LawNode.text_plain.is_not(None),
        compile_condition(node, LawNode.text_plain),
    )

    sentence_count = (
        await session.scalar(select(func.count()).select_from(LawNode).where(match)) or 0
    )
    total_count = (
        await session.scalar(select(func.count(distinct(LawNode.law_revision_id))).where(match))
        or 0
    )

    revision_ids = list(
        await session.scalars(
            select(LawNode.law_revision_id)
            .where(match)
            .distinct()
            .order_by(LawNode.law_revision_id)
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
                    text=highlight_text(text_plain, terms, highlight_tag),
                )
            )

        for revision_id in revision_ids:
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

    return KeywordResponse(
        total_count=total_count,
        sentence_count=sentence_count,
        next_offset=compute_next_offset(total_count, offset, limit, len(items)),
        items=items,
    )
