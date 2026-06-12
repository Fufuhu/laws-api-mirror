from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror import __version__
from laws_api_mirror.api.routers import law_data as law_data_router
from laws_api_mirror.api.routers import laws as laws_router
from laws_api_mirror.core.config import settings
from laws_api_mirror.db.session import check_connection, dispose_engine, get_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 起動時は遅延接続のため何もしない。終了時にエンジン（プール）を破棄する。
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    app = FastAPI(
        title="laws-api-mirror",
        version=__version__,
        description="e-Gov 法令 API v2 互換ミラーサーバー。",
        lifespan=lifespan,
    )

    app.include_router(laws_router.router)
    app.include_router(law_data_router.router)

    @app.get("/health", tags=["meta"], summary="ヘルスチェック")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db", tags=["meta"], summary="DB 疎通ヘルスチェック")
    async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
        await check_connection(session)
        return {"database": "ok"}

    @app.get(settings.api_base_path, tags=["meta"], summary="API ベース情報")
    async def api_root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "base_path": settings.api_base_path,
        }

    return app


app = create_app()
