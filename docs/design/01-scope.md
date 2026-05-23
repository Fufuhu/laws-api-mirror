## 1. 目的とスコープ

e-Gov 法令API Version 2（`https://laws.e-gov.go.jp/api/2/`）が提供する法令データ・法令本文XML（法令標準XMLスキーマ準拠）を、ローカルの PostgreSQL に正規化した形で取り込み、互換性のある HTTP API を FastAPI で再提供するプロジェクト。

### 参考リンク

- **法令API v2 OpenAPI 仕様**: `https://laws.e-gov.go.jp/api/2/swagger-ui/lawapi-v2.yaml`（Swagger UI: `https://laws.e-gov.go.jp/api/2/swagger-ui`、Redoc: `https://laws.e-gov.go.jp/api/2/redoc/`）
- **法令標準XMLスキーマ v3.0** (2020-11-24, 総務省): `https://laws.e-gov.go.jp/file/XMLSchemaForJapaneseLaw_v3.xsd`
- **ヘルプ「データの二次利用」**: `https://laws.e-gov.go.jp/help/#law-xml-schema`
- **XML 一括ダウンロード**: `https://laws.e-gov.go.jp/bulkdownload/`（`file_section=1` 全件 / `file_section=2&category_cd=` 分類別 / `file_section=3&update_date=YYYYMMDD` 差分 過去3か月）
- **法令データ ドキュメンテーション (α)**: `https://laws.e-gov.go.jp/docs/`

主要要件:

- e-Gov 法令API v2 の **6 エンドポイント**を互換維持（パス・クエリ・JSON レスポンス）。
- 法令本文 XML を **構造化された RDB テーブル**に展開し、要素単位（`MainProvision-Article_21-Paragraph_3` 等）の取得を SQL で完結させる。
- 取り込みは **XML 一括ダウンロード**（`bulkdownload` エンドポイント）または **差分（過去 3 か月）**を Alembic 管理スキーマに ETL する。
- 取り込み済データに対する全文検索（キーワード検索 API 互換）を PostgreSQL で実装。

非スコープ:

- e-Gov 側にしかない添付ファイルの永続生成・配布（バイナリは取得時の Blob として保持）。
- 検索式の独自拡張（ワイルドカード・AND/OR/NOT は e-Gov 仕様に揃える）。

