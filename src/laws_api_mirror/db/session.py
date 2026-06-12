"""非同期エンジンとセッションの配線。

``settings.database_url``（環境変数 ``DATABASE_URL`` で上書き可）から
SQLAlchemy の async エンジンとセッションファクトリを構築する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from laws_api_mirror.core.config import settings as default_settings


def build_engine(url: str) -> AsyncEngine:
    """接続 URL から async エンジンを生成する。

    ``pool_pre_ping=True`` でプール内のデッドコネクションを使う前に検査する。
    エンジン生成時点では接続は張られない（遅延接続）。
    """
    return create_async_engine(url, pool_pre_ping=True)


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """エンジンからセッションファクトリを生成する。"""
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_default() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = build_engine(default_settings.database_url)
    return engine, build_session_factory(engine)


#: アプリ全体で共有する既定エンジンとセッションファクトリ
engine, SessionFactory = _make_default()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI 依存性注入用。リクエストごとにセッションを払い出す。"""
    async with SessionFactory() as session:
        yield session


async def check_connection(session: AsyncSession) -> bool:
    """``SELECT 1`` で実接続を確認する（ヘルスチェック・疎通確認用）。"""
    result = await session.execute(text("SELECT 1"))
    return bool(result.scalar_one() == 1)


async def dispose_engine() -> None:
    """エンジンとコネクションプールを破棄する（アプリ終了時）。"""
    await engine.dispose()
