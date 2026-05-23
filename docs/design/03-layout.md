## 3. プロジェクト構成（予定）

```
laws-api-mirror/
├── pyproject.toml
├── alembic.ini
├── alembic/
│   └── versions/
├── src/laws_api_mirror/
│   ├── api/                # FastAPI ルーター（v2 互換）
│   │   ├── routes/
│   │   │   ├── laws.py
│   │   │   ├── revisions.py
│   │   │   ├── law_data.py
│   │   │   ├── law_file.py
│   │   │   ├── attachment.py
│   │   │   └── keyword.py
│   │   └── schemas/        # Pydantic（e-Gov のスキーマ名と一致）
│   ├── db/
│   │   ├── models/         # SQLAlchemy モデル
│   │   ├── session.py
│   │   └── repository/     # クエリ層（API ハンドラから呼ぶ）
│   ├── ingest/             # 取り込みパイプライン
│   │   ├── downloader.py   # bulkdownload からの取得
│   │   ├── xml_parser.py   # 法令XML → 中間DTO
│   │   ├── loader.py       # 中間DTO → RDB（UPSERT）
│   │   └── attachments.py  # 添付ファイルの S3 アップロード
│   ├── jobs/               # Procrastinate アプリ・タスク定義（§11.7）
│   │   ├── app.py          # Procrastinate App 初期化
│   │   ├── ingest.py       # 取り込みタスク（@task / @periodic）
│   │   └── reconciliation.py  # amendment_law の Lazy reconciliation (§11.8)
│   ├── search/             # キーワード検索（pg_bigm + tsvector ハイブリッド、§5）
│   │   ├── query_parser.py # 検索式 AST 化
│   │   └── engine.py       # pg_bigm / tsvector エンジンアダプタ
│   ├── storage/            # オブジェクトストレージ（AWS S3 / SeaweedFS）クライアント
│   ├── rendering/          # DB → 法令XML / JSON（詳細版/簡易版）の再構築
│   └── core/               # 設定・ロギング・例外
└── docs/
    ├── design/             # 本設計ドキュメント（章ごとに分割）
    └── guides/             # 補助解説ドキュメント（例: testcontainers.md）
```

