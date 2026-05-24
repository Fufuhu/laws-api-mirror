from fastapi import FastAPI

from laws_api_mirror import __version__
from laws_api_mirror.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="laws-api-mirror",
        version=__version__,
        description=(
            "e-Gov 法令 API v2 互換ミラーサーバー。"
            "本リリース時点では雛形のみで、互換エンドポイントは未実装。"
        ),
    )

    @app.get("/health", tags=["meta"], summary="ヘルスチェック")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(settings.api_base_path, tags=["meta"], summary="API ベース情報")
    async def api_root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "base_path": settings.api_base_path,
        }

    return app


app = create_app()
