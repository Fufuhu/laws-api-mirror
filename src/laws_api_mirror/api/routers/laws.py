"""法令一覧 API（`GET /api/2/laws`、設計 §7.2 / §7.5）。

`law_revision` を中心に絞り込み、法令ごとに代表（最新施行日）リビジョンを 1 件返す。
取り込み済みデータで埋められないメタ（category / 改正 / 施行期間 等）は null。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.pagination import compute_next_offset
from laws_api_mirror.api.schemas import LawInfo, LawListItem, LawsResponse, RevisionInfo
from laws_api_mirror.db.models import Law, LawRevision
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["laws"])


async def list_laws(
    session: AsyncSession,
    *,
    law_id: str | None,
    law_num: str | None,
    law_title: str | None,
    law_type: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list[tuple[Law, LawRevision]]]:
    """絞り込み条件に合致する法令を、代表リビジョン付きで返す。"""
    conds = []
    if law_id:
        conds.append(Law.law_id == law_id)
    if law_num:
        conds.append(Law.law_num.ilike(f"%{law_num}%"))
    if law_title:
        conds.append(LawRevision.law_title.ilike(f"%{law_title}%"))
    if law_type:
        conds.append(Law.law_type == law_type)

    # 合致する法令数（law_id でユニーク）
    count_stmt = (
        select(func.count(distinct(LawRevision.law_id)))
        .select_from(LawRevision)
        .join(Law, Law.law_id == LawRevision.law_id)
        .where(*conds)
    )
    total = await session.scalar(count_stmt) or 0

    # 法令ごとに最新の law_revision_id（施行日順）を 1 件選ぶ
    page_stmt = (
        select(Law, LawRevision)
        .join(LawRevision, LawRevision.law_id == Law.law_id)
        .where(*conds)
        .distinct(LawRevision.law_id)
        .order_by(LawRevision.law_id, LawRevision.law_revision_id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(page_stmt)
    rows = [(row[0], row[1]) for row in result]
    return total, rows


def _law_info(law: Law) -> LawInfo:
    return LawInfo(
        law_type=law.law_type,
        law_id=law.law_id,
        law_num=law.law_num,
        law_num_era=law.law_num_era,
        law_num_year=law.law_num_year,
        law_num_type=law.law_num_type,
        law_num_num=law.law_num_num,
        promulgation_date=law.promulgation_date,
    )


def _revision_info(revision: LawRevision) -> RevisionInfo:
    return RevisionInfo(
        law_revision_id=revision.law_revision_id,
        law_type=revision.law_type,
        law_title=revision.law_title,
        law_title_kana=revision.law_title_kana,
        abbrev=revision.abbrev,
    )


@router.get("/laws", response_model=LawsResponse, summary="法令一覧取得")
async def get_laws(
    law_id: str | None = Query(None, description="法令 ID（完全一致）"),
    law_num: str | None = Query(None, description="法令番号（部分一致）"),
    law_title: str | None = Query(None, description="法令名（部分一致）"),
    law_type: str | None = Query(None, description="法令種別（Constitution / Act / ...）"),
    limit: int = Query(100, ge=1, le=1000, description="取得件数"),
    offset: int = Query(0, ge=0, description="開始位置"),
    session: AsyncSession = Depends(get_session),
) -> LawsResponse:
    total, rows = await list_laws(
        session,
        law_id=law_id,
        law_num=law_num,
        law_title=law_title,
        law_type=law_type,
        limit=limit,
        offset=offset,
    )
    items = [
        LawListItem(
            law_info=_law_info(law),
            revision_info=_revision_info(revision),
            current_revision_info=_revision_info(revision),
        )
        for law, revision in rows
    ]
    return LawsResponse(
        total_count=total,
        count=len(items),
        next_offset=compute_next_offset(total, offset, limit, len(items)),
        laws=items,
    )
