"""一括 Zip から全法令を投入するブートストラップ・オーケストレータ（§13.2 ロード相）。

Stage 1（展開）→ 法令ごとに parse + load → Stage I（二次索引の後構築）を実行する。

- **1 法令 = 1 トランザクション**で投入し、失敗を局所化する（§8）。個別の失敗は
  ``ingest_law_event`` に記録して継続する（警告継続、§11.12.3）。
- **二次索引の後構築**（§13.4）: ロード前に law_node の二次索引を DROP し、全件
  投入後に再作成する（空 DB へのバルク投入を高速化）。索引定義は DB から取得した
  ``pg_indexes.indexdef`` を保存・再実行するため、スキーマとの drift が起きない。
- 進捗・結果は ``ingest_run`` / ``ingest_law_event`` に記録する（§4.9 / 完全性検証）。

ジョブキュー（Procrastinate 親→子、§11.7）でのラップと COPY バルク投入は後段の
最適化として委ね、本モジュールは直接実行の正しいロード相を担う。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laws_api_mirror.core.logging import get_logger
from laws_api_mirror.db.models import IngestLawEvent, IngestRun
from laws_api_mirror.db.session import SessionFactory
from laws_api_mirror.ingest.archive import iter_law_xml, read_csv_meta
from laws_api_mirror.ingest.load import load_parsed_law
from laws_api_mirror.ingest.parse import parse_law
from laws_api_mirror.ingest.search import populate_text_search

_log = get_logger(__name__)

#: ロード前に DROP し、投入後に再作成する law_node の二次索引（§13.4）
_LAW_NODE_SECONDARY_INDEXES = [
    "ix_law_node_path_gist",
    "ix_law_node_text_search",
    "ix_law_node_text_plain_bigm",
    "ix_law_node_attrs",
    "ix_law_node_revision_parent_ordinal",
    "ix_law_node_revision_kind_num",
]


@dataclass
class BootstrapSummary:
    ingest_run_id: int
    total: int
    inserted: int
    failed: int
    node_count: int
    failures: list[tuple[str, str]] = field(default_factory=list)


async def _save_and_drop_indexes(session: AsyncSession) -> dict[str, str]:
    result = await session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE indexname = ANY(:names)"),
        {"names": _LAW_NODE_SECONDARY_INDEXES},
    )
    defs = {row.indexname: row.indexdef for row in result}
    for name in defs:
        await session.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
    return defs


async def _rebuild_indexes(session: AsyncSession, defs: dict[str, str]) -> None:
    for ddl in defs.values():
        await session.execute(text(ddl))


async def populate_enforcement_periods(
    session: AsyncSession, law_ids: list[str] | None = None
) -> None:
    """法令ごとに enforcement_period と is_current_latest を計算する（§4.3 / §A-2）。

    各リビジョンの施行期間 = [当該施行日, 次の施行日)（最新は上限なし）。
    is_current_latest = 施行期間が本日を含むリビジョン。``law_ids`` 指定でその法令だけ更新。
    """
    where = "WHERE amendment_enforcement_date IS NOT NULL"
    params: dict[str, Any] = {}
    if law_ids is not None:
        where += " AND law_id = ANY(:law_ids)"
        params["law_ids"] = law_ids

    # 更新順で一瞬区間が重なっても EXCLUDE で失敗しないよう、本 Tx 内で遅延検査にする
    await session.execute(text("SET CONSTRAINTS enforcement_period_no_overlap DEFERRED"))
    await session.execute(
        text(
            f"""
            WITH ordered AS (
                SELECT law_revision_id, amendment_enforcement_date,
                    lead(amendment_enforcement_date) OVER (
                        PARTITION BY law_id
                        ORDER BY amendment_enforcement_date, law_revision_id
                    ) AS next_date
                FROM law_revision
                {where}
            )
            UPDATE law_revision lr SET
                enforcement_period = daterange(o.amendment_enforcement_date, o.next_date, '[)'),
                is_current_latest = (
                    o.amendment_enforcement_date <= CURRENT_DATE
                    AND (o.next_date IS NULL OR o.next_date > CURRENT_DATE)
                )
            FROM ordered o
            WHERE lr.law_revision_id = o.law_revision_id
            """
        ),
        params,
    )


async def bootstrap_from_zip(
    zip_path: Path,
    *,
    session_factory: Callable[[], AsyncSession] | async_sessionmaker[AsyncSession] = SessionFactory,
    drop_indexes: bool = True,
    kind: str = "full",
    use_copy: bool = True,
) -> BootstrapSummary:
    """一括 Zip の全法令を DB に投入する。``kind`` は ingest_run の種別（full / delta）。"""
    entries = list(iter_law_xml(zip_path))
    csv_meta = read_csv_meta(zip_path)
    total = len(entries)

    async with session_factory() as session, session.begin():
        run = IngestRun(kind=kind, status="running", started_at=datetime.now(UTC))
        session.add(run)
        await session.flush()
        run_id = run.id

    _log.info("ingest.run.started", extra={"run_id": run_id, "kind": kind, "total": total})

    saved_defs: dict[str, str] = {}
    if drop_indexes:
        async with session_factory() as session, session.begin():
            saved_defs = await _save_and_drop_indexes(session)

    inserted = 0
    failed = 0
    node_count = 0
    text_searched = 0
    failures: list[tuple[str, str]] = []

    for entry in entries:
        try:
            async with session_factory() as session, session.begin():
                parsed = parse_law(entry.xml, law_id=entry.law_id)
                result = await load_parsed_law(
                    session,
                    parsed,
                    law_revision_id=entry.law_revision_id,
                    raw_xml=entry.xml,
                    use_copy=use_copy,
                    meta=csv_meta.get(entry.law_revision_id),
                )
                # Stage I 前半: text_search を法令単位で生成（§13.6。GIN 再構築の前）。
                searched = await populate_text_search(
                    session, law_revision_id=entry.law_revision_id
                )
                session.add(
                    IngestLawEvent(
                        ingest_run_id=run_id,
                        law_revision_id=entry.law_revision_id,
                        action="inserted",
                    )
                )
            inserted += 1
            node_count += result.node_count
            text_searched += searched
        except Exception as exc:  # 個別失敗は記録して継続（§11.12.3）
            failed += 1
            message = str(exc)
            if len(failures) < 20:
                failures.append((entry.law_revision_id, message[:200]))
            _log.warning(
                "ingest.law.failed",
                extra={
                    "run_id": run_id,
                    "law_revision_id": entry.law_revision_id,
                    "error": message[:200],
                },
            )
            async with session_factory() as session, session.begin():
                session.add(
                    IngestLawEvent(
                        ingest_run_id=run_id,
                        law_revision_id=entry.law_revision_id,
                        action="failed",
                        error=message[:1000],
                    )
                )

    if drop_indexes and saved_defs:
        async with session_factory() as session, session.begin():
            await _rebuild_indexes(session, saved_defs)

    # 投入した法令の施行期間 / current 判定を計算（§4.3 / §A-2）
    affected_law_ids = sorted({entry.law_id for entry in entries})
    if affected_law_ids:
        async with session_factory() as session, session.begin():
            await populate_enforcement_periods(session, affected_law_ids)

    async with session_factory() as session, session.begin():
        run = await session.get(IngestRun, run_id)  # type: ignore[assignment]
        if run is not None:
            run.status = "success" if failed == 0 else "completed_with_errors"
            run.finished_at = datetime.now(UTC)
            run.stats = {
                "total": total,
                "inserted": inserted,
                "failed": failed,
                "node_count": node_count,
                "text_searched": text_searched,
            }

    _log.info(
        "ingest.run.finished",
        extra={
            "run_id": run_id,
            "kind": kind,
            "total": total,
            "inserted": inserted,
            "failed": failed,
            "node_count": node_count,
            "text_searched": text_searched,
        },
    )

    return BootstrapSummary(
        ingest_run_id=run_id,
        total=total,
        inserted=inserted,
        failed=failed,
        node_count=node_count,
        failures=failures,
    )
