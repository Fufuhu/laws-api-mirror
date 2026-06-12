"""API 共有のデータアクセス（id 解決など）。"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import Law, LawRevision


async def resolve_law(session: AsyncSession, identifier: str) -> tuple[Law, LawRevision] | None:
    """id を law_revision_id / law_id / law_num の順で (law, revision) に解決する。"""
    by_revision = (
        await session.execute(
            select(Law, LawRevision)
            .join(LawRevision, LawRevision.law_id == Law.law_id)
            .where(LawRevision.law_revision_id == identifier)
        )
    ).first()
    if by_revision is not None:
        return by_revision[0], by_revision[1]

    latest = (
        await session.execute(
            select(Law, LawRevision)
            .join(LawRevision, LawRevision.law_id == Law.law_id)
            .where(or_(Law.law_id == identifier, Law.law_num == identifier))
            .order_by(LawRevision.law_revision_id.desc())
            .limit(1)
        )
    ).first()
    if latest is not None:
        return latest[0], latest[1]
    return None
