## 11. 残課題検討

§10「未確定事項」が「採用するか / しないか」レベルの意思決定リストであるのに対し、本章は **採用は確定しているが、具体運用や細部詰めが必要なテーマ**を扱う。実装フェーズ前に各項目で 1〜2 ページ規模の検討ノートを別途作成する想定。

### 11.1 MeCab 辞書の選定とバージョン管理

§5 で `tsvector` 経路に MeCab トークナイザを採用済み。以下を別途検討する。

#### 検討事項

1. **辞書の選定**
   - 候補: `ipadic` / `ipadic-NEologd` / `unidic` / カスタム辞書（ユーザ辞書併用）
   - 法令テキストの特性（新語より固有名詞・行政用語・条文表記が中心、組織名は更新が必要）を踏まえ、**ベースは `ipadic`、組織名や新法名は user dict で補強**するのが第1候補。
   - NEologd は更新停止リスクと辞書サイズ（数百 MB）が課題のため見送り候補。
2. **PostgreSQL からの呼び出し方式**
   - (A) **`textsearch_ja` 等の拡張**で `to_tsvector('japanese', ...)` を直接動かす。
   - (B) **アプリ側（Python `fugashi`）でトークナイズし空白区切りに変換**してから `to_tsvector('simple', ...)` に渡す。
   - (B) のほうが辞書管理を Python レイヤに閉じ込められて運用が容易（Docker イメージで完結、CI/本番のバージョン一致を保証しやすい）。第1候補。
3. **バージョン固定**
   - 採用辞書のバージョン（例: `ipadic 2.7.0-20070801`）を **Alembic リビジョン**または専用テーブル `text_index_meta(dict_name, dict_version, indexed_at)` に記録。
   - 辞書を更新したら **`text_search` 列の再生成 + `REINDEX CONCURRENTLY`** を実施するマイグレーションを発行。
4. **再生成の影響範囲**
   - `law_node.text_search` は `GENERATED ALWAYS AS ... STORED` 列にすると、トークナイザ実装の変更時に **全行再生成**が必要になる（数千万行クラス）。
   - 代替: STORED にせず、取り込み時に Python トークナイザの出力を `text_search` に明示書き込みする方式。バッチで再構築する SQL を別途用意。
5. **ユーザ辞書の運用**
   - 法令固有の組織名・略称（「個人情報保護委員会」「デジタル庁」など）をユーザ辞書に追加するワークフロー。
   - 追加 → 辞書ビルド → 検証 → 本番反映の手順を文書化。
6. **辞書差異によるデバッグ困難への対応**
   - クエリ実行時のトークナイズ結果を `EXPLAIN`/ログに残し、「以前は引けたのに今は引けない」事象を再現できるようにする。

#### アウトプット

- 辞書選定の意思決定記録（ADR）
- `docker/postgres/` 配下の辞書同梱 Dockerfile
- 辞書更新時の Runbook（手順書）
- `text_index_meta` テーブルの DDL

### 11.2 添付ファイルストレージ

**確定方針**:

- 添付ファイル（JPG / PDF）の本体は **オブジェクトストレージ**に保存する。`law_node.fig_src` および `attached_file` テーブルからオブジェクトキーで参照する形とし、PostgreSQL の BYTEA には保存しない（DB 肥大化を避けるため）。
- **環境別の使い分け**:
  - **サーバー（本番）環境**: **AWS S3** をそのまま利用する。マネージドサービスの可用性・耐久性・運用負荷の低さを優先。
  - **開発・CI・オンプレ評価環境**: **[SeaweedFS](https://github.com/seaweedfs/seaweedfs)** を S3 互換バックエンドとして利用する。選定理由:
    1. **S3 API 互換が公式に謳われている**: `weed s3` サブコマンドで S3 互換ゲートウェイが立ち上がり、AWS SDK (boto3 / aioboto3) からエンドポイント URL の差し替えだけで利用できる。
    2. **軽量**: シングルバイナリで配布され、master / volume / filer / s3 の役割を必要に応じて分離可能。小〜中規模での運用負荷が低い。Ceph RGW のようなクラスタ構築コストがかからず、本プロジェクトの想定データ量（数百 GB クラス）に過不足ない。
    3. **署名付き URL に対応**: AWS S3 互換の Pre-signed URL（GET / PUT）をサポートしており、現時点で CDN 配信は対象外ながら、将来必要になった際に追加実装が容易。
    4. **大量小ファイルへの強さ**: 法令添付ファイルは JPG / PDF が中心で件数が多くなるため、SeaweedFS の小ファイル最適化（Haystack 由来の設計）が適合。
- **MinIO は採用しない**: 2025 年に主要機能の Community Edition からの除外などコミュニティ向け開発が停滞し、事実上のパブリックアーカイブ状態にあるため。
- **現時点で検討しないこと**: CDN 経由配信および署名付き URL の発行ポリシー（必要になった時点で追加検討）。S3 / SeaweedFS いずれも機能を備えているため、設計上の障壁はない。

#### 検討事項

1. **エンドポイント切替の実装**
   - 本番は AWS S3、開発・CI・オンプレ評価環境は SeaweedFS。`boto3` / `aioboto3` のエンドポイント URL・認証情報・リージョンを環境変数から解決し、コードを切り替えずに済む構成にする。
   - 設定例: `S3_ENDPOINT_URL`（AWS S3 利用時は未設定）、`S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`。
2. **オブジェクトキーの命名**
   - 例: `attachments/{law_revision_id}/{src_basename}` または `attachments/sha256/{xx}/{xxxx...}` のいずれか。
   - 同一画像が複数法令で参照される重複排除と整合する形を採用するため、**`attachments/sha256/{先頭2桁}/{残り}`** をベースに、`attached_file` 行で law_revision との対応を取る方式を第1候補とする。
3. **`/attachment/{law_revision_id}` で `src` 未指定時の Zip 一括取得**
   - オンデマンド zipping（ストリーミング応答）か、取り込み時に事前生成して S3 に置くか。
   - 大きな法令だと数十〜数百ファイルになる可能性があるため、性能要件次第で事前生成を選択。
4. **バイナリのハッシュ重複排除**
   - `attached_file.sha256` をオブジェクトキーの一部に使い、同一バイナリは 1 オブジェクトに集約。
   - 法令履歴 ⇄ オブジェクトの関係は `attached_file` テーブルでメタを管理。
5. **最大ファイルサイズ・総量の見積もり**
   - PDF / JPG の分布調査を実施し、AWS S3 のストレージクラス（Standard / IA / Glacier）の使い分けを決定。SeaweedFS 側は同等容量のローカルストレージを確保。
6. **SeaweedFS の運用設計（開発・評価環境向け）**
   - シングルノード構成（小規模）／クラスタ構成（冗長化）の判断。本番は AWS S3 のため、SeaweedFS は基本的にシングルノードで十分。
   - レプリケーション設定 (`-replication=001` 等) とバックアップ戦略は評価用途では簡略化。
   - master / volume / s3 ゲートウェイのプロセス分離と監視（Prometheus exporter あり）。
   - Docker Compose でアプリ・PostgreSQL とまとめて立ち上がるよう同梱。

#### アウトプット

- ストレージレイアウト仕様（オブジェクトキー、メタデータ、AWS S3 のライフサイクル設定）
- 環境別のエンドポイント設定ガイド（本番=AWS S3、開発/CI/オンプレ評価=SeaweedFS）
- SeaweedFS の開発環境構築 Runbook（Docker Compose 同梱）

### 11.3 取り込みパイプラインの再実行性

- 取り込み中の中断・再開シナリオ（数千件の法令を全件取り込み中に失敗した場合）
- `ingest_run` / `ingest_law_event` の運用設計（リトライ単位は法令か履歴か）
- `law_xml.xml_sha256` を使った冪等性確認のフロー
- 差分取り込み（過去 3 か月）と全件取り込みの整合性検証

### 11.4 改正条文ツリー (`AmendProvision`) のレンダリング戦略

- `/law_data` レスポンスで改正条文サブツリーをどう扱うか
- `omit_amendment_suppl_provision=true` の判定実装と、被改正法令の本体と改正法令の附則を分離するロジック
- 改正前後比較（条文比較）機能の要不要

### 11.5 引用関係の抽出

- 法令本文の引用リンク（e-Gov サイト UI で「他の法令へのリンク」と表示されているもの）をデータ化するか
- 自動抽出する場合の精度評価（e-Gov 側は機械処理で付与し誤検出があると公言）
- 引用元 / 引用先のグラフテーブル設計

### 11.6 法令データ ドキュメンテーション (α) のフォローアップ

- `https://laws.e-gov.go.jp/docs/` の更新追跡（α 版のため仕様変更頻度が高い）
- API v2 試行版機能（JSON 形式レスポンス、`law_num` を含むパラメータ指定時のレスポンス）の仕様変更に追随する仕組み

### 11.7 ジョブキュー実装方式（Procrastinate 採用確定）

**結論**: **Procrastinate** を採用する。本節は選定経緯と実装メモを残す検討資料。残課題は §11.7.5「採用後の検討事項」に集約。

**前提と制約**:

- **Redis は使用しない**（運用ミドルウェアを増やしたくない）。
- バックエンドとして許容するのは **AWS SQS（または SQS 互換ソフトウェア）** か **PostgreSQL** のいずれか。
- 既に確定済みの構成: AWS S3（本番）/ SeaweedFS（開発）、PostgreSQL（本番／開発共通）。
- 言語ランタイム: Python 3.12+、asyncio ネイティブ。
- 想定ワークロード:
  - 全件取り込み: 数十分〜数時間の長尺ジョブ、年に数回。
  - 差分取り込み: 日次 cron、数分〜数十分。
  - 添付ファイル S3 アップロード: 数千〜数万の小ジョブ。
  - 検索インデックス再構築: 不定期、長尺。
- 必要機能: **async ネイティブ実行**、**cron / periodic**、**再試行＋バックオフ**、**進捗観測**、**冪等性**。

**Arq は不採用**: Redis 専用設計でバックエンド差し替え不可。

#### 11.7.1 候補方式

**方式 A: AWS SQS + 自前ワーカー（aioboto3）**

- SQS 標準キュー（または FIFO）からポーリングする async ワーカープロセスを自前実装。
- 本番は AWS マネージドサービスのため運用負荷ゼロ。Lambda トリガとも組み合わせ可能。
- 開発・CI は **ElasticMQ**（Scala 製、SQS API 互換、軽量）か **LocalStack**（広範な AWS API モック）で代替。
- cron 機能は SQS にないため、**EventBridge Scheduler**（本番）／**cron + enqueue スクリプト**（開発）で補う。

**方式 B: PostgreSQL ベースのジョブキューライブラリ**

候補ライブラリ:

- **Procrastinate** (Doctolib 製): `LISTEN/NOTIFY` ベース、async ネイティブ、cron 内蔵、再試行内蔵、ジョブテーブルが SQL 観測可能、Alembic 連携可。**第1候補**。
- **pgmq** (Tembo 製 PG 拡張): SQL ライクで軽量。ただし cron / 再試行は自前実装が必要。
- **pgqueuer** (新興): asyncpg ベース、シンプル。実績まだ少。
- **APScheduler + 自前テーブル**: 機能は限定的。
- **自作（advisory lock + skip-locked）**: 学習コスト 0 だがメンテ負荷を抱える。

**方式 C: ハイブリッド（PostgreSQL = メタ管理 + SQS = ワーカー配送）**

- ジョブの状態・履歴・依存関係は PostgreSQL の `ingest_run` / `ingest_law_event` テーブル（§4.9）で永続管理。
- ジョブの配送のみ SQS を経由し、ワーカーは SQS をポーリング。
- 複雑度は上がるが、観測性（SQL）とスケール（SQS）を両取りできる。

#### 11.7.2 比較表

| 観点 | A: SQS + 自前 | B: Procrastinate | C: ハイブリッド |
|---|---|---|---|
| 追加ミドルウェア | SQS（本番）/ ElasticMQ（開発） | なし（PG 流用） | SQS + PG |
| async ネイティブ | ◎ aioboto3 で完結 | ◎ | ◎ |
| cron / periodic | △ EventBridge 等で外付け | ◎ 標準機能 | △ EventBridge |
| 再試行・バックオフ | ○ 可視性タイムアウト + DLQ | ◎ ライブラリ標準 | ○ |
| 進捗観測 | △ CloudWatch / 自前テーブル | ◎ SQL 一発 | ◎ |
| 長尺ジョブ（数時間） | △ 可視性タイムアウト調整必要、Heartbeat 必要 | ○ ロック保持 + 通知 | △ |
| ワーカー水平スケール | ◎ SQS 自然 | ○ skip-locked で OK | ◎ |
| ローカル開発の容易さ | △ ElasticMQ / LocalStack 追加 | ◎ DB だけで完結 | △ |
| ベンダーロックイン | ○ SQS API はほぼ標準 | ◎ なし | △ |
| 学習コスト | 中（実装の手数）| 低 | 高 |
| 既存テーブルとの統合 | △ 別物 | ◎ 同居 | ◎ |

#### 11.7.3 評価

- **本プロジェクトの規模**は中小規模で、ワーカー水平スケール要求は当面ない。ジョブ件数も SQS 課金が問題になる規模ではない。
- **観測性**を重視するなら、ジョブ状態を SQL でクエリできる方式 B が圧倒的に楽（取り込み失敗の調査、再実行範囲の特定が `SELECT` だけで済む）。
- **ローカル開発・CI** で追加ミドルウェアを増やしたくない方針と方式 B が一致。
- **将来サーバーレス化**（Lambda 移行）を視野に入れるなら方式 A / C。現時点ではその想定はない。

#### 11.7.4 採用結論

**採用: 方式 B（Procrastinate）**

決定理由:

1. 既に運用する PostgreSQL に同居でき、**追加ミドルウェアゼロ**。Redis 不使用方針と完全一致。
2. `procrastinate_jobs` テーブルが `ingest_run` / `ingest_law_event`（§4.9）と SQL で結合・横断観測できる。
3. asyncio ネイティブで FastAPI と同じイベントループに乗る。
4. cron / 再試行 / バックオフ / 優先度がライブラリ標準。
5. Alembic で同居スキーマ管理可能（`procrastinate.schema.sql` をリビジョン化）。

将来サーバーレス化（Lambda 移行）等で SQS に切り替える必要が生じた場合、**ジョブ関数のシグネチャ自体は変えずに `engine_adapter` 相当の薄い層を入れて移行可能**な形にしておく。

#### 11.7.5 採用後の検討事項（残課題）

- **Procrastinate スキーマ管理**: `procrastinate` 専用スキーマ名で隔離し、Alembic でリビジョン管理する手順。
- **長尺ジョブの分割**: 全件取り込みを 1 ジョブで完結させず、親ジョブ → 法令単位の子ジョブに分解する設計の細部。
- **失敗ジョブの DLQ 相当運用**: `procrastinate_jobs.status = 'failed'` の集約と再投入 API。
- **観測**: `procrastinate_jobs` を Grafana / Metabase に接続する具体ダッシュボード設計。
- **同一法令の並行更新防止**: 同じ `law_revision_id` を対象にしたジョブの直列化（`procrastinate` のキュー設計 or `pg_advisory_xact_lock`）。
- **ワーカープロセスの配置**: アプリと同居か別 Pod / コンテナか。本番運用の構成決定。

#### 11.7.6 実装メモ

```python
# app/jobs/app.py
from procrastinate import App, PsycopgConnector

procrastinate_app = App(connector=PsycopgConnector(
    kwargs={"conninfo": settings.database_url}
))

# app/jobs/ingest.py
@procrastinate_app.task(queue="ingest", retry=5, pass_context=True)
async def ingest_law_revision(context, law_revision_id: str) -> None:
    ...

@procrastinate_app.periodic(cron="0 3 * * *")
@procrastinate_app.task(queue="ingest")
async def daily_delta(timestamp: int) -> None:
    ...

# 起動: procrastinate --app=app.jobs.app.procrastinate_app worker
```

- Procrastinate のスキーマは `procrastinate` という独立スキーマ名で別管理し、アプリのテーブルと混在させない。
- 長尺ジョブ（全件取り込み）は `procrastinate` のジョブを「親」として 1 件作り、その中で法令単位の **子タスクを enqueue**する分割設計にする（1 ジョブ = 1 法令）。
- DLQ 相当: `procrastinate_jobs.status = 'failed'` の行を別 view で抽出し、Web UI から再投入できるエンドポイントを用意。
- 観測: `procrastinate_jobs` を Grafana / Metabase に接続。

### 11.8 既存改正法令の参照整合性（方針 C 採用確定）

**結論**: **方針 C（独立 `amendment_law` テーブル）＋ 方針 D（Lazy reconciliation）**を採用する。データモデルは §4.5 に反映済み。本節は選定経緯と残課題の整理。

**論点（§10-6）**: `law_revision.amendment_law_id` は「この履歴に対応する改正を行った法令の law_id」を指すが、**改正法令そのものが `law` テーブルに存在しないケース**が一定数発生する。

#### 11.8.1 不一致が発生する典型例

- **過去の改正法**: e-Gov の法令データ整備は平成 29 年（2017 年）4 月 1 日時点以降が中心。それ以前に成立して既に役目を終えた一部改正法（例: 昭和期の改正法）はマスタに含まれず、被改正法令の履歴側にのみ `amendment_law_id` 文字列として残る。
- **失効・廃止後にデータ削除**: 一部改正法は施行後に役目を終えると e-Gov 側で扱いが変わり、`law` の現行マスタに含まれない場合がある。
- **同一改正法 ID で複数履歴**: 1 本の改正法が複数の被改正法令の複数の履歴に紐づく多対多関係。
- **API v2 試行版**: `law_num` を含むパラメータでのレスポンスデータは試行版で仕様変更がありうる（OpenAPI ドキュメントの注意書き）。
- **取り込み順序問題**: 全件取り込み中、被改正法令を先に取り込んだ瞬間は改正法令が未投入で、トランザクション内では FK 解決できない。

#### 11.8.2 採用可能な方針

**方針 A: 厳格 FK（不採用）**

- `law_revision.amendment_law_id` を `law(law_id)` への NOT NULL FK にする。
- 取り込み時に改正法令が存在しない場合は取り込み失敗。
- **問題**: 失敗率が高すぎる。データ整備状況に依存して取り込みが頓挫する。

**方針 B: 文字列保持のみ（緩い参照）**

- `law_revision.amendment_law_id` は **FK なしの TEXT** として保持。`law` の有無に依存しない。
- 検索・表示時に LEFT JOIN で `law` を引き、ヒットしない場合は API レスポンスの `amendment_law_title` 等の文字列フィールドのみで応答（e-Gov API もこの形）。
- **長所**: 取り込みが堅牢。FK 制約による失敗がない。
- **短所**: 参照先の整合性が DB レベルで保証されない。整合性チェックはアプリ層 / 観測クエリで実施。

**方針 C: 独立した `amendment_law` テーブル（推奨）**

- 改正法令のメタ（`amendment_law_id`, `amendment_law_title`, `amendment_law_title_kana`, `amendment_law_num`）を **`amendment_law` テーブル**に別管理。
- `law_revision.amendment_law_id` は `amendment_law(amendment_law_id)` への FK（必須 / 任意は要決定、原則 NOT NULL）。
- `amendment_law` は `law` とは別系統で、改正法令が後から `law` に投入された場合は **`amendment_law.linked_law_id` を埋めて両者を紐付ける**（Lazy Linking）。
- API レスポンス組立時は `amendment_law` を 1 次ソース、`law` への解決は `linked_law_id` 経由で行う。
- **長所**: 改正法令のメタを必ず DB に持ち、整合性を保証できる。`law` の有無に依存しない。後付けで関連付けも可能。
- **短所**: テーブル 1 つ増える。取り込みロジックが少し複雑になる。

```
TABLE amendment_law
  amendment_law_id        VARCHAR(15) PRIMARY KEY      -- 例: 506CO0000000161（law_id 形式）
  amendment_law_title     TEXT
  amendment_law_title_kana TEXT
  amendment_law_num       TEXT
  amendment_promulgate_date DATE
  linked_law_id           VARCHAR(15) REFERENCES law(law_id)   -- 後付けで紐付け可能
  first_seen_at           TIMESTAMPTZ NOT NULL
  last_seen_at            TIMESTAMPTZ NOT NULL
  INDEX (linked_law_id)
```

`law_revision`:

```
amendment_law_id VARCHAR(15) REFERENCES amendment_law(amendment_law_id)
```

**方針 D: Lazy reconciliation（C との併用または B との併用）**

- 取り込みパイプラインの末尾、または日次バッチで **`amendment_law.linked_law_id` を `law` と再突合**する Procrastinate ジョブを定期実行（`@periodic`）。
- 全件取り込み直後と、差分取り込み完了直後に必ず走らせる。

#### 11.8.3 採用決定（方針 C ＋ D）

決定理由:

- e-Gov API v2 のレスポンス構造（`amendment_law_id` + `amendment_law_title` + `amendment_law_num` がフラットに並ぶ）と `amendment_law` テーブルが 1:1 対応する。
- `law` への厳格 FK を避けつつ、改正法令のメタ自体は欠落させない。
- 後から改正法令が `law` に投入された際に、Lazy ジョブで自然に整合性が回復する。
- API ハンドラ側のクエリは `law_revision LEFT JOIN amendment_law LEFT JOIN law ON law.law_id = amendment_law.linked_law_id` の 2 段 LEFT JOIN で完結。

§4.5「改正関係」にあった旧 `amendment_relation` テーブルは `amendment_law` で吸収済み（§4.5 を改訂）。改正法令と被改正法令の多対多は `law_revision.amendment_law_id` の N:1 で表現される。

#### 11.8.4 残課題

- **`amendment_law` への UPSERT 仕様**: 同一 ID で `amendment_law_title` 等が差し替わった場合の扱い（履歴を取るか上書きか）。**初期は上書き**（`last_seen_at` のみ追記）とし、必要に応じて履歴テーブルを追加する方向。
- **取り込み順序**: 被改正法令の `law_revision` を投入する前に、`amendment_law` 行をプレースホルダとして UPSERT する（最低限 `amendment_law_id` のみ確定で、メタは順次補完）。
- **新規制定法令の扱い**: `mission=New` の `law_revision` で `amendment_law_id` をどう持つか。
  - 案 1: NULL 許容（`law_revision.amendment_law_id` を NULL 可とする）。
  - 案 2: 自己参照プレースホルダ（`amendment_law_id = law_id` の `amendment_law` 行を生成）。
  - 案 1 を第1候補とする方向（要レビュー）。
- **Lazy reconciliation の頻度**: 全件取り込み直後、日次差分取り込み直後、または独立した weekly ジョブのいずれか。第1候補は「差分取り込み完了後に毎回実行」。
- **API レスポンスでの表現**: 解決済み（`linked_law_id` 有）と未解決を区別するフィールドを返すか否か。e-Gov 互換維持のため **既定では区別を返さず**、内部観測用フィールドのみとする。

#### アウトプット

- `amendment_law` テーブル DDL（Alembic リビジョン、§4.5 反映済み）と取り込みロジック詳細
- Lazy reconciliation ジョブ（Procrastinate `@task` 化）の実装方針
- 新規制定法令の `amendment_law_id` 扱いに関する最終決定メモ

### 11.9 参考: 不採用方式の予備メモ（ジョブキュー方式 A: SQS + 自前ワーカー）

将来 Procrastinate から SQS へ移行する必要が生じた場合の参考メモ。

- キュー名: `laws-ingest-<env>`、DLQ: `laws-ingest-dlq-<env>`。
- 可視性タイムアウト: 全件取り込みのような長尺ジョブはタイムアウト延長 (`ChangeMessageVisibility`) を Heartbeat で実施。
- ローカル: `docker compose` に **ElasticMQ** を同梱。`AWS_ENDPOINT_URL_SQS` の差し替えで aioboto3 が動作。
- cron: 本番 EventBridge Scheduler、開発は `apscheduler` または `cron`。
- ジョブメタは独自テーブル `ingest_run` / `ingest_law_event` で管理。

#### アウトプット

- Procrastinate 採用の意思決定記録（ADR）
- Procrastinate スキーマの Alembic リビジョン同居方法
- 長尺ジョブの分割設計（親 → 子タスク）と DLQ 運用 Runbook
