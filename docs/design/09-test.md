## 9. テスト方針

- **ユニット**: XML パーサのフィクスチャ（代表的法令 XML を 10〜20 件、XSD バージョンタグ付き）、`elm` パスのパス変換、`enforcement_period` の計算、検索式パーサ（pg_bigm / tsvector 振り分け、§5）。
- **統合**: testcontainers で Postgres を立て（`pg_bigm` / `ltree` / `textsearch_ja` 同梱イメージ、§2.10）、Alembic で最新スキーマを適用 → 法令 1 件投入 → 全エンドポイントを叩いて JSON/XML 双方を比較。
- **添付ファイル統合**: SeaweedFS（または `motoserver/moto` 等の S3 モック）を testcontainers で同梱し、`/attachment/{law_revision_id}` の S3 連携を疎通確認。
- **ジョブ統合**: Procrastinate ワーカーを別プロセスで立ち上げ、`@task` / `@periodic` の発火と `amendment_law` の Lazy reconciliation（§11.8）が想定どおり動くか検証。
- **互換性（インタフェース）**: 実 e-Gov API のレスポンスを録画し、同じパラメータで本実装の **レスポンス形状（フィールド名・型）** を差分比較するスナップショットテスト。1st リリースでは **バイト単位一致は目指さない**（§10-9）。
- **互換性（エッジケース観測）**: §11.11 の JSON light エッジケース項目を観測値として記録し、将来合わせ込みの判断材料とする。

