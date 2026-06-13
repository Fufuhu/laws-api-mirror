"""法令一覧 API（`GET /api/2/laws`、設計 §7.2 / §7.3 / §7.5）。

`law_revision` を中心に絞り込み、法令ごとに代表（最新施行日）リビジョンを 1 件返す。
``order`` による並び替えと DISTINCT ON（代表選定）を両立させるため、代表リビジョンを
サブクエリで選び、外側で並び替え・ページングする。

注: `category_cd` / `repeal_status` / `current_revision_status` / `asof`（施行期間）は、
取り込み済みデータが揃っている範囲で有効。これらは一括 Zip 索引 CSV の取り込み（後続）で
充足する。`asof` は `enforcement_period` を前提とする。
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.pagination import compute_next_offset
from laws_api_mirror.api.schemas import LawListItem, LawsResponse
from laws_api_mirror.db.models import Law, LawRevision
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["laws"])

#: order パラメータで許可するフィールド → カラム（ホワイトリスト、§7.3）
_ORDER_FIELDS = {
    "law_info.law_id": Law.law_id,
    "law_info.law_num": Law.law_num,
    "law_info.promulgation_date": Law.promulgation_date,
    "revision_info.law_revision_id": LawRevision.law_revision_id,
    "revision_info.law_title": LawRevision.law_title,
    "revision_info.amendment_enforcement_date": LawRevision.amendment_enforcement_date,
}


def parse_order(order: str | None) -> list[Any]:
    """``-law_info.promulgation_date,law_info.law_id`` 形式を ORDER BY 列に変換する。

    先頭 ``-`` で降順、``+`` または無印で昇順。未知フィールドは無視。既定は law_id 昇順。
    """
    columns: list[Any] = []
    for token in (order or "").split(","):
        token = token.strip()
        if not token:
            continue
        descending = token.startswith("-")
        name = token.lstrip("+-")
        column = _ORDER_FIELDS.get(name)
        if column is None:
            continue
        columns.append(column.desc() if descending else column.asc())
    return columns or [Law.law_id.asc()]


async def list_laws(
    session: AsyncSession,
    *,
    law_id: str | None,
    law_num: str | None,
    law_title: str | None,
    law_type: str | None,
    category_cd: str | None,
    repeal_status: str | None,
    current_revision_status: str | None,
    promulgation_date_from: date | None,
    promulgation_date_to: date | None,
    asof: date | None,
    order: str | None,
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
    if category_cd:
        conds.append(LawRevision.category_cd == category_cd)
    if repeal_status:
        conds.append(LawRevision.repeal_status == repeal_status)
    if current_revision_status:
        conds.append(LawRevision.current_revision_status == current_revision_status)
    if promulgation_date_from:
        conds.append(Law.promulgation_date >= promulgation_date_from)
    if promulgation_date_to:
        conds.append(Law.promulgation_date <= promulgation_date_to)
    if asof:
        conds.append(LawRevision.enforcement_period.op("@>")(asof))

    # 法令ごとに代表（最新施行日）リビジョンの id を 1 件選ぶ（DISTINCT ON）
    representative = (
        select(LawRevision.law_revision_id)
        .join(Law, Law.law_id == LawRevision.law_id)
        .where(*conds)
        .distinct(LawRevision.law_id)
        .order_by(LawRevision.law_id, LawRevision.law_revision_id.desc())
        .subquery()
    )
    total = await session.scalar(select(func.count()).select_from(representative)) or 0

    page_stmt = (
        select(Law, LawRevision)
        .join(LawRevision, LawRevision.law_id == Law.law_id)
        .join(representative, representative.c.law_revision_id == LawRevision.law_revision_id)
        .order_by(*parse_order(order))
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(page_stmt)
    rows = [(row[0], row[1]) for row in result]
    return total, rows


@router.get("/laws", response_model=LawsResponse, summary="法令一覧取得")
async def get_laws(
    law_id: str | None = Query(None, description="法令 ID（完全一致）"),
    law_num: str | None = Query(None, description="法令番号（部分一致）"),
    law_title: str | None = Query(None, description="法令名（部分一致）"),
    law_type: str | None = Query(None, description="法令種別（Constitution / Act / ...）"),
    category_cd: str | None = Query(None, description="事項別分類コード（1..50）"),
    repeal_status: str | None = Query(None, description="廃止状態（None / Repeal / ...）"),
    current_revision_status: str | None = Query(None, description="現行リビジョン状態"),
    promulgation_date_from: date | None = Query(None, description="公布日 下限（YYYY-MM-DD）"),
    promulgation_date_to: date | None = Query(None, description="公布日 上限（YYYY-MM-DD）"),
    asof: date | None = Query(
        None, description="時点（YYYY-MM-DD）。施行期間が当該日を含む版に限定"
    ),
    order: str | None = Query(
        None, description="並び替え（例 -law_info.promulgation_date,law_info.law_id）"
    ),
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
        category_cd=category_cd,
        repeal_status=repeal_status,
        current_revision_status=current_revision_status,
        promulgation_date_from=promulgation_date_from,
        promulgation_date_to=promulgation_date_to,
        asof=asof,
        order=order,
        limit=limit,
        offset=offset,
    )
    items = [
        LawListItem(
            law_info=build_law_info(law),
            revision_info=build_revision_info(revision),
            current_revision_info=build_revision_info(revision),
        )
        for law, revision in rows
    ]
    return LawsResponse(
        total_count=total,
        count=len(items),
        next_offset=compute_next_offset(total, offset, limit, len(items)),
        laws=items,
    )
