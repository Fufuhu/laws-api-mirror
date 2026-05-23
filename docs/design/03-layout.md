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
│   │   └── tasks.py        # ジョブ定義
│   ├── search/             # キーワード検索（pgroonga or tsvector）
│   ├── rendering/          # DB → 法令XML / JSON（詳細版/簡易版）の再構築
│   └── core/               # 設定・ロギング・例外
└── docs/
    └── design.md           # 本ファイル
```

