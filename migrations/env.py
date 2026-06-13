"""Alembic 実行環境（async / asyncpg 対応）。

接続 URL はアプリ設定（``settings.database_url``、環境変数 ``DATABASE_URL`` で上書き）
から取得する。``target_metadata`` は ORM の ``Base.metadata``（autogenerate 用）。
初期スキーマは手書きリビジョンが作成する（設計 §2.6）。
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

import laws_api_mirror.db.models  # noqa: F401  全テーブルを Base.metadata に登録
from laws_api_mirror.core.config import settings
from laws_api_mirror.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """オフライン（--sql）モード。DBA レビュー用の SQL を出力する。"""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """オンラインモード。async エンジンで接続してマイグレーションを適用する。"""
    engine = create_async_engine(settings.database_url, poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
