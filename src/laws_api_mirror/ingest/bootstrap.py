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

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laws_api_mirror.db.models import IngestLawEvent, IngestRun
from laws_api_mirror.db.session import SessionFactory
from laws_api_mirror.ingest.archive import iter_law_xml
from laws_api_mirror.ingest.load import load_parsed_law
from laws_api_mirror.ingest.parse import parse_law
from laws_api_mirror.ingest.search import populate_text_search

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


async def bootstrap_from_zip(
    zip_path: Path,
    *,
    session_factory: Callable[[], AsyncSession] | async_sessionmaker[AsyncSession] = SessionFactory,
    drop_indexes: bool = True,
    kind: str = "full",
) -> BootstrapSummary:
    """一括 Zip の全法令を DB に投入する。``kind`` は ingest_run の種別（full / delta）。"""
    entries = list(iter_law_xml(zip_path))
    total = len(entries)

    async with session_factory() as session, session.begin():
        run = IngestRun(kind=kind, status="running", started_at=datetime.now(UTC))
        session.add(run)
        await session.flush()
        run_id = run.id

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
                    is_current_latest=None,
                    raw_xml=entry.xml,
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

    return BootstrapSummary(
        ingest_run_id=run_id,
        total=total,
        inserted=inserted,
        failed=failed,
        node_count=node_count,
        failures=failures,
    )
