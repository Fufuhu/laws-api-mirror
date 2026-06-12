# アプリ／ワーカー実行イメージ（uv ベース）。
#
# worker（Procrastinate）と migrate（Alembic）を同一イメージで動かす。
# psycopg は python 実装でシステム libpq を使うため libpq5 を入れる。
# 取り込み時のトークナイズ（fugashi）・XML パース（lxml）はホイール同梱で追加導入不要。
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 依存だけ先に解決してレイヤキャッシュを効かせる（runtime のみ、dev 群は除外）
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# アプリ本体とマイグレーション
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# 既定はワーカー。migrate サービスは command を alembic に差し替える。
CMD ["laws-ingest", "worker"]
