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

