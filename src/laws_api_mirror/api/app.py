from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror import __version__
from laws_api_mirror.api.routers import keyword as keyword_router
from laws_api_mirror.api.routers import law_data as law_data_router
from laws_api_mirror.api.routers import law_file as law_file_router
from laws_api_mirror.api.routers import law_revisions as law_revisions_router
from laws_api_mirror.api.routers import laws as laws_router
from laws_api_mirror.api.schemas import IngestRunInfo, IngestStatusResponse
from laws_api_mirror.core.config import settings
from laws_api_mirror.core.logging import configure_logging
from laws_api_mirror.db.session import check_connection, dispose_engine, get_session
from laws_api_mirror.ingest.status import collect_ingest_status


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # 起動時は遅延接続のため何もしない。終了時にエンジン（プール）を破棄する。
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    configure_logging(settings.log_level, json_format=settings.log_json)
    app = FastAPI(
        title="laws-api-mirror",
        version=__version__,
        description="e-Gov 法令 API v2 互換ミラーサーバー。",
        lifespan=lifespan,
    )

    app.include_router(laws_router.router)
    app.include_router(law_revisions_router.router)
    app.include_router(law_data_router.router)
    app.include_router(law_file_router.router)
    app.include_router(keyword_router.router)

    @app.get("/health", tags=["meta"], summary="ヘルスチェック")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/db", tags=["meta"], summary="DB 疎通ヘルスチェック")
    async def health_db(session: AsyncSession = Depends(get_session)) -> dict[str, str]:
        await check_connection(session)
        return {"database": "ok"}

    @app.get(
        "/health/ingest",
        tags=["meta"],
        summary="取り込み状態ヘルスチェック",
        response_model=IngestStatusResponse,
    )
    async def health_ingest(
        session: AsyncSession = Depends(get_session),
    ) -> IngestStatusResponse:
        """最終取り込み・最終成功・直近の失敗を集約して返す（C-1 / C-3）。

        ``status`` は never / running / failed / stale / ok。日次差分が止まると
        最後の成功が古くなり ``stale`` になるため、外形監視のフックに使える。
        """
        status = await collect_ingest_status(
            session,
            now=datetime.now(UTC),
            freshness_hours=settings.ingest_freshness_hours,
        )
        last_run = (
            IngestRunInfo(
                id=status.last_run.id,
                kind=status.last_run.kind,
                status=status.last_run.status,
                started_at=status.last_run.started_at,
                finished_at=status.last_run.finished_at,
                stats=status.last_run.stats,
            )
            if status.last_run is not None
            else None
        )
        return IngestStatusResponse(
            status=status.status,
            total_runs=status.total_runs,
            last_run=last_run,
            last_success_at=status.last_success_at,
            recent_failures=status.recent_failures,
            failed_samples=status.failed_samples,
        )

    @app.get(settings.api_base_path, tags=["meta"], summary="API ベース情報")
    async def api_root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "base_path": settings.api_base_path,
        }

    return app


app = create_app()
