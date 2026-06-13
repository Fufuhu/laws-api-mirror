# laws-api-mirror

[![test](https://github.com/Fufuhu/laws-api-mirror/actions/workflows/test.yml/badge.svg)](https://github.com/Fufuhu/laws-api-mirror/actions/workflows/test.yml)

e-Gov 法令 API v2 (`https://laws.e-gov.go.jp/api/2/`) と互換性のあるミラーサーバー。法令データを PostgreSQL に正規化して取り込み、FastAPI で再提供する。

設計ドキュメントは [`docs/design/`](./docs/design/README.md) を参照。

## できること

```
取得            取り込み                         再提供
download  →  bootstrap / 日次差分ワーカー  →  v2 互換 API
(一括Zip)    parse(lxml) → load(law_node)        /laws /law_data /keyword …
             → text_search(fugashi)              （pg_bigm + tsvector 検索）
```

- **取り込み**: e-Gov 一括ダウンロード Zip を取得し、法令標準 XML を `law_node`（隣接リスト + ltree）に正規化。原文 XML も `law_xml` に保持。
- **検索**: pg_bigm（部分一致）＋ tsvector（fugashi 形態素）のハイブリッド。`/keyword` は AND/OR/NOT・括弧・ワイルドカードの検索式に対応。
- **再提供**: e-Gov v2 互換の 5 エンドポイント（下表）。
- **MCP**: AI アシスタント（Claude 等）から法令を全文検索できる MCP サーバー（Streamable HTTP）。[`docs/guides/MCPサーバーガイド.md`](./docs/guides/MCPサーバーガイド.md)。
- **運用**: Procrastinate（PostgreSQL バックエンド、Redis 不使用）で日次差分を自動取り込み。
- **品質**: CI（GitHub Actions）で ruff / mypy(strict) / pytest、testcontainers による実 DB 統合テスト。

### API エンドポイント

| メソッド | パス | 概要 |
|---|---|---|
| GET | `/api/2/laws` | 法令一覧（`law_title`/`law_type`/… 絞り込み、ページング） |
| GET | `/api/2/law_revisions/{id}` | 法令履歴一覧 |
| GET | `/api/2/law_data/{id}` | 法令本文（JSON/XML、`elm` でサブツリー抽出） |
| GET | `/api/2/law_file/{file_type}/{id}` | 本文ファイル（xml / json。html/rtf/docx は 400、§10-3） |
| GET | `/api/2/keyword` | キーワード検索（検索式 + ハイライト） |
| GET | `/api/2/attachment/{id}` | 添付ファイル（**未実装**。§4.8 / §11.2） |

## クイックスタート

### 1. データ保存先と取り込みワーカーを起動

```sh
docker compose up -d --build
# postgres（pg_bigm/ltree 同梱）+ migrate（Alembic）+ worker（日次差分）が起動する
```

### 2. 法令データを取り込む

```sh
# 分類別 Zip（例: 1=憲法）を取得 → landing zone に着地
uv run laws-ingest download --section 2 --category 1

# 取り込み（parse → load → text_search 生成）
uv run laws-ingest bootstrap var/landing/raw/bulk/<取得日>/section2/1_xml.zip
```

### 3. API を起動して引く

```sh
uv run uvicorn laws_api_mirror.api.app:app --reload   # http://127.0.0.1:8000

curl 'http://127.0.0.1:8000/api/2/laws?law_type=Constitution'
curl 'http://127.0.0.1:8000/api/2/law_data/321CONSTITUTION?elm=MainProvision-Chapter_2-Article_9'
curl 'http://127.0.0.1:8000/api/2/keyword?keyword=戦争の放棄'
open http://127.0.0.1:8000/docs   # OpenAPI
```

詳細は [`docs/guides/ダウンロード実行ガイド.md`](./docs/guides/ダウンロード実行ガイド.md) を参照。

### 4. （任意）MCP サーバーで AI から検索

```sh
uv run laws-mcp   # http://127.0.0.1:8765/mcp（Streamable HTTP）
```

MCP クライアントから `/mcp` に接続し、`keyword_search` / `search_laws` / `list_law_revisions` / `get_law_text` ツールを使う。詳細は [`docs/guides/MCPサーバーガイド.md`](./docs/guides/MCPサーバーガイド.md)。

## CLI（`laws-ingest`）

| コマンド | 用途 |
|---|---|
| `download --section {1,2,3} [...]` | 一括 Zip を取得（全件 / 分類別 / 差分） |
| `bootstrap <zip>` | Zip から全法令を投入（索引 DROP→後構築） |
| `worker` | Procrastinate ワーカー常駐（日次 03:00 差分） |
| `enqueue-delta --update-date YYYYMMDD` | 差分取り込みジョブを手動投入 |

## 開発

```sh
uv sync                      # 依存解決
uv run pytest                # テスト（Docker があれば統合テストも実行）
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run mypy                  # 型チェック（strict）
uv run alembic upgrade head  # スキーマ適用
```

統合テストは `laws-api-mirror-pg:16` イメージを testcontainers で起動して実行する（無ければ自動スキップ）。CI は `.github/workflows/test.yml` 参照。

## 技術スタック

Python 3.12+ / FastAPI / SQLAlchemy 2.x(async) + asyncpg / PostgreSQL 16（pg_bigm・ltree）/ Alembic / lxml / fugashi(unidic-lite) / Procrastinate / uv。詳細は [`docs/design/02-技術スタック.md`](./docs/design/02-技術スタック.md)。

## ディレクトリ構成

```
src/laws_api_mirror/
  api/        FastAPI アプリ・ルーター・スキーマ・レンダリング・検索式
  ingest/     取得(downloader) / 展開(archive) / パース(parse) / 投入(load)
              / 全件投入(bootstrap) / 検索索引(search) / ジョブ(jobs) / CLI
  db/         接続(session) / ORM モデル(models) / 型(types)
  core/       設定(config)
  mcp_server  法令検索の MCP サーバー（Streamable HTTP）
migrations/   Alembic（初期スキーマ + procrastinate スキーマ）
docker/       postgres（pg_bigm 同梱）/ app（worker 実行イメージ）
docs/         design（設計書）/ guides / tests
tests/        unit + integration（testcontainers）
```
