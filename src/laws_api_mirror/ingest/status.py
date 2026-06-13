"""取り込み状態の集約（運用監視用、C-1 / C-3）。

``ingest_run`` / ``ingest_law_event`` を集約し、最終取り込み・最終成功・直近の失敗を
1 つの状態オブジェクトにまとめる。ワーカー（Procrastinate）が別プロセスのため、API 側は
これらのテーブルを通じて取り込みの健全性を観測する。

判定（``status``）:

- ``never``  : 取り込み実行が 1 件も無い。
- ``running``: 直近の実行がまだ走っている。
- ``failed`` : 直近の実行が失敗で終わっている。
- ``stale``  : 最後の成功が鮮度ウィンドウ（既定 48h）より古い（日次差分が止まっている疑い）。
- ``ok``     : 鮮度ウィンドウ内に成功した実行がある。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.db.models import IngestLawEvent, IngestRun

#: 最後の成功からこの時間を超えると ``stale`` とみなす既定値（日次差分は 03:00 実行）
DEFAULT_FRESHNESS_HOURS = 48


@dataclass(frozen=True)
class RunInfo:
    id: int
    kind: str | None
    status: str | None
    started_at: datetime | None
    finished_at: datetime | None
    stats: dict[str, object] | None


@dataclass(frozen=True)
class IngestStatus:
    status: str
    total_runs: int
    last_run: RunInfo | None
    last_success_at: datetime | None
    recent_failures: int
    failed_samples: list[str]


async def collect_ingest_status(
    session: AsyncSession,
    *,
    now: datetime,
    freshness_hours: int = DEFAULT_FRESHNESS_HOURS,
    sample_limit: int = 10,
) -> IngestStatus:
    """取り込み状態を集約する。``now`` は鮮度判定の基準時刻（tz-aware）。"""
    total_runs = await session.scalar(select(func.count()).select_from(IngestRun)) or 0

    last_run_row = (
        await session.execute(
            select(IngestRun).order_by(desc(IngestRun.started_at), desc(IngestRun.id)).limit(1)
        )
    ).scalar_one_or_none()

    last_success_at = await session.scalar(
        select(func.max(IngestRun.finished_at)).where(IngestRun.status == "success")
    )

    last_run = (
        RunInfo(
            id=last_run_row.id,
            kind=last_run_row.kind,
            status=last_run_row.status,
            started_at=last_run_row.started_at,
            finished_at=last_run_row.finished_at,
            stats=last_run_row.stats,
        )
        if last_run_row is not None
        else None
    )

    # 直近の実行に紐づく失敗イベント（件数とサンプル）
    recent_failures = 0
    failed_samples: list[str] = []
    if last_run is not None:
        recent_failures = (
            await session.scalar(
                select(func.count())
                .select_from(IngestLawEvent)
                .where(
                    IngestLawEvent.ingest_run_id == last_run.id,
                    IngestLawEvent.action == "failed",
                )
            )
            or 0
        )
        failed_samples = list(
            await session.scalars(
                select(IngestLawEvent.law_revision_id)
                .where(
                    IngestLawEvent.ingest_run_id == last_run.id,
                    IngestLawEvent.action == "failed",
                )
                .order_by(IngestLawEvent.id)
                .limit(sample_limit)
            )
        )

    status = _judge(last_run, last_success_at, now=now, freshness_hours=freshness_hours)
    return IngestStatus(
        status=status,
        total_runs=total_runs,
        last_run=last_run,
        last_success_at=last_success_at,
        recent_failures=recent_failures,
        failed_samples=failed_samples,
    )


def _judge(
    last_run: RunInfo | None,
    last_success_at: datetime | None,
    *,
    now: datetime,
    freshness_hours: int,
) -> str:
    if last_run is None:
        return "never"
    if last_run.status == "running":
        return "running"
    if last_success_at is None:
        return "failed"
    if now - last_success_at > timedelta(hours=freshness_hours):
        return "stale"
    if last_run.status not in {"success", "completed_with_errors"}:
        return "failed"
    return "ok"
