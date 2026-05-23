## 6. Alembic 運用

- すべてのスキーマ変更は Alembic リビジョンとして管理。
- 参照テーブル（`category`, `era`, `law_type`, …）は **データ移行**もリビジョン内で実施（v2 仕様変更時はリビジョンで追記）。
- `ltree`, `pg_trgm`, `pgroonga` などの拡張は `op.execute("CREATE EXTENSION IF NOT EXISTS ...")` で初期リビジョンに含める。
- `EXCLUDE` 制約・`tsvector` トリガなどは autogenerate で漏れるため手書き必須。

