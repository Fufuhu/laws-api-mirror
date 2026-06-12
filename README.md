# laws-api-mirror

e-Gov 法令 API v2 (`https://laws.e-gov.go.jp/api/2/`) と互換性のあるミラーサーバー。法令データを PostgreSQL に正規化して取り込み、FastAPI で再提供する。

設計ドキュメントは [`docs/design/`](./docs/design/README.md) を参照。

## クイックスタート

```sh
# 依存解決
uv sync

# 開発サーバー起動 (http://127.0.0.1:8000)
uv run uvicorn laws_api_mirror.api.app:app --reload

# ヘルスチェック
curl http://127.0.0.1:8000/health
# => {"status":"ok"}

# OpenAPI ドキュメント
open http://127.0.0.1:8000/docs
```

## ステータス

実装は **base 段階**。1st リリースのスコープ・確定方針は [`docs/design/10-未確定事項.md`](./docs/design/10-未確定事項.md) を参照。

- 実装済: FastAPI 起動・ヘルスチェック・OpenAPI 雛形
- 未実装: e-Gov API v2 互換エンドポイント、PostgreSQL 連携、取り込みパイプライン、検索、ジョブキュー
