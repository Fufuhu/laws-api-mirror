# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## リポジトリの現状

e-Gov 法令 API v2 互換のミラーサーバー。取得（一括 Zip）→ 取り込み（パース → 正規化投入）→ 検索 → v2 互換 API での再提供までが一通り実装済み。日次差分は Procrastinate ワーカーで自動取り込みする。

- 言語: Python 3.12+（パッケージ管理は uv、`uv.lock` をコミット）
- DB: PostgreSQL 16（`pg_bigm` / `ltree` を同梱したカスタムイメージ `docker/postgres/`）
- 全体方針の根拠は `docs/design/`（章ごとに分割）。設計書は「仕様・意思決定の記録」であり、実装状況は本ファイルと `README.md` を参照。

## よく使うコマンド

```sh
uv sync                           # 依存解決
uv run pytest -q                  # テスト（Docker があれば testcontainers 統合テストも実行）
uv run pytest tests/api/test_query.py::test_parse_or_and_not   # 単体テスト 1 件
uv run ruff check src tests       # lint
uv run ruff format src tests      # format（CI は --check）
uv run mypy                       # 型チェック（strict、files=src,tests）
uv run alembic upgrade head       # スキーマ適用 / alembic revision --autogenerate -m "..." で雛形生成
docker compose up -d --build      # postgres + migrate + worker
uv run uvicorn laws_api_mirror.api.app:app --reload   # API サーバー
uv run laws-ingest <download|bootstrap|worker|enqueue-delta>   # 取り込み CLI
uv run laws-mcp                   # 法令検索 MCP サーバー（要 FastAPI 稼働）
```

**変更は ruff / ruff format / mypy / pytest をすべて通すこと。** DB が絡む変更は compose もしくは testcontainers で実 DB 検証する（SQLite では `ltree`/`pg_bigm`/`EXCLUDE` 等が使えない）。

## 全体アーキテクチャ

データの流れ（取得 → 取り込み → 再提供）が複数モジュールにまたがる。

- `ingest/`（取り込みパイプライン）
  - `downloader` + `bulkdownload`: e-Gov 一括ダウンロード Zip をストリーミング取得し landing zone（現状ローカル FS）へ着地。
  - `archive`: Zip を展開し法令単位に列挙（フォルダ名＝`law_revision_id`）。
  - `parse`（lxml）: 法令標準 XML → `ParsedLaw`（メタ + `law_node` ツリーの前順リスト）。本文ツリーの根は LawBody 直下、インライン要素は葉に畳み込み、ltree パスを構築。
  - `load`: `law` / `law_revision` を UPSERT、`law_node` を洗い替え（親子 `parent_id` はシーケンス採番で解決）、原文 XML を `law_xml` に gzip 保存。
  - `bootstrap`: Zip 全件を 1 法令 = 1 トランザクションで投入。二次索引を DROP→後構築（§13.4）。`ingest_run`/`ingest_law_event` に記録。
  - `search`: fugashi で形態素分割し `to_tsvector('simple', ...)` を `law_node.text_search` に書き込む（§11.1 方式 B）。
  - `jobs`（Procrastinate）: `ingest_delta` / `ingest_archive` タスク、`@periodic` の `daily_delta`。ワーカーは別プロセス。
- `api/`（再提供）
  - `routers/`: `laws` / `law_revisions` / `law_data` / `law_file` / `keyword`。
  - `rendering`: 原文 XML を源泉に `{tag,attr,children}`(full)/light/Base64 XML を再構築。`elm` はパスラベル規則で XML を辿る。
  - `query`: 検索式（AND/OR/NOT・括弧・ワイルドカード）→ pg_bigm の LIKE ブール条件にコンパイル。
  - `schemas` / `mappers` / `pagination` / `repository`: レスポンス整形・id 解決。
- `db/`: `session`（async エンジン・`get_session`・テスト用 `configure`、COPY 用 ltree コーデック登録）、`models`（§4 の全テーブル）、`types`（`LTREE`）。
- `mcp_server`: 法令検索の MCP サーバー（Streamable HTTP）。FastAPI の `/api/2/keyword` を HTTP 経由で呼ぶ薄いプロキシ（`docs/guides/MCPサーバーガイド.md`）。
- `migrations/`: 初期スキーマ（拡張・EXCLUDE・GIN/GiST・マスタ投入）と procrastinate スキーマ（専用スキーマに隔離）。

## 取り込み・同期戦略

- **取得チャネルは一括 Zip 単独**（REST API v2 は再提供専用で、取得には使わない、§12.1）。
- **初回**は `file_section=1`（全件）/分類別を `bootstrap` で投入。**日次差分**は `file_section=3&update_date=` を Procrastinate `@periodic`（03:00）で自動取り込み（差分は索引を保持＝DROP しない）。
- **冪等性**: `law_revision_id` 単位の UPSERT＋ノード洗い替え、`law_xml.xml_sha256`、Procrastinate の `retry`。
- **検索**: pg_bigm（`text_plain` 部分一致）＋ tsvector（`text_search` 形態素）のハイブリッド（§5）。

## 参照データの注意

- `node_kind`（XSD v3 全要素）・`category`（e-Gov 事項別分類、コードは実形式 `"1".."50"`）は初期マイグレーションで投入済み。XSD バージョンアップ時の要素追加は後続リビジョンで行う（§11.12.4）。

## 言語に関する取り決め

CLAUDE.md・コメント・コミットメッセージ・ドキュメントは日本語で記述する。
