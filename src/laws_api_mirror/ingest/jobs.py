"""Procrastinate ジョブ定義（取り込みの非同期実行・日次差分、設計 §8 / §11.7）。

PostgreSQL（LISTEN/NOTIFY）をバックエンドとし、Redis は使わない。スキーマは専用の
``procrastinate`` スキーマに隔離する（Alembic で作成、§11.7.5）。コネクタはそのスキーマを
``search_path`` に含めて接続する。

タスク:

- ``ingest_archive(zip_path, kind)``: landing zone の Zip を取り込む（手動再投入・テスト用）。
- ``ingest_delta(update_date)``: 差分 Zip を取得して取り込む（手動トリガ）。
- ``daily_delta``: ``@periodic`` で日次 03:00 に前日差分を取り込む（§10-5）。

ワーカーは FastAPI とは別プロセスで起動する（``laws-ingest worker``、§11.7.5）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from procrastinate import App, PsycopgConnector

from laws_api_mirror.core.config import settings
from laws_api_mirror.core.logging import get_logger
from laws_api_mirror.ingest.bootstrap import bootstrap_from_zip
from laws_api_mirror.ingest.bulkdownload import BulkDownloadRequest, FileSection
from laws_api_mirror.ingest.downloader import BulkDownloader

_log = get_logger(__name__)

#: procrastinate スキーマを search_path に含めて接続する
_SEARCH_PATH = "procrastinate,public"


def build_connector() -> PsycopgConnector:
    return PsycopgConnector(
        conninfo=settings.procrastinate_dsn,
        kwargs={"options": f"-csearch_path={_SEARCH_PATH}"},
    )


procrastinate_app = App(connector=build_connector())


async def _run_delta(update_date: str) -> None:
    """差分 Zip を取得して取り込む（索引は保持＝差分は DROP しない）。"""
    request = BulkDownloadRequest(
        file_section=FileSection.DELTA,
        update_date=datetime.strptime(update_date, "%Y%m%d").date(),
    )
    artifact = await BulkDownloader().download(request)
    await bootstrap_from_zip(Path(artifact.landing_path), drop_indexes=False, kind="delta")


@procrastinate_app.task(queue="ingest", retry=5)
async def ingest_archive(zip_path: str, kind: str = "delta") -> None:
    """landing zone の Zip を取り込む（再投入・テスト用）。"""
    await bootstrap_from_zip(Path(zip_path), drop_indexes=False, kind=kind)


@procrastinate_app.task(queue="ingest", retry=5)
async def ingest_delta(update_date: str) -> None:
    """指定日（YYYYMMDD）の差分を取得して取り込む。"""
    await _run_delta(update_date)


@procrastinate_app.periodic(cron="0 3 * * *")
@procrastinate_app.task(queue="ingest", retry=5)
async def daily_delta(timestamp: int) -> None:
    """日次 03:00 に前日分の差分を取り込む（§10-5）。"""
    yesterday = (datetime.now(UTC).date() - timedelta(days=1)).strftime("%Y%m%d")
    _log.info("ingest.daily_delta.started", extra={"update_date": yesterday})
    await _run_delta(yesterday)
    _log.info("ingest.daily_delta.finished", extra={"update_date": yesterday})
