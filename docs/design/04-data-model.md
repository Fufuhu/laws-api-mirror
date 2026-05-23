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
  amendment_enforcement_date DATE
  amendment_enforcement_comment TEXT
  amendment_scheduled_enforcement_date DATE
  amendment_law_id  VARCHAR(15) REFERENCES amendment_law(amendment_law_id)
                                              -- 改正法令メタは amendment_law へ正規化（§4.5）
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

### 4.5 改正法令メタ（`amendment_law`）

`law_revision` から改正法令の属性を切り出し、独立テーブル `amendment_law` に正規化する。**`law` テーブルへの厳格 FK は持たず**、後から該当改正法令が `law` に投入された際に `linked_law_id` で紐付ける Lazy Linking 方式（方針 C、§11.8 で確定）。

```
TABLE amendment_law
  amendment_law_id          VARCHAR(15) PRIMARY KEY      -- 例: 506CO0000000161（law_id と同一形式の 15 桁）
  amendment_law_title       TEXT
  amendment_law_title_kana  TEXT
  amendment_law_num         TEXT
  amendment_promulgate_date DATE
  linked_law_id             VARCHAR(15) REFERENCES law(law_id) ON DELETE SET NULL
                                                          -- 後付け解決。NULL のままでも運用可能
  first_seen_at             TIMESTAMPTZ NOT NULL DEFAULT now()
  last_seen_at              TIMESTAMPTZ NOT NULL DEFAULT now()
  INDEX (linked_law_id)
  INDEX (amendment_promulgate_date)
```

設計ポイント:

1. **`law` への厳格 FK を避ける**: e-Gov のデータ整備対象（平成 29 年 4 月 1 日以降）外にある改正法令の `amendment_law_id` も受け入れる。`linked_law_id` は `law` への参照だが NULL 許容で、後から Lazy reconciliation ジョブが埋める。
2. **`law_revision.amendment_law_id` は `amendment_law` への FK**（NOT NULL を原則とする。新規制定 (`mission=New`) で改正元がない履歴の扱いは要確認: 自己参照プレースホルダを置くか NULL 許容にするか）。
3. **取り込み順序**: `law_revision` を投入する前に、`amendment_law` 行を UPSERT（プレースホルダ挿入を許容）。法令本体（`law`）の有無に依存しないので、被改正法令の取り込みが先行しても安全。
4. **API レスポンス組立**: `law_revision LEFT JOIN amendment_law LEFT JOIN law ON law.law_id = amendment_law.linked_law_id` の 2 段 LEFT JOIN で `amendment_law_id` / `amendment_law_title` / `amendment_law_num` を返却。e-Gov の `revision_info` 構造と 1:1 対応。
5. **Lazy reconciliation**（方針 D）: Procrastinate のジョブが `amendment_law` を走査し、`linked_law_id IS NULL` の行を `law` と再突合する。トリガは以下のいずれか:
   - 差分取り込みジョブの完了直後（chain）
   - 全件取り込みジョブの完了直後（chain）
   - 安全網としての `@periodic`（例: 日次 04:00）
   - 突合は `amendment_law.amendment_law_id = law.law_id` の単純な等価結合で、ヒットした行の `linked_law_id` を更新する。詳細は §11.8。
6. **`last_seen_at`**: 取り込みのたびに更新。長期間更新されない `amendment_law` 行は失効候補としてレビュー対象にする。

#### 4.5.1 多対多関係

1 つの改正法令が複数の被改正法令の複数履歴に紐づくのは、`law_revision.amendment_law_id` の N:1 関係で表現される。明示的な M2M テーブルは不要（`amendment_law` 1 つに対して `law_revision` 複数行）。


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

添付ファイル本体（JPG / PDF）は **オブジェクトストレージ** に保存し、DB にはメタデータとオブジェクトキーのみを持つ（DB の BYTEA には入れない）。本番（サーバー環境）は **AWS S3** を直接利用し、開発・CI・オンプレ評価環境は **SeaweedFS**（S3 互換）を利用する。Zip 一括取得・重複排除の方式は §11.2 で別途検討。

```
TABLE attached_file
  id                BIGSERIAL PRIMARY KEY
  law_revision_id   FK -> law_revision
  src               TEXT NOT NULL              -- 法令XML中の Fig.src（例: ./pict/M06SE065-001.jpg）
  content_type      TEXT                       -- image/jpeg, application/pdf
  byte_size         BIGINT
  sha256            BYTEA NOT NULL             -- 重複排除キー兼整合性チェック
  object_key        TEXT NOT NULL              -- オブジェクトストレージ上のキー（例: attachments/sha256/ab/cd.../bytes）
  source_updated_at TIMESTAMPTZ
  UNIQUE (law_revision_id, src)
  INDEX (sha256)
```

設計ポイント:

- バイナリは `object_key` 経由で取得する。同一 `sha256` は 1 オブジェクトに集約し、複数の `attached_file` 行から参照可能（重複排除）。
- バケット名・エンドポイントはアプリ設定（環境変数）から解決し、DB に永続化しない。AWS S3 ／ S3 互換ソフトの切替はエンドポイント URL の差し替えで完結する。
- `law_node.fig_src`（§4.7）と `attached_file(law_revision_id, src)` で join し、`/attachment/{law_revision_id}?src=...` に応答する。

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

