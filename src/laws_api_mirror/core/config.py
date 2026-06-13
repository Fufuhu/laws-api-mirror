from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from laws_api_mirror import __version__


class Settings(BaseSettings):
    """アプリケーション設定。環境変数または .env から読み込む。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "laws-api-mirror"
    api_base_path: str = "/api/2"

    # --- MCP サーバー（FastAPI を HTTP 経由で呼ぶプロキシ） ---
    #: MCP ツールが叩く FastAPI のベース URL
    api_base_url: str = "http://127.0.0.1:8000"
    #: MCP（Streamable HTTP）の待受ホスト・ポート（FastAPI と別ポート）
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8765

    #: データ保存先 PostgreSQL への接続 URL（SQLAlchemy async / asyncpg ドライバ）。
    #: docker-compose の既定値に合わせる。本番・CI は環境変数 DATABASE_URL で上書きする。
    database_url: str = "postgresql+asyncpg://laws:laws@localhost:5432/laws"

    # --- 全件ダウンロード（docs/design/12-全件ダウンロード.md §12.2 / §12.7） ---
    #: e-Gov XML 一括ダウンロードのベース URL
    bulkdownload_base_url: str = "https://laws.e-gov.go.jp/bulkdownload"
    #: 生 Zip を着地させる landing zone（§12.4）。現時点はローカル FS。将来 S3 に差し替え。
    download_landing_dir: Path = Path("var/landing")
    #: 大量リクエストではないが礼儀として連絡先入りの User-Agent を必ず付与（§12.7）
    download_user_agent: str = (
        f"laws-api-mirror/{__version__} "
        "(+https://github.com/Fufuhu/laws-api-mirror; e-Gov law data mirror)"
    )
    #: 接続タイムアウト（秒）
    download_connect_timeout: float = 30.0
    #: 読み取りタイムアウト（秒）。GB 級 Zip のストリーミングを許容する長め設定。
    download_read_timeout: float = 600.0
    #: 失敗時の最大試行回数（指数バックオフ、§12.7）
    download_max_retries: int = 5
    #: バックオフの底（delay = base ** attempt）
    download_backoff_base: float = 2.0
    #: バックオフ上限（秒）
    download_backoff_max: float = 60.0
    #: ストリーミング受信のチャンクサイズ（バイト）。既定 1 MiB。
    download_chunk_size: int = 1 << 20

    @property
    def procrastinate_dsn(self) -> str:
        """Procrastinate（psycopg）用の DSN。asyncpg ドライバ指定を外す。"""
        return self.database_url.replace("+asyncpg", "")


settings = Settings()
