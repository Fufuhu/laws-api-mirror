# laws-api-mirror 設計書

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

### 4.0 法令標準XMLスキーマ v3 からの設計上の含意

[`XMLSchemaForJapaneseLaw_v3.xsd`](https://laws.e-gov.go.jp/file/XMLSchemaForJapaneseLaw_v3.xsd) を精読した結果、データモデル上で以下の点が確定する:

1. **`Law` ルート属性**: `Era` (Meiji/Taisho/Showa/Heisei/Reiwa), `Year` (positiveInteger), `Num` (positiveInteger), `PromulgateMonth`, `PromulgateDay`, `LawType` (Constitution/Act/CabinetOrder/ImperialOrder/MinisterialOrdinance/Rule/Misc), `Lang` (ja/en) はすべて **必須 or 任意属性**として XML に明示。API メタ（`law_info`）と重複するが、**`law_xml` 取り込み時の整合性チェック**に使う。
2. **構造階層の choice 構造**: `MainProvision` は `Part+ | Chapter+ | Section+ | Article+ | Paragraph+` のいずれか（法令ごとに depth が違う）。`Part > Chapter > Section > Subsection > Division > Article > Paragraph > Item > Subitem1 > … > Subitem10` の **9 段 + 5 段** の階層が起こり得るが、すべての段が常に出るわけではない。
3. **Num 属性の型混在**:
   - `Article.Num`, `Item.Num`, `Subitem*.Num`, `Class.Num` は **任意文字列**（"21_2", "21_2_3" のような枝番表記を許容）
   - `Paragraph.Num` は **xs:positiveInteger**（整数）
   - `Sentence.Num`, `Column.Num`, `AppdxTable.Num` も positiveInteger
4. **`Subitem` は 10 段**: `Subitem1` から `Subitem10` まで（旧設計の "Subitem1..5" は誤り）。各段に `*Title?`, `*Sentence`, 子 `Subitem(N+1)*`, `TableStruct|FigStruct|StyleStruct|List` を持つ。
5. **`Sentence` は mixed content**: テキストに加え `Line`, `QuoteStruct`, `ArithFormula`, `Ruby`, `Sup`, `Sub` がインラインで混在。属性は `Num`, `Function` (main/proviso), `Indent` (Paragraph/Item/Subitem1..10), `WritingMode` (vertical/horizontal default vertical)。これらは **検索結果ハイライトと縦書きレンダリングに必要**。
6. **`QuoteStruct` は `type="any"`**: 任意XML埋め込み（被改正法令断片など）。**子要素を分解せず raw XML として保持**するのが現実解。
7. **`SupplProvision` 属性**: `Type` (New/Amend), `AmendLawNum`, `Extract`。API ドキュメントで言及されている `omit_amendment_suppl_provision=true` の判定はこの `Type="Amend"` で行う。
8. **`AmendProvision` / `NewProvision`**: 法令の改正条文を表現する要素で、内部に **構造ノードを丸ごとネスト**できる（Part, Chapter, Article, Paragraph, ... さらには AppdxTable まで）。再帰スキーマで設計する必要がある。
9. **`TableColumn`**: `rowspan`, `colspan`, `BorderTop/Bottom/Left/Right` (solid/none/dotted/double), `Align`, `Valign` を持ち、内部にも構造要素 (Article/Paragraph 等) を入れられる。**表は単なるテキストではなく木構造**。
10. **`LawTitle` 属性**: `Kana`, `Abbrev`, `AbbrevKana` — `revision_info.law_title_kana` / `abbrev` の出所はここ。
11. **`Article` / `Part` / `Chapter` / `Section` / `Subsection` / `Division` / `Item` / `Subitem*`** には `Delete` と `Hide` のブール属性がある（削除・非表示扱い）。`Paragraph` には `OldStyle`, `OldNum`, `Hide`。
12. **`Fig` は `src` のみの葉要素**（`FigStruct` でラップされる）。`AppdxTable.Num` は任意（番号なし別表あり）。
13. **`TOC` は独立構造**: `TOCLabel?`, `TOCPreambleLabel?`, `TOCPart+ | TOCChapter+ | TOCSection+ | TOCArticle+`, `TOCSupplProvision?`, `TOCAppdxTableLabel*`。本文 (`MainProvision`) と別系統。

これらを単一の `law_node` テーブルに **属性は `JSONB` ＋ 重要属性は専用カラム化**で格納する。

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

法令 XML の全要素を **単一テーブル `law_node` にツリー格納**する。XSD v3 は 80 以上の要素を定義するため、ENUM ではなく **lookup テーブル `node_kind`** に切り出し、XSD バージョンアップに耐えうる設計とする。

```
TABLE node_kind                    -- 参照テーブル（XSD の全要素を初期データで投入）
  kind          TEXT PRIMARY KEY   -- 'Law','LawBody','MainProvision','Article','Paragraph',...
  category      TEXT NOT NULL      -- 'structure'|'block'|'sentence'|'inline'|'table'|'fig'|'amend'|'toc'|'appdx'|'meta'
  is_container  BOOLEAN NOT NULL   -- 子ノードを持ち得るか
  description   TEXT
```

XSD v3 で定義される **構造系の主要 `kind`**（カテゴリ別、抜粋）:

| category | kind の例 |
|---|---|
| meta | `Law`, `LawNum`, `LawBody`, `LawTitle`, `EnactStatement` |
| toc | `TOC`, `TOCLabel`, `TOCPreambleLabel`, `TOCPart`, `TOCChapter`, `TOCSection`, `TOCSubsection`, `TOCDivision`, `TOCArticle`, `TOCSupplProvision`, `TOCAppdxTableLabel` |
| structure | `Preamble`, `MainProvision`, `Part`, `Chapter`, `Section`, `Subsection`, `Division` |
| structure | `Article`, `ArticleTitle`, `ArticleCaption` |
| block | `Paragraph`, `ParagraphCaption`, `ParagraphNum`, `ParagraphSentence` |
| block | `Item`, `ItemTitle`, `ItemSentence` |
| block | `Subitem1..10`, `Subitem1Title..Subitem10Title`, `Subitem1Sentence..Subitem10Sentence` |
| block | `Class`, `ClassTitle`, `ClassSentence` |
| sentence | `Sentence`, `Column`, `List`, `ListSentence`, `Sublist1`, `Sublist1Sentence`, `Sublist2`, `Sublist2Sentence`, `Sublist3`, `Sublist3Sentence` |
| inline | `Line`, `QuoteStruct`, `ArithFormula`, `ArithFormulaNum`, `Ruby`, `Rt`, `Sup`, `Sub` |
| table | `TableStruct`, `TableStructTitle`, `Table`, `TableRow`, `TableColumn`, `TableHeaderRow`, `TableHeaderColumn` |
| fig | `FigStruct`, `FigStructTitle`, `Fig` |
| fig | `StyleStruct`, `StyleStructTitle`, `Style`, `FormatStruct`, `FormatStructTitle`, `Format`, `NoteStruct`, `NoteStructTitle`, `Note` |
| structure | `Remarks`, `RemarksLabel`, `SupplNote`, `RelatedArticleNum`, `ArticleRange` |
| supplement | `SupplProvision`, `SupplProvisionLabel`, `SupplProvisionAppdxTable`, `SupplProvisionAppdxTableTitle`, `SupplProvisionAppdxStyle`, `SupplProvisionAppdxStyleTitle`, `SupplProvisionAppdx` |
| appdx | `AppdxTable`, `AppdxTableTitle`, `AppdxStyle`, `AppdxStyleTitle`, `AppdxFormat`, `AppdxFormatTitle`, `Appdx`, `AppdxFig`, `AppdxFigTitle`, `AppdxNote`, `AppdxNoteTitle` |
| amend | `AmendProvision`, `AmendProvisionSentence`, `NewProvision` |

```sql
TABLE law_node
  id                BIGSERIAL PRIMARY KEY
  law_revision_id   VARCHAR(64)   NOT NULL REFERENCES law_revision
  parent_id         BIGINT REFERENCES law_node(id) ON DELETE CASCADE
  kind              TEXT          NOT NULL REFERENCES node_kind(kind)
  ordinal           INTEGER       NOT NULL                     -- 同一親内での 0 始まり順序
  -- 番号（Num 属性）
  num_text          TEXT                                       -- XML の Num 属性をそのまま（"21", "21_2" など）
  num_int           INTEGER                                    -- 主要番号（"21_2"→21）。Paragraph 等の純整数 Num も同居
  num_branches      INTEGER[]                                  -- ["21","2"]→{21,2}。SQL ソート/比較用
  -- タイトル・キャプション
  caption           TEXT                                       -- ArticleCaption / ParagraphCaption
  title             TEXT                                       -- ArticleTitle / *Title 群
  label             TEXT                                       -- SupplProvisionLabel / RemarksLabel / TOCLabel
  -- 構造系の属性（XSD 由来）
  delete_flag       BOOLEAN       NOT NULL DEFAULT false       -- Article/Part/Chapter/.../Item/Subitem* の Delete
  hide_flag         BOOLEAN       NOT NULL DEFAULT false       -- 同 Hide
  old_style         BOOLEAN                                    -- Paragraph.OldStyle
  old_num           BOOLEAN                                    -- Paragraph.OldNum
  extract_flag      BOOLEAN                                    -- MainProvision/SupplProvision.Extract
  -- Sentence 専用カラム（検索/レンダリングで頻用するため別カラム）
  sentence_function TEXT                                       -- 'main' | 'proviso'
  sentence_indent   TEXT                                       -- 'Paragraph'|'Item'|'Subitem1'..'Subitem10'
  writing_mode      TEXT                                       -- 'vertical'|'horizontal'
  -- SupplProvision 専用
  suppl_type        TEXT                                       -- 'New' | 'Amend'
  amend_law_num     TEXT
  -- Fig 専用
  fig_src           TEXT                                       -- attached_file への外部キー検索キー（src は ./pict/... 相対）
  -- TableColumn 専用（疎なカラム）
  rowspan           INTEGER
  colspan           INTEGER
  border_top        TEXT
  border_bottom     TEXT
  border_left       TEXT
  border_right      TEXT
  align             TEXT                                       -- left/center/right/justify
  valign            TEXT                                       -- top/middle/bottom
  -- レア属性 / インライン要素 (Ruby Rt, Sentence の Num 以外の属性) の格納
  attrs             JSONB         NOT NULL DEFAULT '{}'        -- 他の XML 属性すべて
  -- 中身（葉ノードの XML 断片）
  raw_xml           XML                                        -- Sentence の混在内容、QuoteStruct の任意 XML、ArithFormula 等を原文保持
  text_plain        TEXT                                       -- インライン要素を剥がしたプレーンテキスト（検索とハイライト用）
  -- パス（elm パラメータの解決用）
  path              LTREE         NOT NULL                     -- 例: MainProvision.Article_21.Paragraph_3.Item_2
  path_text         TEXT          NOT NULL                     -- 例: "MainProvision-Article_21-Paragraph_3-Item_2"
  depth             SMALLINT      NOT NULL                     -- 0=Law
  -- 検索
  text_search       TSVECTOR                                   -- 日本語 tsvector（pgroonga 採用時は別カラム pgroonga_text）
  UNIQUE (law_revision_id, path)
  INDEX USING GIST (path)
  INDEX (law_revision_id, parent_id, ordinal)
  INDEX (law_revision_id, kind, num_int)
  INDEX USING GIN (text_search)
  INDEX USING GIN (attrs jsonb_path_ops)
```

設計上のポイント:

1. **隣接リスト + ltree**: `parent_id` で厳密ツリー、`path` (`ltree`) で `elm` の高速検索。`elm=MainProvision-Article_21-Paragraph_3` は `path <@ 'MainProvision.Article_21.Paragraph_3'` で O(log N) サブツリー取得。
2. **`num_branches INTEGER[]`** で枝番（"21_2_3"→{21,2,3}）を表現し、`ORDER BY num_branches` で **辞書順ではなく数値順**に並ぶ。`num_int` は最上位番号で簡易ソート・絞り込み用。
3. **`Paragraph.Num` は positiveInteger、`Article.Num`/`Item.Num`/`Subitem*.Num` は文字列**。両者を `num_text` (原文) + `num_int`/`num_branches` (派生) で受ける統一カラム設計とする。
4. **頻用属性は専用カラム**にして検索性能と可読性を確保（Sentence 系・SupplProvision 系・TableColumn 系・Fig 系）。それ以外の XSD 属性（Ruby の振り仮名、ArithFormula のキャプション等）は `attrs JSONB` に追い込み、GIN インデックスで横断検索可能にしておく。
5. **インライン要素は分解しない**: `Ruby`/`Sup`/`Sub`/`Line`/`QuoteStruct`/`ArithFormula` は **Sentence の `raw_xml` に保持**し、`text_plain` でプレーン化して検索に供する。これにより XML 復元時に元の混在内容を完全再現できる。
6. **`QuoteStruct` は `xs:any`** のため、子要素を `law_node` 化せず raw XML の塊として保持するのが現実解。ただし内部に被改正法令断片が入る場合があるため、別 `quote_extract` テーブルで関連法令 ID を抽出記録するオプションを残す。
7. **AppdxTable / AppdxFig / Fig は `attached_file` と接続**: `law_node.fig_src` に `Fig.src` 値（`./pict/M06SE065-001.jpg` 等）を入れ、`attached_file(law_revision_id, src)` に join できる。
8. **AmendProvision / NewProvision は通常ノードとして再帰格納**: XSD で再帰スキーマになっているため、`law_node` に通常通り格納すれば自然にツリーが組める。検索時には `kind='AmendProvision'` でフィルタ可能。`omit_amendment_suppl_provision=true` は `path` に `SupplProvision` を含み `suppl_type='Amend'` のサブツリーを除外する。

### 4.7.1 `elm` パスの組み立て規則

`law_node.path` は **ltree ラベル** で構築する。ラベルは以下の規則:

- `Num` 属性なしの要素: `kind` そのまま（例: `MainProvision`, `Preamble`, `TOC`）。
- `Num` 属性ありの要素: `kind_Num`（例: `Article_21`, `Paragraph_3`, `Item_2`, `Subitem1_1`）。
- 枝番は `_` 区切りで保持: `Article_21_2`（XML の `Num="21_2"`）。
- `[1]` 形式（API ドキュメント例の `Preamble[1]`, `SupplProvision[1]`）は **`ordinal` カラム**で表現し、外向け文字列としては `kind` のあと `[ordinal+1]` を組み立てる。
- ltree のラベル制約（英数字とアンダースコア）を満たすため、枝番は `_` 区切りに正規化。
- 外向け表記（`path_text`）は **`-` 区切り** で API ドキュメント表記に揃える。

```
内部 ltree:      MainProvision.Article_21_2.Paragraph_3.Item_2.Subitem1_1
外向け path_text: MainProvision-Article_21_2-Paragraph_3-Item_2-Subitem1_1
```

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
- キーワード検索エンジンは未確定。以下の 3 候補をサイドバイサイドで併記し、PoC で比較する。検索のヒット位置（`position` フィールド）は **`law_node` 単位**で返すため、いずれの方式でも `law_node.path_text` をそのまま返却可能。

### 5.1 全文検索エンジン比較

| 観点 | (A) pg_bigm | (B) pgroonga | (C) tsvector + textsearch_ja (MeCab) |
|---|---|---|---|
| 索引方式 | 2-gram（bigram）GIN | N-gram + 形態素 | 形態素 |
| 部分一致 `LIKE '%...%'` 加速 | ◎ | ◎ | △（形態素単位） |
| ワイルドカード `*` / `?` | ◎ LIKE/正規表現に直接マッピング | ○ | △ |
| AND / OR / NOT | ◎ LIKE の論理結合 | ◎ クエリ言語 | ◎ `tsquery` |
| 1 文字クエリ | × フルスキャンへフォールバック | ○ | ○ |
| ハイライト座標 | × 自前算出（`re.finditer` 等） | ◎ `pgroonga_match_positions_byte` | ○ `ts_headline` |
| スコアリング | × | ◎ | ◎ |
| 辞書メンテ | 不要 | 不要 | 必要（MeCab/ipadic） |
| 拡張入手性 | ◎ 主要マネージドPG（AWS RDS/Aurora/Cloud SQL/Azure 等）で利用可 | △ 利用可能環境が限定 | ◎ 標準 |
| 運用負荷 | 低 | 中 | 高 |

### 5.2 採用判断のポイント

- **e-Gov 仕様との親和性**: キーワード API は「部分一致＋ワイルドカード＋AND/OR/NOT」が中心で、スコアリングは使われない（`order` は `law_info`/`revision_info` のフィールド指定）。**(A) pg_bigm** の特性とよく噛み合う。
- **ハイライト**: e-Gov のレスポンスはヒット部分を `<span>` で囲うだけの単純仕様。pg_bigm の場合は `law_node.text_plain` に対して Python 側で `re.finditer` してオフセットを計算すれば十分（条文単位＝通常 100〜数百文字なので軽い）。本格的な `ts_headline` 相当が必要なら (B) を選ぶ。
- **1 文字クエリ**: e-Gov 仕様の `第?条` のように 1 文字ワイルドカードを含む式でも、固定文字部分（"第", "条"）が 2 文字以上あれば bigram で絞り込めるため、pg_bigm でも実害は小さい想定。ただし PoC で性能確認が必要。
- **環境依存**: 本番運用がマネージド DB 前提なら (A)/(C) が安全。自前 Postgres を立てるなら (B) も選択肢。

### 5.3 共通設計

検索対象は `law_node.text_plain` 列。採用エンジンに応じて以下のカラム／インデックスを追加する。

```sql
-- (A) pg_bigm 採用時
CREATE EXTENSION IF NOT EXISTS pg_bigm;
CREATE INDEX law_node_text_bigm_idx
  ON law_node USING gin (text_plain gin_bigm_ops);

-- (B) pgroonga 採用時
CREATE EXTENSION IF NOT EXISTS pgroonga;
CREATE INDEX law_node_text_pgroonga_idx
  ON law_node USING pgroonga (text_plain);

-- (C) tsvector 採用時
ALTER TABLE law_node ADD COLUMN text_search tsvector;
CREATE INDEX law_node_text_search_idx
  ON law_node USING gin (text_search);
-- text_search はトリガで更新（to_tsvector('japanese', text_plain)）
```

検索式（AND/OR/NOT、ワイルドカード）は `search.query_parser` モジュールで AST 化し、採用エンジンに応じた SQL/関数呼び出しへ変換する責務分離とする。エンジン差し替えが API 層に漏れない構造にしておく。

### 5.4 ハイブリッド構成（pg_bigm + tsvector）

pg_bigm と tsvector は得意領域が直交しているため、両者を **同じ `law_node` に対して併存させ、クエリ種別でルーティング**する構成も有力（要 PoC）。

**得意領域の対応**

| クエリ種別 | 担当 | 理由 |
|---|---|---|
| ワイルドカード `*` `?` 含む | pg_bigm | tsvector は形態素境界で切るため破綻 |
| 1〜2 文字トークン混じり | pg_bigm | tsvector は語彙単位 |
| 引用条文表記・固有名詞・記号入り | pg_bigm | MeCab の未知語分割を回避 |
| 自然文の語形変化 | tsvector | 活用形を語幹に正規化 |
| ハイライト＋前後文脈 | tsvector (`ts_headline`) | bigm 単独では自前計算 |
| スコアリング (`ts_rank`) | tsvector | e-Gov 仕様では未使用だが拡張余地 |

**ルーティング戦略**

- **(α) 振り分け方式**: `search.query_parser` で AST 化した時点でワイルドカード or 短トークンの有無を判定し、**ワイルドカード=pg_bigm 強制**、それ以外は tsvector を優先。e-Gov の `*`/`?` と `tsvector` は本来非互換のため安全側に倒す。
- **(β) 二段検索方式**: 1 段目で pg_bigm により粗く候補ノードを絞り（false positive 許容）、2 段目で tsvector により再評価＋ハイライト＋並び順を確定。精度優先なら (β)、レイテンシ優先なら (α)。

**スキーマ追記**

```sql
CREATE EXTENSION IF NOT EXISTS pg_bigm;
-- text_plain は §4.7 で既存
ALTER TABLE law_node ADD COLUMN text_search tsvector
  GENERATED ALWAYS AS (to_tsvector('japanese', coalesce(text_plain, ''))) STORED;
CREATE INDEX law_node_text_bigm_idx
  ON law_node USING gin (text_plain gin_bigm_ops);
CREATE INDEX law_node_text_search_idx
  ON law_node USING gin (text_search);
```

**トレードオフ**

- 書き込みコスト: GIN インデックスが 2 本になるため取り込み時の更新コストは **約 2 倍**。
- ストレージ: bigm は本文長の 0.5〜1 倍、tsvector は語彙数依存で 0.3〜0.5 倍。法令本文全体で数 GB ならいずれも許容範囲。
- 辞書メンテ: MeCab/ipadic（または unidic）の更新運用が発生。避けたい場合は単独構成（pg_bigm のみ）にフォールバック可能。
- クエリ層の複雑度: `query_parser` の責務が増える。エンジンアダプタを差し替え可能な形にし、ハイブリッド適用は段階導入とする。

**段階導入の指針**

1. **PoC: pg_bigm 単独**で e-Gov 仕様を満たせるか検証（スコアリング不要・ワイルドカード必須なので有力）。
2. ハイライトの質や自然語検索の精度が不足するようなら **tsvector を追加投入**してハイブリッド化。
3. 設計上は最初から `query_parser → engine_adapter` の責務分離を確立しておき、(1)→(2) の移行で API 層を変更しないこと。

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
2. **全文検索エンジン**: §5.1 の 3 候補（pg_bigm / pgroonga / tsvector+MeCab）から PoC で選定。マネージド DB の拡張サポート状況・1 文字クエリの頻度・ハイライト要件の重さで決定。
3. **html/rtf/docx ファイル形式**の生成: e-Gov 同等の見た目を再現するか、簡易版で良いか。
4. **キャッシュ層**: CDN / Redis を間に挟むか。
5. **更新頻度**: 日次 1 回で十分か、もっと細かいか。
6. **既存改正法令の参照整合性**: `amendment_law_id` が `law` テーブルに存在しないケース（旧法令）の扱い。
7. **`QuoteStruct` の取り扱い深度**: `xs:any` の中身まで構造分解するか、不透明 XML として保持するか。検索ヒット位置の精度に影響。
8. **`AmendProvision` ツリーのレンダリング**: 改正条文を `law_node` に通常ノードとして格納するが、`/law_data` レスポンスで「改正部分を畳む」UI 要件があるか。
9. **JSON（詳細版/簡易版）の差分**: `json_format=light` 時に「インライン要素はテキスト埋め込み、属性は `AmendLawNum`/`Extract`/`Paragraph.Num` のみフィールド化」というルールを `rendering` 層で正確に再現する必要がある。
10. **XSD バージョン管理**: 法令標準 XML スキーマがバージョンアップした際の `node_kind` 追加運用（Alembic でマスタ追加リビジョンを作る方針で良いか）。
