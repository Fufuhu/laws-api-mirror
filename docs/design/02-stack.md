## 2. 技術スタック

| 層 | 採用 | 備考 |
|---|---|---|
| 言語 | Python 3.12+ | `pyproject.toml` を採用 |
| パッケージ管理 | uv（推奨）または Poetry | 未決定。要確認 |
| Web | FastAPI + Uvicorn / Gunicorn | OpenAPI 自動生成を v2 仕様に合わせる |
| DB | PostgreSQL 16 | 全文検索は `pg_trgm` + `tsvector`（日本語は `pgroonga` 採用を要検討） |
| ORM | SQLAlchemy 2.x（async） | `asyncpg` ドライバ |
| マイグレーション | Alembic | autogenerate を活用、ただしレビュー必須 |
| XML パース | `lxml`（iterparse でストリーミング） | 1 法令あたり XML が大きいため SAX 風処理 |
| ジョブ | Arq / RQ / Celery いずれか | 一括取り込みは長時間化するため別プロセス |
| Lint/Format | Ruff + mypy | |
| テスト | pytest + pytest-asyncio + testcontainers (Postgres) | |

