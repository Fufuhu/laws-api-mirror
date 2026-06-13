"""法令履歴一覧 API（`GET /api/2/law_revisions/{id}`、設計 §7.2）。

法令（law_id または law_num）を解決し、その全リビジョンを履歴として返す。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.schemas import LawRevisionsResponse
from laws_api_mirror.api.xml import negotiate
from laws_api_mirror.db.models import Law, LawRevision
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["law_revisions"])


@router.get(
    "/law_revisions/{law_id_or_num}",
    response_model=LawRevisionsResponse,
    summary="法令履歴一覧取得",
)
async def get_law_revisions(
    law_id_or_num: str,
    response_format: str = Query("json", pattern="^(json|xml)$"),
    session: AsyncSession = Depends(get_session),
) -> LawRevisionsResponse | Response:
    law = await session.scalar(
        select(Law).where(or_(Law.law_id == law_id_or_num, Law.law_num == law_id_or_num))
    )
    if law is None:
        raise HTTPException(status_code=404, detail="法令が見つかりません")

    revisions = list(
        await session.scalars(
            select(LawRevision)
            .where(LawRevision.law_id == law.law_id)
            .order_by(LawRevision.law_revision_id)
        )
    )
    model = LawRevisionsResponse(
        law_info=build_law_info(law),
        revisions=[build_revision_info(r) for r in revisions],
    )
    return negotiate(response_format, "law_revisions_response", model)
