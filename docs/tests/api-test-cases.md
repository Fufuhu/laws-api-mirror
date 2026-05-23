# API テストケース設計書

e-Gov 法令 API v2 互換エンドポイント（設計書 §7）に対する API テストケース集。**同値分割**と**境界値分析**を中心に、1st リリース時点で抑えるべき確認項目を網羅する。

設計書本体（`docs/design/`）の決定事項に基づき、以下を前提とする:

- 1st リリースは **e-Gov v2 API のインタフェース互換**のみ維持。レスポンスのバイト単位一致は目指さない（§10-9）。
- `/law_file/{file_type}` は **`xml` / `json` のみ対応**、それ以外は **400 Bad Request**（§10-3）。
- レスポンス形式は `response_format=json|xml` をすべてのエンドポイントでサポート。`Accept` ヘッダからの自動判定も実装。
- エラー形式は `error_info {code, message}`（e-Gov の仕様を踏襲）。

## 1. テスト方針

### 1.1 同値分割（Equivalence Partitioning）

- 入力パラメータごとに**有効同値クラス**と**無効同値クラス**を定義し、各クラスから代表値 1 件をテストする。
- 例: `law_num_era` は `Meiji|Taisho|Showa|Heisei|Reiwa` の 5 値が有効、それ以外は無効。

### 1.2 境界値分析（Boundary Value Analysis）

- 数値・日付・文字列長のパラメータについて、**有効範囲の上下端 ± 1** をテストする。
- 例: `limit` の上限・下限、`promulgation_date_from <= promulgation_date_to` の境界、`offset = 0` と `offset = total_count - 1`。

### 1.3 テスト ID / テスト名 規約

- ID 形式: `TC-<endpoint>-<category>-<seq>`
  - `endpoint`: `laws` / `rev` / `data` / `file` / `att` / `kw` / `common` / `scope`
  - `category`: `eq`（同値）/ `bv`（境界値）/ `comb`（組合せ）/ `err`（エラー）/ `compat`（互換性）
- **テスト名**: 「何を確認するか（目的）」を 1 行で述べる。テスト失敗時にレポートだけで論点が分かる粒度。
- 表は `| ID | テスト名 | 入力 | 期待結果 |` で統一。

## 2. 共通テストケース（全エンドポイント横断）

### 2.1 レスポンス形式（`response_format`）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-common-eq-01 | response_format=json で JSON レスポンスが返ること | `response_format=json` | `Content-Type: application/json`、JSON ボディ |
| TC-common-eq-02 | response_format=xml で XML レスポンスが返ること | `response_format=xml` | `Content-Type: application/xml`、XML ボディ |
| TC-common-eq-03 | Accept: application/json でフォーマットが自動判定されること | 指定なし、`Accept: application/json` | JSON |
| TC-common-eq-04 | Accept: application/xml でフォーマットが自動判定されること | 指定なし、`Accept: application/xml` | XML |
| TC-common-eq-05 | response_format も Accept も無いとき既定が JSON であること | 指定なし、`Accept` ヘッダなし | JSON（既定） |
| TC-common-err-01 | 未対応の response_format で 400 が返ること | `response_format=yaml` | 400、`error_info` を含む |
| TC-common-err-02 | response_format 空文字で 400 が返ること | `response_format=` | 400 |
| TC-common-err-03 | response_format の大文字小文字を厳格にマッチすること | `response_format=JSON` | 400 |

### 2.2 エラーレスポンス形式

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-common-err-10 | 400 系エラーで error_info {code, message} が返ること | 任意の 400 | `error_info {code:str, message:str}` を含む |
| TC-common-err-11 | 500 系エラーでも error_info が返ること | サーバ内エラーをモック注入 | 500、`error_info` を含む |
| TC-common-err-12 | 未定義パスで 404 が返ること | `/api/2/unknown` | 404 |
| TC-common-err-13 | 許可されない HTTP メソッドで 405 が返ること | `POST /api/2/laws` | 405 |

### 2.3 文字エンコーディング

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-common-eq-20 | UTF-8 日本語クエリが URL エンコードで受理されること | `law_title=個人情報`（エンコード済み） | 200、絞り込みヒット |
| TC-common-eq-21 | 空文字パラメータが「指定なし」として扱われること | `law_title=` | 200、絞り込みなし |
| TC-common-err-20 | 不正な % エスケープで 400 が返ること | `law_title=%ZZ` | 400 |

## 3. `/api/2/laws` 法令一覧取得

### 3.1 `law_id`（部分一致、文字列）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-01 | law_id 完全一致で該当法令 1 件が返ること | `law_id=322CO0000000016` | 該当 1 件 |
| TC-laws-eq-02 | law_id 部分一致で複数件が返ること | `law_id=322CO` | 複数件 |
| TC-laws-eq-03 | 存在しない law_id で 0 件が返ること | `law_id=ZZZZZZZZZZZZ` | `total_count=0`、`laws=[]` |
| TC-laws-bv-01 | law_id 空文字でパラメータが無視されること | `law_id=` | 絞り込みなし |
| TC-laws-bv-02 | law_id 最大長 15 文字で正常動作すること | 15 文字 | 200 |
| TC-laws-bv-03 | law_id 16 文字以上はヒットしないが 400 にならないこと | 16 文字 | 200、ヒットなし |

### 3.2 `law_num_era`（enum: Meiji / Taisho / Showa / Heisei / Reiwa）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-10 | 最古元号 Meiji が enum として受理されること | `law_num_era=Meiji` | 該当ヒット |
| TC-laws-eq-11 | 最新元号 Reiwa が enum として受理されること | `law_num_era=Reiwa` | 該当ヒット |
| TC-laws-err-10 | enum 外の元号で 400 が返ること | `law_num_era=Edo` | 400 |
| TC-laws-err-11 | 大文字小文字の不一致で 400 が返ること | `law_num_era=meiji` | 400 |
| TC-laws-err-12 | 空文字での挙動（既定: パラメータ無視）が一貫すること | `law_num_era=` | パラメータ無視 |

### 3.3 `law_num_year`（整数）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-bv-10 | 最小値 1 が受理されること | `law_num_year=1` | 200 |
| TC-laws-bv-11 | 二桁年が正常処理されること | `law_num_year=99` | 200 |
| TC-laws-bv-12 | 0 は正の整数前提から外れること | `law_num_year=0` | 400 or ヒットなし |
| TC-laws-bv-13 | 負の整数で 400 が返ること | `law_num_year=-1` | 400 |
| TC-laws-bv-14 | int32 上限が受理されること | `law_num_year=2147483647` | 200、ヒットなし |
| TC-laws-bv-15 | int32 オーバーで 400 が返ること | `law_num_year=2147483648` | 400 |
| TC-laws-err-20 | 非整数文字列で 400 が返ること | `law_num_year=abc` | 400 |
| TC-laws-err-21 | 小数で 400 が返ること | `law_num_year=1.5` | 400 |

### 3.4 `law_num_type` / `law_num`（部分一致） / `law_num_num`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-20 | law_num_type=Act で法律のみが返ること | `law_num_type=Act` | 法律のみ |
| TC-laws-eq-21 | enum 末尾 Misc が受理されること | `law_num_type=Misc` | 該当ヒット |
| TC-laws-err-30 | 未定義の法令種別で 400 が返ること | `law_num_type=Decree` | 400 |
| TC-laws-eq-22 | law_num 完全一致でヒットすること | `law_num=昭和二十二年政令第十六号` | 完全一致 |
| TC-laws-eq-23 | law_num 部分一致で複数件ヒットすること | `law_num=政令第十六号` | 複数件 |
| TC-laws-eq-24 | law_num_num のゼロ詰め文字列がヒットすること | `law_num_num=016` | ヒット |
| TC-laws-eq-25 | law_num_num のゼロ詰めなしも部分一致でヒットすること | `law_num_num=16` | 部分一致ヒット |

### 3.5 `law_type`（複数指定可: カンマ区切り）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-30 | 単一指定で該当種別のみ返ること | `law_type=Act` | 法律のみ |
| TC-laws-eq-31 | カンマ区切り複数指定で和集合が返ること | `law_type=Act,Rule` | 法律＋規則 |
| TC-laws-eq-32 | 重複指定が単一と同等に扱われること | `law_type=Act,Act` | `Act` 単独と同等 |
| TC-laws-err-40 | 不正な要素を含む配列で 400 が返ること | `law_type=Act,Bogus` | 400 |
| TC-laws-bv-30 | law_type 空文字の挙動が一貫すること | `law_type=` | パラメータ無視 |

### 3.6 `category_cd`（複数指定、001〜050）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-40 | 最小コード 001（憲法）が受理されること | `category_cd=001` | 該当ヒット |
| TC-laws-eq-41 | 最大コード 050（外事）が受理されること | `category_cd=050` | 該当ヒット |
| TC-laws-eq-42 | 複数コード指定で和集合が返ること | `category_cd=001,002` | 和集合 |
| TC-laws-err-50 | 範囲下限を下回るコードで 400 が返ること | `category_cd=000` | 400 |
| TC-laws-err-51 | 範囲上限を上回るコードで 400 が返ること | `category_cd=051` | 400 |
| TC-laws-err-52 | ゼロ詰めなしの 1 桁で 400 が返ること（書式厳格） | `category_cd=1` | 400 |
| TC-laws-err-53 | 英字を含む不正コードで 400 が返ること | `category_cd=ABC` | 400 |

### 3.7 `repeal_status`（複数指定: None / Repeal / Expire / Suspend / LossOfEffectiveness）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-50 | None で廃止等のない法令のみ抽出されること | `repeal_status=None` | 該当のみ |
| TC-laws-eq-51 | 複数の状態で和集合が返ること | `repeal_status=Repeal,Expire` | 和集合 |
| TC-laws-err-60 | 未定義の状態で 400 が返ること | `repeal_status=Unknown` | 400 |

### 3.8 `mission`（New / Partial）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-60 | New 単独指定で新規制定のみが返ること | `mission=New` | 新規制定のみ |
| TC-laws-eq-61 | 全種列挙が全件相当として扱われること | `mission=New,Partial` | 全件相当 |
| TC-laws-err-70 | 未定義 mission で 400 が返ること | `mission=All` | 400 |

### 3.9 `asof`（日付）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-70 | 典型日付で当時の有効履歴が返ること | `asof=2023-07-01` | 該当履歴 |
| TC-laws-bv-70 | 極端な過去日付が受理され応答が返ること | `asof=0001-01-01` | 200、ヒットなし or 古い時点 |
| TC-laws-bv-71 | 極端な未来日付では最新履歴が返ること | `asof=9999-12-31` | 最新履歴 |
| TC-laws-bv-72 | asof 空文字で「現時点」として扱われること | `asof=` | パラメータ無視 |
| TC-laws-err-80 | YYYY/MM/DD 形式で 400 が返ること | `asof=2023/07/01` | 400 |
| TC-laws-err-81 | 月の範囲外で 400 が返ること | `asof=2023-13-01` | 400 |
| TC-laws-err-82 | 日の範囲外（うるう年含む）で 400 が返ること | `asof=2023-02-30` | 400 |
| TC-laws-err-83 | 区切り無しの日付文字列で 400 が返ること | `asof=20230701` | 400 |

### 3.10 `promulgation_date_from` / `promulgation_date_to`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-bv-80 | from のみ指定で「以後」の絞り込みが効くこと | `promulgation_date_from=2023-01-01` | 該当ヒット |
| TC-laws-bv-81 | to のみ指定で「以前」の絞り込みが効くこと | `promulgation_date_to=2023-12-31` | 該当ヒット |
| TC-laws-bv-82 | from と to の両方指定で範囲内が返ること | from=2023-01-01, to=2023-12-31 | 範囲内 |
| TC-laws-bv-83 | from > to の逆転入力で空集合（または 400）になること | from=2023-12-31, to=2023-01-01 | 0 件 or 400 |
| TC-laws-bv-84 | from と to が同日で当該日付の法令のみ返ること | from=to=同日 | 該当のみ |
| TC-laws-err-90 | from / to のどちらかが不正日付で 400 が返ること | to=2023-13-31 | 400 |

### 3.11 `limit`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-bv-90 | limit=1 で 1 件が返り next_offset が 1 になること | `limit=1` | `count=1`、`next_offset=1` |
| TC-laws-bv-91 | limit=100（既定）で既定相当の件数が返ること | `limit=100` | 既定相当 |
| TC-laws-bv-92 | limit=0 で 400 が返ること | `limit=0` | 400 |
| TC-laws-bv-93 | 負の limit で 400 が返ること | `limit=-1` | 400 |
| TC-laws-bv-94 | int32 上限指定で内部上限にクリップ or 400 となること | `limit=2147483647` | 400 or クリップ |
| TC-laws-bv-95 | 非整数 limit で 400 が返ること | `limit=abc` | 400 |

### 3.12 `offset`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-bv-100 | offset=0（既定）で先頭から返ること | `offset=0` | 1 件目から |
| TC-laws-bv-101 | offset=total_count-1 で末尾 1 件と next_offset=null が返ること | `offset=total_count - 1` | `next_offset=null` |
| TC-laws-bv-102 | offset=total_count で空配列が返ること | `offset=total_count` | `count=0` |
| TC-laws-bv-103 | 負の offset で 400 が返ること | `offset=-1` | 400 |
| TC-laws-bv-104 | 非整数 offset で 400 が返ること | `offset=abc` | 400 |

### 3.13 `order`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-110 | 既定の order（law_id 昇順）で正しく並ぶこと | `order=law_info.law_id` | 昇順 |
| TC-laws-eq-111 | + 接頭辞で昇順指定できること | `order=+law_info.law_id` | 昇順 |
| TC-laws-eq-112 | - 接頭辞で降順指定できること | `order=-law_info.law_id` | 降順 |
| TC-laws-eq-113 | 複合キーで第二キーまで反映されること | `order=+law_info.law_id,-revision_info.amendment_promulgate_date` | 複合ソート |
| TC-laws-err-110 | ホワイトリスト外フィールドで 400 が返ること | `order=non_existent_field` | 400 |
| TC-laws-err-111 | SQL インジェクション試行が拒否されること | `order=law_info.law_id; DROP TABLE` | 400 |
| TC-laws-err-112 | order 空文字で既定が適用されること | `order=` | 既定適用 |

### 3.14 `omit_current_revision_info`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-eq-120 | true 指定で current_revision_info がレスポンスから除外されること | `omit_current_revision_info=true` | フィールド無し |
| TC-laws-eq-121 | false（既定）で current_revision_info が含まれること | `omit_current_revision_info=false` | フィールド有り |
| TC-laws-err-120 | boolean 以外の値で 400 が返ること | `omit_current_revision_info=yes` | 400 |

### 3.15 組合せテスト

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-laws-comb-01 | law_title と law_type の AND 絞り込みが効くこと | `law_title=個人情報` + `law_type=Act` | AND |
| TC-laws-comb-02 | 三条件 AND（category + repeal + asof）が成立すること | `category_cd=001` + `repeal_status=None` + `asof=2024-01-01` | AND |
| TC-laws-comb-03 | amendment_law_id 指定時に asof が無視される仕様が守られること | `amendment_law_id` + `asof` | `asof` 無視 |
| TC-laws-comb-04 | 全パラメータ同時指定で整合した結果が返ること | 網羅 | 200 |

### 3.16 レスポンス形状の確認

| ID | テスト名 | 期待結果 |
|---|---|---|
| TC-laws-compat-01 | レスポンスの必須トップフィールドが揃うこと | `total_count`, `count`, `next_offset`, `laws` |
| TC-laws-compat-02 | laws[].law_info の必須フィールドが揃うこと | `law_id`, `law_type`, `law_num`, `law_num_era`, `law_num_year`, `law_num_type`, `law_num_num`, `promulgation_date` |
| TC-laws-compat-03 | laws[].revision_info の必須フィールドが揃うこと | v2 仕様一式 |
| TC-laws-compat-04 | 末尾到達時に next_offset=null となること | 該当時 | `null` |

## 4. `/api/2/law_revisions/{law_id_or_num}` 法令履歴一覧取得

### 4.1 パス引数

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-rev-eq-01 | law_id 指定で履歴一覧が返ること | `/law_revisions/322CO0000000016` | 履歴複数件 |
| TC-rev-eq-02 | law_num 指定で履歴一覧が返ること | `/law_revisions/昭和二十二年政令第十六号` | 履歴複数件 |
| TC-rev-eq-03 | 不存在 ID で 404 または空応答が返ること | `/law_revisions/ZZZ` | 404 or `total_count=0` |
| TC-rev-bv-01 | URL エンコード済み日本語 law_num が正しくデコードされること | `%E6%98%AD%E5%92%8C...` | デコード→処理 |
| TC-rev-err-01 | パス引数なしでルーティング不一致になること | `/law_revisions/` | 404 |
| TC-rev-err-02 | パスに `/` を含む不正値でルーティング不一致になること | `/law_revisions/a/b` | 404 |

### 4.2 レスポンス

| ID | テスト名 | 期待結果 |
|---|---|---|
| TC-rev-compat-01 | レスポンスの必須トップフィールドが揃うこと | `law_info`, `revisions[]` |
| TC-rev-compat-02 | revisions が law_revision_id 降順で並ぶこと | 新しい順 |
| TC-rev-compat-03 | 各 revisions[] に履歴属性が揃うこと | `law_title`, `amendment_promulgate_date`, `amendment_law_id` 等 |

## 5. `/api/2/law_data/{law_id_or_num_or_revision_id}` 法令本文取得

### 5.1 パス引数の 3 形式（同値クラス）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-data-eq-01 | law_id 指定で最新リビジョンの本文が返ること | `/law_data/411AC0000000127` | 最新リビジョン |
| TC-data-eq-02 | law_num 指定で最新リビジョンの本文が返ること | `/law_data/平成十一年法律第百二十七号` | 最新リビジョン |
| TC-data-eq-03 | law_revision_id 指定で当該リビジョンが返ること | `/law_data/411AC0000000127_19990813_000000000000000` | 指定リビジョン |
| TC-data-eq-04 | 存在しない ID で 404 が返ること | 不存在 ID | 404 |

### 5.2 `law_full_text_format` × `response_format`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-data-eq-10 | json × json は本文も JSON で返ること | `response_format=json`, `law_full_text_format=json` | `law_full_text` が JSON |
| TC-data-eq-11 | json × xml は本文が Base64 化されること | `response_format=json`, `law_full_text_format=xml` | `law_full_text` が Base64 文字列 |
| TC-data-eq-12 | xml × xml は本文が XML 内 XML で返ること | `response_format=xml`, `law_full_text_format=xml` | XML 内 XML |
| TC-data-eq-13 | xml × json は本文が Base64 化されること | `response_format=xml`, `law_full_text_format=json` | Base64 文字列 |
| TC-data-err-10 | 未定義の law_full_text_format で 400 が返ること | `law_full_text_format=yaml` | 400 |

### 5.3 `json_format`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-data-eq-20 | full（既定）で詳細版 JSON ツリーが返ること | `json_format=full` | `{tag, attr, children}` |
| TC-data-eq-21 | light で簡易版 JSON が返ること | `json_format=light` | `{TagName: value or array}` |
| TC-data-err-20 | 未定義の json_format で 400 が返ること | `json_format=medium` | 400 |
| TC-data-compat-20 | light の Ruby がベーステキストのみ埋め込みである（1st 実装） | Ruby を含む条文 | ベーステキストのみ（§11.11） |

### 5.4 `elm`（要素絞り込み）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-data-eq-30 | MainProvision 指定で本則全体が返ること | `elm=MainProvision` | 本則全体 |
| TC-data-eq-31 | Article_21 指定で第 21 条全体が返ること | `elm=MainProvision-Article_21` | 第 21 条 |
| TC-data-eq-32 | Paragraph 指定で項単位に絞られること | `elm=MainProvision-Article_21-Paragraph_3` | 第 21 条第 3 項 |
| TC-data-eq-33 | 枝番 Article_21_2 が解決されること | `elm=MainProvision-Article_21_2` | 第 21 条の 2 |
| TC-data-eq-34 | SupplProvision[1] が ordinal 指定として解決されること | `elm=SupplProvision[1]` | 1 つ目の附則 |
| TC-data-bv-30 | elm 空文字で全文が返ること | `elm=` | 全文 |
| TC-data-bv-31 | 存在しないノード指定で空応答 or 404 となること | `elm=NonExistent` | 空 or 404 |
| TC-data-err-30 | 区切り誤り（スラッシュ）で 400 が返ること | `elm=MainProvision/Article_21` | 400 |
| TC-data-err-31 | SQL/ltree インジェクション試行が拒否されること | `elm=MainProvision-Article_21; DROP` | 400 |

### 5.5 `asof` / `omit_amendment_suppl_provision` / `include_attached_file_content`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-data-eq-40 | asof 指定で当時のリビジョンの本文が返ること | `asof=2020-01-01` | 当時のリビジョン |
| TC-data-eq-41 | law_revision_id 指定時に asof が無視される仕様が守られること | revision_id + `asof` | `asof` 無視 |
| TC-data-eq-42 | omit_amendment_suppl_provision=true で改正附則が除外されること | true | `suppl_type='Amend'` を除外 |
| TC-data-eq-43 | include_attached_file_content=true で画像 Base64 が含まれること | true | `image_data` に Base64 |
| TC-data-eq-44 | include_attached_file_content=false（既定）で image_data が空であること | false | 空 |

## 6. `/api/2/law_file/{file_type}/{law_id_or_num_or_revision_id}` 法令本文ファイル取得

### 6.1 `file_type`（1st リリースは xml / json のみ）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-file-eq-01 | xml 指定で XML バイナリが返ること | `/law_file/xml/{id}` | XML ファイル |
| TC-file-eq-02 | json 指定で JSON バイナリが返ること | `/law_file/json/{id}` | JSON ファイル |
| TC-file-err-01 | html が 1st リリース非対応として 400 になること | `/law_file/html/{id}` | 400（§10-3） |
| TC-file-err-02 | rtf が 1st リリース非対応として 400 になること | `/law_file/rtf/{id}` | 400 |
| TC-file-err-03 | docx が 1st リリース非対応として 400 になること | `/law_file/docx/{id}` | 400 |
| TC-file-err-04 | 仕様外の pdf が 400 になること | `/law_file/pdf/{id}` | 400 |
| TC-file-err-05 | file_type の大文字小文字を厳格にマッチすること | `/law_file/XML/{id}` | 400 |
| TC-file-err-06 | file_type 空でルーティング不一致になること | `/law_file//{id}` | 404 |

### 6.2 ID 解決

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-file-eq-10 | 各 ID 形式（law_id / law_num / law_revision_id）が解決されること | 各形式 | 200 |
| TC-file-err-10 | 不存在 ID で 404 が返ること | 不存在 ID | 404 |

### 6.3 `asof`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-file-eq-20 | asof 指定で当時の本文ファイルが返ること | `asof=2023-04-01` | 当時のファイル |
| TC-file-eq-21 | law_revision_id 指定時に asof が無視されること | revision_id + asof | `asof` 無視 |

## 7. `/api/2/attachment/{law_revision_id}` 添付ファイル取得

### 7.1 `src` 指定 / 未指定の同値クラス

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-att-eq-01 | src 指定（JPG）で単体画像が返ること | `src=./pict/M06SE065-001.jpg` | JPG バイナリ |
| TC-att-eq-02 | src 指定（PDF）で単体ファイルが返ること | `src=./pict/sample.pdf` | PDF バイナリ |
| TC-att-eq-03 | src 未指定で Zip 一括返却となること | `src` 未指定 | Zip |
| TC-att-err-01 | 不存在の src で 404 が返ること | 不存在 src | 404 |
| TC-att-err-02 | 不存在の law_revision_id で 404 が返ること | 不存在 id | 404 |
| TC-att-err-03 | パストラバーサル試行が拒否されること | `src=../etc/passwd` | 400 |
| TC-att-err-04 | NULL バイト混入が拒否されること | `src` に `%00` | 400 |

### 7.2 Content-Type

| ID | テスト名 | 期待結果 |
|---|---|---|
| TC-att-compat-01 | JPG レスポンスの Content-Type が image/jpeg であること | `image/jpeg` |
| TC-att-compat-02 | PDF レスポンスの Content-Type が application/pdf であること | `application/pdf` |
| TC-att-compat-03 | Zip 一括の Content-Type が application/zip であること | `application/zip` |

## 8. `/api/2/keyword` キーワード検索

### 8.1 `keyword` 必須・形式

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-eq-01 | 典型キーワードで該当条文が返ること | `keyword=デジタル庁` | 該当条文一覧 |
| TC-kw-bv-01 | keyword 空文字で 400 が返ること | `keyword=` | 400 |
| TC-kw-err-01 | keyword 未指定で 400 が返ること | 未指定 | 400 |
| TC-kw-bv-02 | 1 文字キーワードで LIKE フォールバックが動作すること | `keyword=庁` | 200（bigm 不利用） |
| TC-kw-bv-03 | 2 文字キーワードで bigm 索引が利用されること | `keyword=情報` | 200（索引利用） |
| TC-kw-bv-04 | 極端に長い keyword で 200 または 414 になること | 1000 文字 | 200 or 414 |

### 8.2 検索式（AND / OR / NOT）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-eq-10 | スペース区切りが AND として解釈されること | `keyword=情報 公開` | AND |
| TC-kw-eq-11 | パイプ区切りが OR として解釈されること | `keyword=情報公開\|個人情報` | OR |
| TC-kw-eq-12 | 感嘆符接頭が NOT として解釈されること | `keyword=情報 !個人情報` | 「情報」AND NOT「個人情報」 |
| TC-kw-eq-13 | 括弧でグルーピングが効くこと | `keyword=(情報 公開)\|個人` | 仕様どおり |

### 8.3 ワイルドカード（pg_bigm 経路）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-eq-20 | `*` が 0 文字以上にマッチすること | `keyword=第*条` | 「第○○条」 |
| TC-kw-eq-21 | `?` が 1 文字にマッチすること | `keyword=第?条` | 1 文字ワイルドカード |
| TC-kw-eq-22 | 連続ワイルドカードが解釈されること | `keyword=であって*として*定める` | 仕様どおり |
| TC-kw-err-20 | `*` のみのキーワードが拒否されるか仕様どおり処理されること | `keyword=*` | 400 or 全件 |
| TC-kw-err-21 | ワイルドカードと AND/OR の組合せが仕様外として拒否されること | `keyword=第*条 情報` | 400 |

### 8.4 `limit` / `sentences_limit` / `sentence_text_size` / `offset`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-bv-30 | limit=1 で 1 件が返ること | `limit=1` | 1 件 |
| TC-kw-bv-31 | 仕様上限 1000 で受理されること | `limit=1000` | 1000 件 |
| TC-kw-bv-32 | 仕様上限超で 400 またはクリップとなること | `limit=1001` | 400 or 1000 にクリップ |
| TC-kw-bv-33 | limit=0 で 400 が返ること | `limit=0` | 400 |
| TC-kw-bv-34 | sentences_limit が sentences 数の上限として効くこと | `sentences_limit=5` + `limit=100` | sentences 5 まで |
| TC-kw-bv-35 | sentences_limit > limit のとき limit が優先されること | `sentences_limit=100, limit=10` | limit 優先 |
| TC-kw-bv-36 | sentence_text_size がテキスト切り出し長として効くこと | `sentence_text_size=20` | 20 文字 |
| TC-kw-bv-37 | sentence_text_size=0 が拒否 or 既定値適用されること | `sentence_text_size=0` | 400 or 既定 |
| TC-kw-bv-38 | offset の境界挙動が法令一覧と同等であること | TC-laws-bv-100〜104 参照 | 同等 |

### 8.5 `highlight_tag`

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-eq-40 | 任意タグ名でヒット箇所が囲まれること | `highlight_tag=em` | `<em>...</em>` |
| TC-kw-eq-41 | 既定値で span が使われること | 未指定 | `<span>...</span>` |
| TC-kw-err-40 | XSS 試行が拒否 or エスケープされること | `highlight_tag=<script>` | 400 or エスケープ |
| TC-kw-err-41 | 属性付きタグ名が拒否されること | `highlight_tag=div onclick="..."` | 400 |

### 8.6 法令絞り込み（laws と共通）

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-kw-comb-01 | keyword と law_type の AND 絞り込みが効くこと | `keyword=情報 公開` + `law_type=Act` | 法律のみ対象 |
| TC-kw-comb-02 | keyword と asof の組合せで時点絞り込みが効くこと | `keyword=デジタル` + `asof=2024-01-01` | 当時の本文 |
| TC-kw-comb-03 | keyword と category_cd の組合せで分類絞り込みが効くこと | `keyword=情報` + `category_cd=001,002` | 分類絞り込み |

### 8.7 レスポンス形状

| ID | テスト名 | 期待結果 |
|---|---|---|
| TC-kw-compat-01 | レスポンスの必須トップフィールドが揃うこと | `total_count`, `sentence_count`, `next_offset`, `items` |
| TC-kw-compat-02 | position が law_node.path_text 形式であること | `MainProvision-Article_21-Paragraph_3` 等 |
| TC-kw-compat-03 | text にハイライトタグが埋め込まれること | タグ付き文字列 |
| TC-kw-compat-04 | XML レスポンス時はハイライトタグがエスケープされること | エスケープ済み |

## 9. 1st リリース非対応事項のテスト

| ID | テスト名 | 入力 | 期待結果 |
|---|---|---|---|
| TC-scope-err-01 | html 形式が 1st リリースでサポートされないこと | `/law_file/html/...` | 400（§10-3） |
| TC-scope-err-02 | rtf 形式が 1st リリースでサポートされないこと | `/law_file/rtf/...` | 400 |
| TC-scope-err-03 | docx 形式が 1st リリースでサポートされないこと | `/law_file/docx/...` | 400 |
| TC-scope-compat-01 | レスポンスキャッシュ非対応であること（Cache-Control 設定）| 任意エンドポイント | `Cache-Control` 未設定 or `no-store`（§10-4）|

## 10. テストデータ準備方針

### 10.1 法令フィクスチャ

代表性を持たせるため以下のような法令を 10〜20 件選定（XSD v3 適合確認済み）:

- **構造的多様性**:
  - Part / Chapter / Section / Article 階層が深い（民法）
  - Article のみシンプル（短い政令）
  - SupplProvision に Amend を含む
  - AppdxTable / AppdxFig / AppdxStyle を含む
- **属性的多様性**:
  - `Era` を全種類（Meiji〜Reiwa）
  - `LawType` を全種類
  - `repeal_status` のバリエーション
  - `Article.Num` に枝番（"21_2" 等）
  - `Paragraph.OldStyle=true`
  - `QuoteStruct` を含む
  - `Ruby` / `Sup` / `Sub` を含む

### 10.2 ネガティブテストデータ

- 不正な enum 値（`law_num_era=Edo`）
- 範囲外の日付（`2023-02-30`）
- パストラバーサル（`src=../etc/passwd`）
- SQL インジェクション試行（`order=law_id; DROP TABLE`）
- XSS 試行（`highlight_tag=<script>`）

### 10.3 性能・境界テスト

- 1 法令で `law_node` が数万行を超える大物（民法級）
- 全件取り込み後の `/laws` で `total_count` 約 1 万件
- `keyword` 全件マッチ（例: `第*条`）の応答時間

## 11. 今後の拡張

- **互換性スナップショット**: §11.11 のエッジケース合わせ込みフェーズで実 API レスポンスを録画し、本ケースを補強する。
- **負荷テスト**: 1st リリース範囲外。別途定義予定。
- **セキュリティテスト**: SQL インジェクション・XSS・パストラバーサルは本書に組み込み済み。CSRF / 認証はパブリック API のため対象外。
