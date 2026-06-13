"""DB 接続層の配線テスト（実 DB を必要としない範囲）。

実接続を伴う疎通確認（/health/db の SELECT 1）は docker-compose の PostgreSQL を
起動した統合確認で行う。本ファイルはエンジン生成・セッション払い出し・設定読込の
配線が壊れていないことのみを検証する。
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.core.config import Settings
from laws_api_mirror.db.session import build_engine, build_session_factory, get_session


def test_settings_reads_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """環境変数 DATABASE_URL が Settings.database_url に反映されることを確認する。"""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@dbhost:5433/mydb")
    assert Settings().database_url == "postgresql+asyncpg://u:p@dbhost:5433/mydb"


def test_database_url_default_uses_async_driver() -> None:
    """既定の接続 URL が asyncpg ドライバを指していることを確認する。"""
    assert Settings().database_url.startswith("postgresql+asyncpg://")


def test_build_engine_parses_url() -> None:
    """接続 URL からエンジンが生成され、URL 構成要素が解釈されることを確認する。"""
    engine = build_engine("postgresql+asyncpg://u:p@dbhost:5433/mydb")
    assert engine.url.drivername == "postgresql+asyncpg"
    assert engine.url.host == "dbhost"
    assert engine.url.database == "mydb"


async def test_get_session_yields_async_session() -> None:
    """get_session が（実接続なしに）AsyncSession を払い出し、消費後に終了することを確認する。"""
    agen = get_session()
    session = await agen.__anext__()
    assert isinstance(session, AsyncSession)
    # yield の先まで進めるとセッションの async with を抜けて正常終了する
    with pytest.raises(StopAsyncIteration):
        await agen.__anext__()


async def test_session_factory_produces_async_session() -> None:
    """セッションファクトリが AsyncSession を生成することを確認する。"""
    engine = build_engine("postgresql+asyncpg://u:p@dbhost:5433/mydb")
    factory = build_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
    await engine.dispose()
