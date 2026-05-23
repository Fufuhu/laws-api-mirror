# laws-api-mirror 設計書

## 1. 目的とスコープ

e-Gov 法令API Version 2（`https://laws.e-gov.go.jp/api/2/`）が提供する法令データ・法令本文XML（法令標準XMLスキーマ準拠）を、ローカルの PostgreSQL に正規化した形で取り込み、互換性のある HTTP API を FastAPI で再提供するプロジェクト。

主要要件:

- e-Gov 法令API v2 の **6 エンドポイント**を互換維持（パス・クエリ・JSON レスポンス）。
- 法令本文 XML を **構造化された RDB テーブル**に展開し、要素単位（`MainProvision-Article_21-Paragraph_3` 等）の取得を SQL で完結させる。
- 取り込みは **XML 一括ダウンロード**（`bulkdownload` エンドポイント）または **差分（過去 3 か月）**を Alembic 管理スキーマに ETL する。
- 取り込み済データに対する全文検索（キーワード検索 API 互換）を PostgreSQL で実装。

非スコープ:

- e-Gov 側にしかない添付ファイルの永続生成・配布（バイナリは取得時の Blob として保持）。
- 検索式の独自拡張（ワイルドカード・AND/OR/NOT は e-Gov 仕様に揃える）。

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

## 4. データモデル設計

法令ドメインは **「法令 (`law`)」「履歴 (`law_revision`)」「本文構造ノード (`law_node`)」** の 3 層で構成する。法令 XML の階層構造は、ノードに対する **隣接リスト + materialized path** で表現し、`elm` パラメータの解決をインデックスで一発検索できるようにする。

### 4.1 マスタ／参照テーブル

```
era                  -- (Meiji, Taisho, Showa, Heisei, Reiwa)
law_num_type         -- (Constitution, Act, CabinetOrder, ...)
law_type             -- 同上（API では別概念だが値域は同じ）
category             -- 50 種の事項別分類コード（001 憲法 … 050 外事）
repeal_status        -- (None, Repeal, Expire, Suspend, LossOfEffectiveness)
current_revision_status -- (CurrentEnforced, UnEnforced, PreviousEnforced, Repeal)
amendment_type       -- (1 新規, 3 被改正, 8 廃止)
mission              -- (New, Partial)
```

すべて enum 文字列を主キーとした参照テーブル（ENUM 型でも可。マイグレーション容易性のため lookup テーブル採用を推奨）。

### 4.2 法令メタ（履歴非依存）

```
TABLE law
  law_id            VARCHAR(15) PRIMARY KEY        -- 例: 322CO0000000016
  law_type          FK -> law_type
  law_num           TEXT             NOT NULL UNIQUE  -- 例: 昭和二十二年政令第十六号
  law_num_era       FK -> era
  law_num_year      SMALLINT
  law_num_type      FK -> law_num_type
  law_num_num       TEXT                              -- "016" など、ゼロ詰めあり文字列
  promulgation_date DATE
  created_at, updated_at
  INDEX (law_num_era, law_num_year, law_num_type, law_num_num)
  INDEX (promulgation_date)
```

### 4.3 法令履歴（時点依存メタ）

```
TABLE law_revision
  law_revision_id   VARCHAR(64) PRIMARY KEY  -- 例: 322CO0000000016_20240401_506CO0000000161
  law_id            FK -> law(law_id) NOT NULL
  law_type          FK -> law_type
  law_title         TEXT NOT NULL
  law_title_kana    TEXT
  abbrev            TEXT
  category_cd       FK -> category(cd)        -- 主分類
  updated_at_source TIMESTAMPTZ               -- API の updated
  amendment_promulgate_date DATE
  amendment_enforcement_date DATE
  amendment_enforcement_comment TEXT
  amendment_scheduled_enforcement_date DATE
  amendment_law_id  TEXT                      -- e-Gov 側の改正法令 ID 文字列
  amendment_law_title TEXT
  amendment_law_title_kana TEXT
  amendment_law_num TEXT
  amendment_type    FK -> amendment_type
  repeal_status     FK -> repeal_status
  repeal_date       DATE
  remain_in_force   BOOLEAN
  mission           FK -> mission
  current_revision_status FK -> current_revision_status
  is_current_latest BOOLEAN                   -- current_revision の高速判定
  enforcement_period daterange                -- 履歴の有効期間（PostgreSQL range）
  EXCLUDE USING gist (law_id WITH =, enforcement_period WITH &&) DEFERRABLE
  INDEX (law_id, amendment_enforcement_date DESC)
  INDEX (current_revision_status)
```

- `enforcement_period` は隣接履歴から計算してセット（最新行は `[date, infinity)`）。
- `EXCLUDE` 制約で「同一法令の有効期間が重ならない」ことを保証。
- `asof` クエリは `enforcement_period @> :asof` で O(log N)。

### 4.4 法令 ⇄ 分類（多対多の余地）

主分類は `law_revision.category_cd` に持たせるが、`law_type=array` 検索や複数分類への対応のため、別 M2M テーブルも用意する。

```
TABLE law_revision_category
  law_revision_id   FK
  category_cd       FK
  PRIMARY KEY (law_revision_id, category_cd)
```

### 4.5 改正関係

```
TABLE amendment_relation
  amended_revision_id    FK -> law_revision(law_revision_id)  -- 被改正側
  amending_law_id        VARCHAR(15)                          -- 改正法（law が無い場合もあるため FK 化は緩く）
  amending_law_title     TEXT
  amending_law_num       TEXT
  amendment_type         FK -> amendment_type
  PRIMARY KEY (amended_revision_id, amending_law_id)
```

### 4.6 法令本文（生 XML 保存）

参照頻度は低いが「API 取得時に Base64 / 原文 XML を返却する」要件があるため、リビジョン単位で生 XML（gzip 圧縮）を保持する。

```
TABLE law_xml
  law_revision_id   PK FK -> law_revision
  xml_gz            BYTEA NOT NULL
  xml_sha256        BYTEA NOT NULL
  byte_size         INTEGER
  source_updated_at TIMESTAMPTZ
```

### 4.7 法令本文の構造化（正規化の核）

法令 XML の階層（`Law > LawBody > MainProvision > Part > Chapter > Section > Subsection > Division > Article > Paragraph > Item > Subitem1..10`、+ `TOC`, `Preamble`, `SupplProvision`, `AppdxTable`, `AppdxStyle`, `AppdxFormat`, `Appdx`, `AppdxFig` 等）を **単一テーブル**にツリー格納する。

```
TYPE node_kind ENUM (
  'Law','LawBody','LawNum','LawTitle','EnactStatement','Preamble',
  'TOC','TOCLabel','TOCPart','TOCChapter','TOCSection','TOCArticle','TOCSupplProvision','TOCAppdxTableLabel',
  'MainProvision','Part','Chapter','Section','Subsection','Division',
  'Article','ArticleTitle','ArticleCaption',
  'Paragraph','ParagraphNum','ParagraphSentence','ParagraphCaption',
  'Item','ItemTitle','ItemSentence',
  'Subitem1','Subitem2','Subitem3','Subitem4','Subitem5',
  'Subitem6','Subitem7','Subitem8','Subitem9','Subitem10',
  'SupplProvision','SupplProvisionLabel','SupplProvisionAppdxTable','SupplProvisionAppdxStyle','SupplProvisionAppdx',
  'AppdxTable','AppdxStyle','AppdxFormat','Appdx','AppdxFig','AppdxNote',
  'TableStruct','Table','TableRow','TableColumn','TableHeaderRow','TableHeaderColumn',
  'FigStruct','Fig','StyleStruct','Style','FormatStruct','Format','NoteStruct','Note','RemarksLabel','Remarks',
  'Sentence','Column','List','ListSentence','Sublist1','Sublist2','Sublist3',
  -- インライン要素は基本的に展開せず Sentence の raw_text に残す
  'Other'
)

TABLE law_node
  id                BIGSERIAL PRIMARY KEY
  law_revision_id   FK -> law_revision NOT NULL
  parent_id         BIGINT FK -> law_node(id)
  kind              node_kind NOT NULL
  ordinal           INTEGER NOT NULL              -- 同一親の中での順序
  num               TEXT                          -- Article の Num="21_2" 等（XML属性そのまま）
  num_int           INTEGER                       -- ソート用に主たる番号を数値化
  caption           TEXT                          -- Caption/Title 文字列
  title             TEXT
  -- 構造系の属性
  delete_flag       BOOLEAN
  hide_flag         BOOLEAN
  old_style         BOOLEAN
  -- パス（elm 解決用）
  path              LTREE NOT NULL                -- 例: MainProvision.Article_21.Paragraph_3
  path_text         TEXT NOT NULL                 -- "MainProvision-Article_21-Paragraph_3"
  -- 中身（葉ノード）
  raw_xml           XML                           -- 子要素を XML 断片で保持（Sentence 内のインライン要素を保つ）
  text_plain        TEXT                          -- 検索用プレーン
  text_search       TSVECTOR                      -- 日本語全文検索（pgroonga 採用時は別カラム）
  UNIQUE (law_revision_id, path)
  INDEX USING GIST (path)
  INDEX USING GIN (text_search)
  INDEX (law_revision_id, kind, num_int)
```

設計上のポイント:

1. **隣接リスト + ltree**: `parent_id` で厳密ツリー、`path` (`ltree`) で `elm` の高速検索。`elm=MainProvision-Article_21-Paragraph_3` は `path ~ 'MainProvision.Article_21.Paragraph_3.*'` に変換。
2. **属性は要素種別ごとに必要なものだけカラム化**。Sentence の `WritingMode`、`Paragraph` の `Num`、`AmendLawNum`、`Extract` などは API で個別フィールド化されるため `attrs JSONB` を追加で持つ（下記）。
3. **インライン要素は分解しない**：`<Ruby>` `<Sup>` `<Sub>` `<Line>` `<QuoteStruct>` などは原文 XML に残し、`text_plain` でプレーン化。検索とレンダリングの両方を保つ。
4. **AppdxTable / AppdxFig / Fig は `attached_file` と双方向参照**。

```
TABLE law_node_attr  -- 大量のレア属性を別出し（任意）
  node_id           FK -> law_node ON DELETE CASCADE
  key               TEXT
  value             TEXT
  PRIMARY KEY (node_id, key)
```

実用上は `law_node.attrs JSONB` ひとつで十分なケースが多いため、属性は **`JSONB` 列に集約**してインデックスを必要に応じて式インデックスで張る運用を推奨。

### 4.8 添付ファイル

```
TABLE attached_file
  id                BIGSERIAL PRIMARY KEY
  law_revision_id   FK -> law_revision
  src               TEXT NOT NULL              -- 例: ./pict/M06SE065-001.jpg
  content_type      TEXT                       -- image/jpeg, application/pdf
  byte_size         INTEGER
  sha256            BYTEA
  source_updated_at TIMESTAMPTZ
  UNIQUE (law_revision_id, src)

TABLE attached_file_blob
  attached_file_id  PK FK -> attached_file
  content           BYTEA NOT NULL             -- 大容量の場合は外部ストレージへ
```

実運用ではバイナリは S3/MinIO に逃がし、`attached_file` に URL を持つ構成のほうが Postgres を肥大化させない。要確認。

### 4.9 取り込み管理

```
TABLE ingest_run
  id                BIGSERIAL PRIMARY KEY
  kind              TEXT          -- 'full' | 'delta'
  started_at, finished_at
  status            TEXT          -- 'running' | 'success' | 'failed'
  source_date       DATE          -- delta の場合
  stats             JSONB         -- 法令数・差分件数

TABLE ingest_law_event
  ingest_run_id     FK
  law_revision_id   TEXT
  action            TEXT          -- 'inserted' | 'updated' | 'skipped' | 'failed'
  error             TEXT
```

## 5. インデックス／全文検索戦略

- 法令メタの絞り込み（種別・分類・公布日範囲）は B-tree 複合インデックスで十分。
- `asof` クエリは `enforcement_period @> :asof` + GIST。
- キーワード検索は以下のいずれか:
  - **採用候補 A**: `pgroonga`（日本語形態素・N-gram 両対応、`pgroonga_match_positions_byte` でハイライト座標）。
  - **採用候補 B**: PostgreSQL 標準 `tsvector` + `textsearch_ja`（MeCab）。
  - e-Gov 仕様の `*` `?` ワイルドカードと AND/OR/NOT は **検索式パーサで pgroonga クエリへ変換**するのが現実的。
- 検索のヒット位置（`position` フィールド）は **`law_node`単位**で返すため、`law_node.path_text` をそのまま返却可能。

## 6. Alembic 運用

- すべてのスキーマ変更は Alembic リビジョンとして管理。
- 参照テーブル（`category`, `era`, `law_type`, …）は **データ移行**もリビジョン内で実施（v2 仕様変更時はリビジョンで追記）。
- `ltree`, `pg_trgm`, `pgroonga` などの拡張は `op.execute("CREATE EXTENSION IF NOT EXISTS ...")` で初期リビジョンに含める。
- `EXCLUDE` 制約・`tsvector` トリガなどは autogenerate で漏れるため手書き必須。

## 7. API 設計（v2 互換）

### 7.1 ベースパス

`/api/2/` を維持（e-Gov クライアントがそのまま使えるようにする）。

### 7.2 エンドポイント一覧

| メソッド | パス | 概要 | 実装ノート |
|---|---|---|---|
| GET | `/api/2/laws` | 法令一覧取得 | 14 個のクエリパラメータを Pydantic で受け、`law_revision` を中心に絞り込み |
| GET | `/api/2/law_revisions/{law_id_or_num}` | 法令履歴一覧取得 | `law` をキーに `law_revision` を全件返却 |
| GET | `/api/2/law_data/{law_id_or_num_or_revision_id}` | 法令本文取得（JSON/XML） | `law_xml` から原文 XML を取り出し or `law_node` から再構築 |
| GET | `/api/2/law_file/{file_type}/{law_id_or_num_or_revision_id}` | 法令本文ファイル（xml/json/html/rtf/docx） | xml/json は DB から、html/rtf/docx は事前生成 or オンザフライ |
| GET | `/api/2/attachment/{law_revision_id}` | 添付ファイル | `src` 指定で単体返却、未指定で Zip |
| GET | `/api/2/keyword` | キーワード検索 | pgroonga 検索 → `law_node` ヒット位置 |

### 7.3 共通仕様

- **クエリパラメータの enum は v2 のスキーマ名（`law_num_era=Showa` 等）を厳密一致**で受ける。Pydantic の `Literal` または `StrEnum`。
- **レスポンス形式**: `response_format=json|xml` を全エンドポイントでサポート。`Accept` ヘッダから自動判定するミドルウェアを 1 つ用意。
- **法令本文形式**: `law_full_text_format` と `response_format` が異なる場合は **Base64 でエンコード**する仕様を厳守。
- **エラー形式**: `error_info`（`code`, `message`）。コード体系は e-Gov のものを踏襲（最初はサブセット定義し、リファレンスに合わせて拡張）。
- **並び順 `order`**: `+/-law_info.law_id,-revision_info.amendment_promulgate_date` 形式のパーサを用意し、許可フィールドのホワイトリストで SQL の `ORDER BY` を構築。
- **ページング**: `limit` / `offset` / `next_offset`。`next_offset` は `total_count - (offset+count) > 0` のとき `offset+limit`、それ以外は `null`。

### 7.4 `elm` パラメータ解決

`elm=MainProvision-Article_21-Paragraph_3` を以下のように解決:

1. `-` で分割 → `["MainProvision", "Article_21", "Paragraph_3"]`
2. ltree パスに変換 → `MainProvision.Article_21.Paragraph_3`
3. `SELECT * FROM law_node WHERE law_revision_id = ? AND path <@ ?` でサブツリー一括取得。
4. 取得結果を `rendering` モジュールで XML/JSON（詳細版/簡易版）に再構築。

### 7.5 法令一覧 API の SQL イメージ

```sql
SELECT
  l.*, lr.*
FROM law_revision lr
JOIN law l ON l.law_id = lr.law_id
LEFT JOIN law_revision_category lrc ON lrc.law_revision_id = lr.law_revision_id
WHERE
  (:law_title IS NULL OR lr.law_title ILIKE '%' || :law_title || '%')
  AND (:law_num IS NULL OR l.law_num LIKE '%' || :law_num || '%')
  AND (:asof IS NULL OR lr.enforcement_period @> :asof::date)
  AND (:law_types::text[] IS NULL OR l.law_type = ANY(:law_types))
  AND (:category_cds::text[] IS NULL OR lrc.category_cd = ANY(:category_cds))
  AND (:repeal_statuses::text[] IS NULL OR lr.repeal_status = ANY(:repeal_statuses))
  AND (:promulgation_date_from IS NULL OR l.promulgation_date >= :promulgation_date_from)
  AND (:promulgation_date_to   IS NULL OR l.promulgation_date <= :promulgation_date_to)
ORDER BY <dynamic from `order` param>
LIMIT :limit OFFSET :offset;
```

## 8. 取り込みパイプライン

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Downloader      │ → │  XML Parser      │ → │  Loader (UPSERT) │
│ bulkdownload zip │   │ lxml.iterparse   │   │ law / law_revision│
└──────────────────┘   └──────────────────┘   │ law_xml / law_node│
                                              │ attached_file    │
                                              └──────────────────┘
                                                       ↓
                                              ┌──────────────────┐
                                              │ Search Indexer   │
                                              │ tsvector / pgroonga│
                                              └──────────────────┘
```

- 全件取り込み: `file_section=1` の Zip をローカルに展開 → 法令ごとに XML → DB UPSERT。
- 差分取り込み: 日次で `file_section=3&update_date=YYYYMMDD` を取得（過去 3 か月のみ参照可）。
- **UPSERT キー**は `law_revision_id`。同一 ID で `xml_sha256` が変化したら更新。
- **トランザクション境界**は「1 法令リビジョン = 1 トランザクション」を基本とし、失敗を局所化する。
- `law_node` の挿入は子要素が大量（数万行）になり得るので `COPY` を使う。

## 9. テスト方針

- **ユニット**: XML パーサのフィクスチャ（代表的法令 XML を 10〜20 件）、`elm` パスのパス変換、`enforcement_period` の計算。
- **統合**: testcontainers で Postgres を立て、Alembic で最新スキーマを適用 → 法令 1 件投入 → 全エンドポイントを叩いて JSON/XML 双方を比較。
- **互換性**: 実 e-Gov API のレスポンスを録画し、同じパラメータで本実装のレスポンスと差分比較するスナップショットテスト。

## 10. 未確定事項（要確認）

1. **添付ファイルの保存先**: DB BYTEA か、S3/MinIO か。
2. **全文検索エンジン**: pgroonga 採用可否（運用負荷・PGUS 拡張インストールの可否）。
3. **html/rtf/docx ファイル形式**の生成: e-Gov 同等の見た目を再現するか、簡易版で良いか。
4. **キャッシュ層**: CDN / Redis を間に挟むか。
5. **更新頻度**: 日次 1 回で十分か、もっと細かいか。
6. **既存改正法令の参照整合性**: `amendment_law_id` が `law` テーブルに存在しないケース（旧法令）の扱い。
