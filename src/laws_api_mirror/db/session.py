"""非同期エンジンとセッションの配線。

``settings.database_url``（環境変数 ``DATABASE_URL`` で上書き可）から
SQLAlchemy の async エンジンとセッションファクトリを構築する。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import NullPool, event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from laws_api_mirror.core.config import settings as default_settings


def _ltree_encode(value: str) -> bytes:
    # ltree のバイナリ形式: 1 バイトのバージョン(=1) + パス文字列（UTF-8）
    return b"\x01" + value.encode("utf-8")


def _ltree_decode(value: bytes) -> str:
    return value[1:].decode("utf-8")


def _register_codecs(engine: AsyncEngine) -> None:
    """各物理コネクションに ltree のバイナリコーデックを登録する（COPY 投入のため、§13.4）。

    SQLAlchemy 通常経路では bind_expression で text→ltree キャストするが、asyncpg の
    ``copy_records_to_table`` はバイナリ COPY のため、ltree のバイナリエンコーダが要る。
    """

    @event.listens_for(engine.sync_engine, "connect")
    def _on_connect(dbapi_connection: Any, _record: Any) -> None:
        dbapi_connection.run_async(
            lambda conn: conn.set_type_codec(
                "ltree",
                schema="public",
                encoder=_ltree_encode,
                decoder=_ltree_decode,
                format="binary",
            )
        )


def build_engine(url: str) -> AsyncEngine:
    """接続 URL から async エンジンを生成する。

    ``pool_pre_ping=True`` でプール内のデッドコネクションを使う前に検査する。
    エンジン生成時点では接続は張られない（遅延接続）。
    """
    engine = create_async_engine(url, pool_pre_ping=True)
    _register_codecs(engine)
    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """エンジンからセッションファクトリを生成する。"""
    return async_sessionmaker(engine, expire_on_commit=False)


def _make_default() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    engine = build_engine(default_settings.database_url)
    return engine, build_session_factory(engine)


#: アプリ全体で共有する既定エンジンとセッションファクトリ
engine, SessionFactory = _make_default()


def configure(url: str, *, null_pool: bool = False) -> None:
    """共有エンジン／セッションファクトリを再構築する（接続先の差し替え、主にテスト用）。

    ``null_pool=True`` で ``NullPool`` を使う（イベントループをまたぐテストでの
    asyncpg コネクション再利用問題を避ける）。
    """
    global engine, SessionFactory
    kwargs: dict[str, Any] = {"pool_pre_ping": True}
    if null_pool:
        kwargs["poolclass"] = NullPool
    engine = create_async_engine(url, **kwargs)
    _register_codecs(engine)
    SessionFactory = build_session_factory(engine)


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
