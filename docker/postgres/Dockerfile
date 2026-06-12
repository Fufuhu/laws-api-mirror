# 法令データの保存先 PostgreSQL イメージ。
#
# 設計 §2.4（PostgreSQL 16）／§5（pg_bigm + tsvector ハイブリッド検索）／
# §4.7.1（ltree による elm パス解決）に対応する。
#
# - ltree: 公式イメージの contrib に同梱（追加ビルド不要）。
# - pg_bigm: PGDG にプリビルドパッケージが無いため、ソースからビルドして導入する。
#   ビルド依存は一時的に入れてコンパイル後に除去し、ランタイムイメージを肥大させない。
#
# 検索のトークナイズ（MeCab）はアプリ側（Python fugashi）で行う方針のため（§11.1-B）、
# DB イメージには textsearch_ja を同梱しない。
FROM postgres:16

# https://github.com/pgbigm/pg_bigm のリリースタグ
ARG PG_BIGM_VERSION=1.2-20250903

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
        libicu-dev \
        curl \
        ca-certificates; \
    curl -fsSL -o /tmp/pg_bigm.tar.gz \
        "https://github.com/pgbigm/pg_bigm/archive/refs/tags/v${PG_BIGM_VERSION}.tar.gz"; \
    mkdir -p /tmp/pg_bigm; \
    tar -xzf /tmp/pg_bigm.tar.gz -C /tmp/pg_bigm --strip-components=1; \
    cd /tmp/pg_bigm; \
    make USE_PGXS=1; \
    make USE_PGXS=1 install; \
    apt-get purge -y --auto-remove build-essential postgresql-server-dev-16 libicu-dev curl; \
    rm -rf /var/lib/apt/lists/* /tmp/pg_bigm /tmp/pg_bigm.tar.gz

# 初回 initdb 時に拡張を有効化する SQL を配置（/docker-entrypoint-initdb.d）
COPY initdb/ /docker-entrypoint-initdb.d/
