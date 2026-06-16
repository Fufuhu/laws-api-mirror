# laws-api-mirror

[![test](https://github.com/Fufuhu/laws-api-mirror/actions/workflows/test.yml/badge.svg)](https://github.com/Fufuhu/laws-api-mirror/actions/workflows/test.yml)

e-Gov 法令 API v2 (`https://laws.e-gov.go.jp/api/2/`) と互換性のあるミラーサーバー。法令データを PostgreSQL に正規化して取り込み、FastAPI で再提供する。

設計ドキュメントは [`docs/design/`](./docs/design/README.md) を参照。

> [!IMPORTANT]
> 本リポジトリはローカル環境での動作のみを意図している。インターネットに公開するサーバーとしての運用は想定しておらず、公開サーバーとしての動作検証・セキュリティ検証・負荷検証等は一切行っていない。公開環境での利用は自己責任とし、認証・アクセス制御・通信の暗号化などは利用者側で別途対応すること。

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
- **MCP**: AI アシスタント（Claude 等）から法令を「探す → 絞る → 取る」操作ができる MCP サーバー（Streamable HTTP）。全文検索・法令一覧・改正履歴・本文取得の 4 ツール（下表）を公開する。[`docs/guides/MCPサーバーガイド.md`](./docs/guides/MCPサーバーガイド.md)。
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

### MCP ツール

AI アシスタントから利用できる MCP ツール。稼働中の FastAPI（`/api/2/...`）を呼ぶ薄いプロキシで、本文全体ではなく必要十分な情報（抜粋・light JSON）に絞って返す。

| ツール | 概要 | 叩く API |
|---|---|---|
| `keyword_search(keyword, limit, law_type, category_cd, asof, current)` | 検索式（AND/OR/NOT・括弧・ワイルドカード）で全文検索し、該当条文の抜粋を関連度順に返す | `/api/2/keyword` |
| `search_laws(title, law_type, limit, category_cd, asof, current)` | 題名・種別・分類・時点で法令を探し、一覧（法令 ID・題名・番号）を返す | `/api/2/laws` |
| `list_law_revisions(law_id)` | 改正履歴一覧（施行日・現行最新フラグ・状態・改正法令 ID つき） | `/api/2/law_revisions/{id}` |
| `get_law_text(law_id, elm, asof)` | 法令本文を light JSON で取得（`elm` で特定条文・`asof` で時点指定） | `/api/2/law_data/{id}` |

典型フロー: `keyword_search` / `search_laws` で `law_id` を見つけ → `get_law_text(law_id, elm="MainProvision-Article_9")` で条文を読む。詳細は [`docs/guides/MCPサーバーガイド.md`](./docs/guides/MCPサーバーガイド.md)。

## クイックスタート

### 1. データ保存先・取り込みワーカー・API・MCP を起動

```sh
docker compose up -d --build
# postgres（pg_bigm/ltree 同梱）+ migrate（Alembic）+ worker（日次差分）
# + api（v2 互換 API: http://localhost:8000）+ mcp（MCP: http://localhost:8765/mcp）が起動する
```

### 2. 法令データを取り込む

通常は **全件取り込み（初期ブートストラップ）** を行う。これで全法令が検索対象になる。

```sh
uv run laws-ingest download --section 1          # 全件 Zip（GB 級）を取得
uv run laws-ingest bootstrap var/landing/raw/bulk/<取得日>/section1/all_xml.zip
```

> [!NOTE]
> 全件は GB 級・数百万ノードになり、取り込みに数十分かかる。先に疎通だけ確認したい場合は、
> 下記の分類別（小サイズ）で一連の流れを試してから全件に進むとよい。

取り込み結果は `/health/ingest` で確認できる（`total` が取り込んだ法令数）。

```sh
curl -s localhost:8000/health/ingest | jq .
```

<details>
<summary>分類別に一部だけ取り込む（スモークテスト・部分取り込み）</summary>

```sh
# 分類別 Zip（例: 1=憲法）を取得 → landing zone に着地
uv run laws-ingest download --section 2 --category 1

# 取り込み（parse → load → text_search 生成）
uv run laws-ingest bootstrap var/landing/raw/bulk/<取得日>/section2/1_xml.zip
```

この方法では指定した分類の法令しか入らない（例: 憲法分類のみ）。全法令を引くには上記の `--section 1` を使う。
</details>

手順の詳細・再取り込み・確認方法は [`docs/guides/取り込み実行ガイド.md`](./docs/guides/取り込み実行ガイド.md) を参照。

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

## データの出典

本アプリケーションは、デジタル庁が運営する **e-Gov 法令検索**（<https://laws.e-gov.go.jp/>）で公開されている法令データ（法令標準 XML）を前提として動作する。取得・取り込み・再提供の対象となるすべての法令本文は、e-Gov 法令検索の一括ダウンロードおよび法令 API v2 を出典とする。

法令データを利用する際は、e-Gov が定める[利用規約](https://laws.e-gov.go.jp/terms/)に従うこと。

## 謝辞

法令データを整備し、機械可読な形で広く公開してくださっている e-Gov 法令検索の運営に携わるデジタル庁および関係省庁の皆様、ならびに法令標準 XML スキーマの策定・データ整備・API 提供に尽力されているすべての関係者の皆様に、心より感謝申し上げます。本リポジトリは、こうした公開データの基盤があってはじめて成り立っています。
