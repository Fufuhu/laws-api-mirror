## 6. Alembic 運用

- すべてのスキーマ変更は Alembic リビジョンとして管理。
- 参照テーブル（`category`, `era`, `law_type`, …）は **データ移行**もリビジョン内で実施（v2 仕様変更時はリビジョンで追記）。
- `ltree`, `pg_bigm` などの拡張は `op.execute("CREATE EXTENSION IF NOT EXISTS ...")` で初期リビジョンに含める。`tsvector` は標準搭載（拡張不要）。`textsearch_ja`（MeCab トークナイザ）は Docker イメージ側でセットアップ（§2.4 / §11.1）。
- **Procrastinate スキーマ**は独立 schema（例: `procrastinate`）として配置し、`procrastinate` 公式提供の SQL を Alembic リビジョン化して同居管理（§11.7）。
- `EXCLUDE` 制約・`GENERATED ... STORED` 列・`tsvector` / `pg_bigm` の GIN インデックスは autogenerate で漏れるため手書き必須。
- 法令標準 XSD バージョンアップ時の `node_kind` / `era` 等の参照テーブル追記運用は §11.12 を参照。

