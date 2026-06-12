"""Procrastinate ジョブ（スキーマ・ワーカー実行）の統合テスト（実 PostgreSQL）。

``database_url`` フィクスチャ（conftest.py）が Alembic で procrastinate スキーマも
適用する。Docker/イメージが無い環境では自動スキップされる。
"""

from __future__ import annotations

import zipfile
from pathlib import Path

from sqlalchemy import text

# 注: SessionFactory は conftest の configure() 後にコンテナへ向くため、
# モジュール冒頭で名前束縛せず実行時に db_session 経由で参照する。
import laws_api_mirror.db.session as db_session

FIXTURE_XML = Path(__file__).parent.parent / "fixtures" / "laws" / "322CO0000000014.xml"
REVISION_ID = "322CO0000000014_19470503_000000000000000"


async def test_procrastinate_schema_applied(database_url: str) -> None:
    """Alembic で procrastinate スキーマ（ジョブテーブル）が作成されている。"""
    async with db_session.SessionFactory() as session:
        names = list(
            await session.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'procrastinate'"
                )
            )
        )
    assert "procrastinate_jobs" in names


async def test_worker_runs_ingest_job(database_url: str, tmp_path: Path) -> None:
    """ジョブを投入しワーカーで実行すると、Zip が取り込まれる。"""
    from laws_api_mirror.ingest import jobs

    zip_path = tmp_path / "delta.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(f"{REVISION_ID}/{REVISION_ID}.xml", FIXTURE_XML.read_bytes())

    # コンテナ向けのコネクタに差し替えてワーカーを実行（処理後に停止）
    with jobs.procrastinate_app.replace_connector(jobs.build_connector()):
        async with jobs.procrastinate_app.open_async():
            await jobs.ingest_archive.defer_async(zip_path=str(zip_path), kind="delta")
            await jobs.procrastinate_app.run_worker_async(
                queues=["ingest"],
                wait=False,
                install_signal_handlers=False,
                listen_notify=False,
            )

    async with db_session.SessionFactory() as session:
        count = await session.scalar(
            text("SELECT count(*) FROM law_node WHERE law_revision_id = :r"),
            {"r": REVISION_ID},
        )
        kind = await session.scalar(
            text("SELECT kind FROM ingest_run WHERE source_date IS NULL ORDER BY id DESC LIMIT 1")
        )
    assert count == 15
    assert kind == "delta"
