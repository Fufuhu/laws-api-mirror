"""キーワード検索 API（`GET /api/2/keyword`、設計 §5 / §7.2）。

pg_bigm（``text_plain`` の部分一致）と tsvector（``text_search`` の形態素一致）の
**ハイブリッド**でヒットした law_node を、法令（リビジョン）ごとにまとめて返す。

1st リリースはキーワードを 1 つの語句として扱う。検索式（ワイルドカード・AND/OR/NOT、
§7.1）の解析と関連度ランキングは後続に委ねる。
"""

from __future__ import annotations

from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.pagination import compute_next_offset
from laws_api_mirror.api.schemas import KeywordItem, KeywordResponse, KeywordSentence
from laws_api_mirror.db.models import Law, LawNode, LawRevision
from laws_api_mirror.db.session import get_session
from laws_api_mirror.ingest.search import tokenize

router = APIRouter(prefix="/api/2", tags=["keyword"])


def highlight_text(value: str, keyword: str, tokens: list[str], tag: str) -> str:
    """ヒット箇所をハイライトタグで囲む。

    語句が部分一致するならその語句を、しないなら各形態素トークンを囲む。
    """
    open_tag, close_tag = f"<{tag}>", f"</{tag}>"
    if keyword and keyword in value:
        return value.replace(keyword, f"{open_tag}{keyword}{close_tag}")
    result = value
    for token in tokens:
        if token and token in result:
            result = result.replace(token, f"{open_tag}{token}{close_tag}")
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
    tokens = [t for t in tokenize(keyword).split(" ") if t]

    # ハイブリッド一致条件: bigm 部分一致 OR tsvector 形態素一致
    clauses = [LawNode.text_plain.like(f"%{keyword}%")]
    if tokens:
        tsquery = func.to_tsquery("simple", " & ".join(tokens))
        clauses.append(LawNode.text_search.op("@@")(tsquery))
    match = and_(LawNode.text_plain.is_not(None), or_(*clauses))

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
                    text=highlight_text(text_plain, keyword, tokens, highlight_tag),
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
