## 5. インデックス／全文検索戦略

- 法令メタの絞り込み（種別・分類・公布日範囲）は B-tree 複合インデックスで十分。
- `asof` クエリは `enforcement_period @> :asof` + GIST。
- **キーワード検索エンジンは `pg_bigm` + `tsvector` のハイブリッド構成で確定**。両者の得意領域が直交しており、e-Gov 仕様（ワイルドカード必須・自然文も来る・ハイライト必須）を単独エンジンで満たすのは過不足が生じるため。
- 検索ヒット位置（`position` フィールド）は **`law_node` 単位**で返すため、`law_node.path_text` をそのまま返却可能。

### 5.1 採用方針と根拠

| エンジン | 主担当 | 理由 |
|---|---|---|
| **pg_bigm** | ワイルドカード `*` `?` を含む式、1〜2 文字トークン、固有名詞・引用条文表記など記号入り、部分一致 | bigram GIN により `LIKE '%...%'` を高速化。形態素解析の未知語問題を回避できる。e-Gov の検索式仕様（ワイルドカード＋AND/OR/NOT）と直接マッピング可能 |
| **tsvector (textsearch_ja + MeCab)** | 自然文の語形変化を含むキーワード、`ts_headline` による前後文脈ハイライト、将来のスコアリング (`ts_rank`) | 活用形（「行う／行った／行います」）を語幹で拾える。`ts_headline` は前後文の切り出しに最適 |

不採用とした候補:

- **pgroonga**: 機能としては魅力的だが、マネージド PostgreSQL（AWS RDS/Aurora、Cloud SQL、Azure Database 等）の標準サポートに乗っていない環境が多く、移行リスクを抱える。pg_bigm + tsvector で機能要件を満たせる見込みのため不採用。
- **pg_bigm 単独**: ハイライト座標を自前計算でき軽量だが、`ts_headline` 相当の前後文脈生成や自然文の語形吸収を保留することになる。将来要件追加時の手戻りを避けるため、初期から tsvector を併設する。
- **tsvector 単独**: e-Gov 仕様のワイルドカード `*`/`?` と非互換。1 文字ワイルドカード（`第?条` など）も拾えない。

### 5.2 ルーティング戦略

`search.query_parser` が検索式を AST 化し、`engine_adapter` がエンジンへ振り分ける。両エンジンを単一クエリ内で組み合わせる場合もあるため、次の 2 方式を併用する。

- **(α) 振り分け方式**（既定）: AST にワイルドカード or 短トークンが含まれる場合は **pg_bigm 経路**。それ以外は **tsvector 経路**。e-Gov の `*`/`?` と `tsvector` は本来非互換のため、ワイルドカード混入時は pg_bigm を強制する。
- **(β) 二段検索方式**（必要時）: 1 段目で pg_bigm により候補ノードを粗く絞り、2 段目で tsvector により再評価＋ `ts_headline` でハイライト整形。ハイライトの質を最優先する API リクエスト（`highlight_tag` 指定時など）に適用。

両方式を `engine_adapter` 内のストラテジとして実装し、リクエスト種別で切り替える。

### 5.3 スキーマ

検索対象は `law_node.text_plain` 列。両エンジンのインデックスを併設する。

```sql
CREATE EXTENSION IF NOT EXISTS pg_bigm;
-- textsearch_ja（PGroonga ではなく標準 tsvector + MeCab トークナイザを採用）の準備は環境構築側で実施

-- law_node.text_plain は §4.7 で既存

-- tsvector は STORED 生成列で自動同期（トリガ不要）
ALTER TABLE law_node ADD COLUMN text_search tsvector
  GENERATED ALWAYS AS (to_tsvector('japanese', coalesce(text_plain, ''))) STORED;

-- 両 GIN インデックスを併設
CREATE INDEX law_node_text_bigm_idx
  ON law_node USING gin (text_plain gin_bigm_ops);
CREATE INDEX law_node_text_search_idx
  ON law_node USING gin (text_search);
```

`japanese` テキスト検索設定は MeCab 連携のトークナイザを前提とする（`textsearch_ja` または `pg_textsearch_ja` 系拡張）。CI / 本番 DB の構築スクリプトでセットアップする。

### 5.4 トレードオフと運用上の留意点

- **書き込みコスト**: GIN インデックスが 2 本のため、取り込み時の更新コストは pg_bigm 単独に比して **約 2 倍**。XML 一括取り込み時は `pg_bigm` と `tsvector` の維持で I/O が増えるが、`COPY` 後に `REINDEX CONCURRENTLY` でまとめ直す運用も検討。
- **ストレージ**: bigm は本文長の 0.5〜1 倍、tsvector は語彙数依存で 0.3〜0.5 倍。法令本文全体（数 GB クラス）でも許容範囲。
- **辞書メンテ**: MeCab/ipadic（または unidic）の更新運用が発生。辞書バージョンと `tsvector` カラムの再生成は Alembic リビジョンで管理。
- **クエリ層の責務**: `query_parser → engine_adapter` の責務分離を必ず守り、API ハンドラには **engine 中立のインタフェース**だけを露出する。将来 pgroonga 等への切替が必要になった場合のリスクを下げる。

### 5.5 検索式と SQL 変換の例

```
入力: 個人情報 !マイナンバー
AST:   AND( TERM("個人情報"), NOT(TERM("マイナンバー")) )
振り分け: tsvector 経路（ワイルドカードなし、自然文）

SQL（イメージ）:
  SELECT n.id, n.law_revision_id, n.path_text,
         ts_headline('japanese', n.text_plain,
                     to_tsquery('japanese', '個人情報 & !マイナンバー'),
                     'StartSel=<span>, StopSel=</span>') AS snippet
    FROM law_node n
   WHERE n.text_search @@ to_tsquery('japanese', '個人情報 & !マイナンバー')
   ORDER BY n.law_revision_id, n.id
   LIMIT :limit OFFSET :offset;
```

```
入力: 第*条 (情報|個人)
AST:   AND( WILDCARD("第*条"), OR(TERM("情報"), TERM("個人")) )
振り分け: pg_bigm 経路（ワイルドカードあり）

SQL（イメージ）:
  SELECT n.id, n.law_revision_id, n.path_text, n.text_plain
    FROM law_node n
   WHERE n.text_plain LIKE '%第%条%'                  -- pg_bigm が GIN を効かせる
     AND (n.text_plain LIKE '%情報%' OR n.text_plain LIKE '%個人%')
   ORDER BY n.law_revision_id, n.id
   LIMIT :limit OFFSET :offset;

-- 実際の `第*条` のパターン照合（* = 0 文字以上）は正規表現で再評価:
--   AND n.text_plain ~ '第[^条]*条'
-- bigm で粗く絞った後の二次フィルタとして適用する。
```

ハイライト位置（`<span>` で囲うオフセット）は、

- tsvector 経路: `ts_headline` の出力をそのまま使用。
- pg_bigm 経路: `re.finditer` 等で Python 側計算、または `regexp_matches` で SQL 側計算。

いずれの経路でも、レスポンスは e-Gov 互換の `sentences[].position` (`law_node.path_text`) ＋ `sentences[].text`（ハイライト済み）で返す。
