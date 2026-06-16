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

import asyncio
import contextlib
import multiprocessing
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from laws_api_mirror.core.logging import get_logger
from laws_api_mirror.db.models import IngestLawEvent, IngestRun
from laws_api_mirror.db.session import build_engine, build_session_factory
from laws_api_mirror.ingest.archive import (
    LawEntryName,
    RevisionMeta,
    iter_law_names,
    iter_law_xml,
    read_csv_meta,
)
from laws_api_mirror.ingest.load import load_parsed_law
from laws_api_mirror.ingest.parse import parse_law
from laws_api_mirror.ingest.search import populate_text_search

_log = get_logger(__name__)

#: 逐次パスで進捗ログ（ingest.progress）を出す法令件数の間隔
_PROGRESS_LOG_EVERY = 100
#: 並列パスで各シャードが共有カウンタを更新する法令件数の間隔（IPC を間引く）
_SHARD_REPORT_EVERY = 20
#: 並列パスでコーディネータが集約進捗を出す秒間隔
_PROGRESS_INTERVAL_S = 15.0

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


@dataclass
class _LoadStats:
    """ロード相の集計（逐次・各シャードで共有。プロセス間で受け渡すため pickle 可能）。"""

    inserted: int = 0
    failed: int = 0
    node_count: int = 0
    text_searched: int = 0
    failures: list[tuple[str, str]] = field(default_factory=list)

    def merge(self, other: _LoadStats) -> None:
        self.inserted += other.inserted
        self.failed += other.failed
        self.node_count += other.node_count
        self.text_searched += other.text_searched
        for failure in other.failures:
            if len(self.failures) < 20:  # 代表例のみ保持（記録は ingest_law_event）
                self.failures.append(failure)


async def _load_entries(
    *,
    zip_path: Path,
    names: list[str] | None,
    csv_meta: dict[str, RevisionMeta],
    run_id: int,
    use_copy: bool,
    session_factory: Callable[[], AsyncSession] | async_sessionmaker[AsyncSession],
    on_progress: Callable[[int], None] | None = None,
) -> _LoadStats:
    """Zip の法令エントリ（``names`` 指定分、None なら全件）を 1 法令 = 1 Tx で投入する。

    ロード相のセッションでは ``synchronous_commit = off`` にする（クラッシュ時は landing
    zone から再実行可能なので許容、§13.4）。個別法令の失敗は記録して継続する（§11.12.3）。
    ``on_progress`` は法令を 1 件処理するたびに、本呼び出し内の累計処理件数で呼ばれる。
    """
    name_set = set(names) if names is not None else None
    stats = _LoadStats()
    processed = 0
    for entry in iter_law_xml(zip_path, names=name_set):
        try:
            async with session_factory() as session, session.begin():
                # ロード相は per-law fsync を避ける（§13.4）。SET LOCAL で当該 Tx に限定する。
                await session.execute(text("SET LOCAL synchronous_commit = off"))
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
            stats.inserted += 1
            stats.node_count += result.node_count
            stats.text_searched += searched
        except Exception as exc:  # 個別失敗は記録して継続（§11.12.3）
            stats.failed += 1
            message = str(exc)
            if len(stats.failures) < 20:
                stats.failures.append((entry.law_revision_id, message[:200]))
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
        processed += 1
        if on_progress is not None:
            on_progress(processed)
    return stats


def _run_shard(
    zip_path_str: str,
    names: list[str],
    csv_meta: dict[str, RevisionMeta],
    run_id: int,
    use_copy: bool,
    db_url: str,
    progress_slots: Any,
    slot_index: int,
) -> _LoadStats:
    """並列シャードのプロセス・エントリポイント（同期）。

    ``ProcessPoolExecutor`` から呼ばれる。各プロセスは独自の async エンジンを張り、
    担当分の法令だけを Zip から読んで投入する（同一テーブルへの並行 COPY、§13.2）。
    接続先 ``db_url`` は親から明示的に受け取る（spawn 起動の子は実行時の settings 変更を
    引き継がないため）。進捗は ``progress_slots[slot_index]`` に自分の処理件数を書き込み、
    集約とログ出力はコーディネータ（親）が担う（子から直接ログしない）。
    """
    # spawn 起動の子はロギング未設定なので、親と同じ設定を当てる（警告ログの体裁を揃える）。
    from laws_api_mirror.core.config import settings
    from laws_api_mirror.core.logging import configure_logging

    configure_logging(settings.log_level, json_format=settings.log_json)

    def _report(done: int) -> None:
        if done % _SHARD_REPORT_EVERY == 0:
            progress_slots[slot_index] = done

    async def _run() -> _LoadStats:
        engine = build_engine(db_url)
        factory = build_session_factory(engine)
        try:
            stats = await _load_entries(
                zip_path=Path(zip_path_str),
                names=names,
                csv_meta=csv_meta,
                run_id=run_id,
                use_copy=use_copy,
                session_factory=factory,
                on_progress=_report,
            )
            progress_slots[slot_index] = stats.inserted + stats.failed  # 端数も含む最終値
            return stats
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _assign_shards(entries: list[LawEntryName], concurrency: int) -> list[list[str]]:
    """法令エントリを ``concurrency`` 個のシャードへ分配する（同一 law_id は同一シャード）。

    同一 ``law_id`` を別プロセスが同時 UPSERT するとロック競合・デッドロックを招くため、
    law_id 単位で round-robin に割り当て、リビジョンが分散してもまとまるようにする。
    """
    shards: list[list[str]] = [[] for _ in range(concurrency)]
    law_to_shard: dict[str, int] = {}
    next_shard = 0
    for entry in entries:
        shard = law_to_shard.get(entry.law_id)
        if shard is None:
            shard = next_shard % concurrency
            law_to_shard[entry.law_id] = shard
            next_shard += 1
        shards[shard].append(entry.name)
    return shards


async def _load_parallel(
    *,
    zip_path: Path,
    entries: list[LawEntryName],
    csv_meta: dict[str, RevisionMeta],
    run_id: int,
    use_copy: bool,
    concurrency: int,
    db_url: str,
) -> _LoadStats:
    """法令を law_id 単位でシャード分割し、プロセスプールで並行投入する（§13.2 / §13.4）。"""
    active_shards = [names for names in _assign_shards(entries, concurrency) if names]
    name_to_rev = {entry.name: entry.law_revision_id for entry in entries}
    zip_path_str = str(zip_path)
    total = len(entries)
    loop = asyncio.get_running_loop()

    stats = _LoadStats()
    # 各シャードが自分のスロットに処理件数を書き込み、親が合計してログする（子はログしない）。
    with multiprocessing.Manager() as manager:
        progress_slots = manager.list([0] * len(active_shards))
        with ProcessPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for slot_index, names in enumerate(active_shards):
                # シャード担当分の meta だけを渡す（pickle サイズを抑える）
                sub_meta = {
                    name_to_rev[name]: csv_meta[name_to_rev[name]]
                    for name in names
                    if name_to_rev[name] in csv_meta
                }
                futures.append(
                    loop.run_in_executor(
                        executor,
                        _run_shard,
                        zip_path_str,
                        names,
                        sub_meta,
                        run_id,
                        use_copy,
                        db_url,
                        progress_slots,
                        slot_index,
                    )
                )
            progress_task = asyncio.create_task(_poll_progress(progress_slots, total, run_id))
            try:
                results = await asyncio.gather(*futures)
            finally:
                progress_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await progress_task
            for result in results:
                stats.merge(result)
    return stats


async def _poll_progress(progress_slots: Any, total: int, run_id: int) -> None:
    """並列投入中、各シャードの進捗を合計して定期的にログする（コーディネータ側）。"""
    while True:
        await asyncio.sleep(_PROGRESS_INTERVAL_S)
        done = sum(progress_slots)
        _log.info(
            "ingest.progress",
            extra={
                "run_id": run_id,
                "done": done,
                "total": total,
                "pct": round(100 * done / total, 1) if total else 100.0,
            },
        )


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
    session_factory: Callable[[], AsyncSession] | async_sessionmaker[AsyncSession] | None = None,
    drop_indexes: bool = True,
    kind: str = "full",
    use_copy: bool = True,
    concurrency: int = 1,
) -> BootstrapSummary:
    """一括 Zip の全法令を DB に投入する。``kind`` は ingest_run の種別（full / delta）。

    ``concurrency > 1`` で law_id 単位のシャードをプロセスプールで並行投入する（§13.2）。
    差分取り込み（件数が小さくライブ索引）は既定の逐次（``concurrency=1``）で呼ぶこと。
    並列時は各シャードが独自の DB 接続を張るため、``session_factory`` は逐次パス専用。

    ``session_factory`` 未指定時は実行時点の共有 ``SessionFactory`` を遅延束縛する
    （``db.session.configure`` による接続先差し替えを取りこぼさないため。import 順に依存しない）。
    """
    if session_factory is None:
        from laws_api_mirror.db.session import SessionFactory

        session_factory = SessionFactory
    # 並列分配の段では XML 本文を読まず、名前だけを軽量に列挙する（§13.4）。
    entries = list(iter_law_names(zip_path))
    csv_meta = read_csv_meta(zip_path)
    total = len(entries)

    async with session_factory() as session, session.begin():
        run = IngestRun(kind=kind, status="running", started_at=datetime.now(UTC))
        session.add(run)
        await session.flush()
        run_id = run.id

    _log.info(
        "ingest.run.started",
        extra={"run_id": run_id, "kind": kind, "total": total, "concurrency": concurrency},
    )

    saved_defs: dict[str, str] = {}
    if drop_indexes:
        async with session_factory() as session, session.begin():
            saved_defs = await _save_and_drop_indexes(session)

    if concurrency > 1 and total > 0:
        from laws_api_mirror.core.config import settings

        stats = await _load_parallel(
            zip_path=zip_path,
            entries=entries,
            csv_meta=csv_meta,
            run_id=run_id,
            use_copy=use_copy,
            concurrency=concurrency,
            db_url=settings.database_url,
        )
    else:

        def _report(done: int) -> None:
            if done % _PROGRESS_LOG_EVERY == 0:
                _log.info(
                    "ingest.progress",
                    extra={
                        "run_id": run_id,
                        "done": done,
                        "total": total,
                        "pct": round(100 * done / total, 1) if total else 100.0,
                    },
                )

        stats = await _load_entries(
            zip_path=zip_path,
            names=None,
            csv_meta=csv_meta,
            run_id=run_id,
            use_copy=use_copy,
            session_factory=session_factory,
            on_progress=_report,
        )

    inserted = stats.inserted
    failed = stats.failed
    node_count = stats.node_count
    text_searched = stats.text_searched
    failures = stats.failures

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
