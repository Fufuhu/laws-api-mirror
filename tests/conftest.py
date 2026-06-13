"""統合テスト用フィクスチャ（testcontainers + PostgreSQL）。

カスタムイメージ ``laws-api-mirror-pg:16``（pg_bigm / ltree 同梱、docker/postgres/）で
PostgreSQL コンテナを起動し、Alembic で最新スキーマを適用する。Docker やイメージが
無い環境では統合テストをスキップする（ユニットテストは Docker 無しで通る）。

設計 §2.10 / docs/guides/Testcontainersガイド.md を参照。
"""

from __future__ import annotations

import asyncio
import subprocess
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

import laws_api_mirror.db.session as db_session
from laws_api_mirror.core.config import settings

IMAGE = "laws-api-mirror-pg:16"
FIXTURE_XML = Path(__file__).parent / "fixtures" / "laws" / "322CO0000000014.xml"
FIXTURE_REVISION_ID = "322CO0000000014_19470503_000000000000000"


def _image_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", IMAGE], capture_output=True, check=False
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _wait_ready(host: str, port: int) -> None:
    import asyncpg

    async def ping() -> None:
        conn = await asyncpg.connect(
            host=host, port=port, user="test", password="test", database="test"
        )
        await conn.close()

    last_error: Exception | None = None
    for _ in range(60):
        try:
            asyncio.run(ping())
            return
        except Exception as exc:  # 起動待ち
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f"PostgreSQL が起動しませんでした: {last_error}")


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """PostgreSQL コンテナを起動し、スキーマ適用済みの接続 URL を返す。"""
    if not _image_available():
        pytest.skip(f"docker image {IMAGE} が無いため統合テストをスキップします")

    from testcontainers.core.container import DockerContainer

    container = (
        DockerContainer(IMAGE)
        .with_env("POSTGRES_USER", "test")
        .with_env("POSTGRES_PASSWORD", "test")
        .with_env("POSTGRES_DB", "test")
        .with_exposed_ports(5432)
    )
    container.start()
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(5432))
        _wait_ready(host, port)
        url = f"postgresql+asyncpg://test:test@{host}:{port}/test"

        # アプリ・Alembic 双方を当コンテナへ向ける
        settings.database_url = url
        db_session.configure(url, null_pool=True)

        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def ingested(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> str:
    """フィクスチャ法令 1 件を一括 Zip 化して投入し、その law_revision_id を返す。"""
    from laws_api_mirror.ingest.bootstrap import bootstrap_from_zip

    zip_path = tmp_path_factory.mktemp("bulk") / "fixture.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            f"{FIXTURE_REVISION_ID}/{FIXTURE_REVISION_ID}.xml", FIXTURE_XML.read_bytes()
        )

    summary = asyncio.run(bootstrap_from_zip(zip_path))
    assert summary.inserted == 1, summary.failures
    return FIXTURE_REVISION_ID
