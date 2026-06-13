"""API 共有のデータアクセス（id 解決など）。"""

from __future__ import annotations

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import Law, LawRevision


async def resolve_law(
    session: AsyncSession, identifier: str, *, asof: date | None = None
) -> tuple[Law, LawRevision] | None:
    """id を law_revision_id / law_id / law_num の順で (law, revision) に解決する。

    ``asof`` を指定し、id が law_id / law_num の場合は、施行期間が当該日を含む版を選ぶ
    （無ければ該当なし）。リビジョン ID 直接指定時は ``asof`` を無視する。
    """
    by_revision = (
        await session.execute(
            select(Law, LawRevision)
            .join(LawRevision, LawRevision.law_id == Law.law_id)
            .where(LawRevision.law_revision_id == identifier)
        )
    ).first()
    if by_revision is not None:
        return by_revision[0], by_revision[1]

    stmt = (
        select(Law, LawRevision)
        .join(LawRevision, LawRevision.law_id == Law.law_id)
        .where(or_(Law.law_id == identifier, Law.law_num == identifier))
    )
    if asof is not None:
        stmt = stmt.where(LawRevision.enforcement_period.op("@>")(asof))
    stmt = stmt.order_by(LawRevision.law_revision_id.desc()).limit(1)

    picked = (await session.execute(stmt)).first()
    if picked is not None:
        return picked[0], picked[1]
    return None
