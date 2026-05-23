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

### 1.3 テスト ID 規約

- `TC-<endpoint>-<category>-<seq>` 形式。
  - `endpoint`: `laws` / `rev` / `data` / `file` / `att` / `kw` / `common`
  - `category`: `eq`（同値）/ `bv`（境界値）/ `comb`（組合せ）/ `err`（エラー）/ `compat`（互換性）

## 2. 共通テストケース（全エンドポイント横断）

### 2.1 レスポンス形式（`response_format`）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-common-eq-01 | `response_format=json` | `Content-Type: application/json`、JSON ボディ |
| TC-common-eq-02 | `response_format=xml` | `Content-Type: application/xml`、XML ボディ |
| TC-common-eq-03 | 指定なし、`Accept: application/json` | JSON |
| TC-common-eq-04 | 指定なし、`Accept: application/xml` | XML |
| TC-common-eq-05 | 指定なし、`Accept` ヘッダなし | JSON（既定） |
| TC-common-err-01 | `response_format=yaml` | 400、`code` / `message` を含む `error_info` |
| TC-common-err-02 | `response_format=` (空文字) | 400 |
| TC-common-err-03 | `response_format=JSON`（大文字） | 400（小文字厳格） |

### 2.2 エラーレスポンス形式

| ID | 状況 | 期待結果 |
|---|---|---|
| TC-common-err-10 | 任意の 400 エラー | レスポンスに `error_info {code:str, message:str}` を含む |
| TC-common-err-11 | サーバ内エラー | 500、`error_info` を含む |
| TC-common-err-12 | 存在しないパス `/api/2/unknown` | 404 |
| TC-common-err-13 | HTTP メソッド誤り（POST /api/2/laws） | 405 |

### 2.3 文字エンコーディング

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-common-eq-20 | `law_title=個人情報` (UTF-8 URL エンコード) | 200、絞り込みヒット |
| TC-common-eq-21 | `law_title=` (空文字) | 200、絞り込みなし扱い |
| TC-common-err-20 | `law_title=` に不正な %エスケープ | 400 |

## 3. `/api/2/laws` 法令一覧取得

### 3.1 パラメータ単独の同値クラス

#### `law_id`（部分一致、文字列）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-01 | `law_id=322CO0000000016`（完全一致） | 該当 1 件 |
| TC-laws-eq-02 | `law_id=322CO`（部分一致） | 該当ありで複数件 |
| TC-laws-eq-03 | `law_id=ZZZZZZZZZZZZ`（不存在） | `total_count=0`、`laws=[]` |
| TC-laws-bv-01 | `law_id=`（空文字） | パラメータ無視（絞り込みなし） |
| TC-laws-bv-02 | `law_id` 15 文字（最大長一致） | 最大長で正常動作 |
| TC-laws-bv-03 | `law_id` 16 文字（長すぎ） | パラメータとしては受け付け、ヒットなし |

#### `law_num_era`（enum: Meiji / Taisho / Showa / Heisei / Reiwa）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-10 | `law_num_era=Meiji` | 該当ヒット |
| TC-laws-eq-11 | `law_num_era=Reiwa`（境界・最新元号） | 該当ヒット |
| TC-laws-err-10 | `law_num_era=Edo`（無効） | 400 |
| TC-laws-err-11 | `law_num_era=meiji`（小文字、不正） | 400 |
| TC-laws-err-12 | `law_num_era=`（空文字） | 400 or パラメータ無視（実装方針確認、デフォルトはパラメータ無視） |

#### `law_num_year`（整数）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-bv-10 | `law_num_year=1`（最小） | 200 |
| TC-laws-bv-11 | `law_num_year=99` | 200 |
| TC-laws-bv-12 | `law_num_year=0` | 400 or ヒットなし（正の整数前提） |
| TC-laws-bv-13 | `law_num_year=-1` | 400 |
| TC-laws-bv-14 | `law_num_year=2147483647`（int32 上限） | 200、ヒットなし |
| TC-laws-bv-15 | `law_num_year=2147483648`（int32 オーバー） | 400 |
| TC-laws-err-20 | `law_num_year=abc`（非整数） | 400 |
| TC-laws-err-21 | `law_num_year=1.5`（小数） | 400 |

#### `law_num_type` / `law_num`（部分一致） / `law_num_num`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-20 | `law_num_type=Act` | 法律のみ抽出 |
| TC-laws-eq-21 | `law_num_type=Misc`（最後の enum 値） | 該当ヒット |
| TC-laws-err-30 | `law_num_type=Decree`（無効） | 400 |
| TC-laws-eq-22 | `law_num=昭和二十二年政令第十六号` | 完全一致ヒット |
| TC-laws-eq-23 | `law_num=政令第十六号` | 部分一致ヒット複数 |
| TC-laws-eq-24 | `law_num_num=016` | ヒット |
| TC-laws-eq-25 | `law_num_num=16`（前ゼロなし） | 部分一致でヒット |

#### `law_type`（複数指定可: カンマ区切り）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-30 | `law_type=Act` | 法律のみ |
| TC-laws-eq-31 | `law_type=Act,Rule` | 法律と規則の和集合 |
| TC-laws-eq-32 | `law_type=Act,Act`（重複） | `Act` 単独と同等 |
| TC-laws-err-40 | `law_type=Act,Bogus` | 400 |
| TC-laws-bv-30 | `law_type=` (空文字) | パラメータ無視 or 400（仕様明確化要） |

#### `category_cd`（複数指定、001〜050）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-40 | `category_cd=001`（最小：憲法） | 該当ヒット |
| TC-laws-eq-41 | `category_cd=050`（最大：外事） | 該当ヒット |
| TC-laws-eq-42 | `category_cd=001,002` | 和集合 |
| TC-laws-err-50 | `category_cd=000` | 400 |
| TC-laws-err-51 | `category_cd=051` | 400 |
| TC-laws-err-52 | `category_cd=1`（ゼロ詰めなし、3桁未満） | 400 |
| TC-laws-err-53 | `category_cd=ABC` | 400 |

#### `repeal_status`（複数指定: None / Repeal / Expire / Suspend / LossOfEffectiveness）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-50 | `repeal_status=None` | 廃止等なし法令のみ |
| TC-laws-eq-51 | `repeal_status=Repeal,Expire` | 廃止または失効 |
| TC-laws-err-60 | `repeal_status=Unknown` | 400 |

#### `mission`（New / Partial）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-60 | `mission=New` | 新規制定のみ |
| TC-laws-eq-61 | `mission=New,Partial` | 全件相当 |
| TC-laws-err-70 | `mission=All` | 400 |

#### `asof`（日付）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-70 | `asof=2023-07-01` | 指定時点で有効な履歴 |
| TC-laws-bv-70 | `asof=0001-01-01`（過去極端値） | 200、ヒットなし or 古い時点 |
| TC-laws-bv-71 | `asof=9999-12-31`（未来極端値） | 200、最新履歴を返す |
| TC-laws-bv-72 | `asof=` (空文字) | パラメータ無視 |
| TC-laws-err-80 | `asof=2023/07/01`（区切り文字違い） | 400 |
| TC-laws-err-81 | `asof=2023-13-01`（無効月） | 400 |
| TC-laws-err-82 | `asof=2023-02-30`（無効日） | 400 |
| TC-laws-err-83 | `asof=20230701`（ハイフンなし） | 400 |

#### `promulgation_date_from` / `promulgation_date_to`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-bv-80 | `promulgation_date_from=2023-01-01` のみ | 2023-01-01 以後 |
| TC-laws-bv-81 | `promulgation_date_to=2023-12-31` のみ | 2023-12-31 以前 |
| TC-laws-bv-82 | from=2023-01-01, to=2023-12-31 | 範囲内 |
| TC-laws-bv-83 | from=2023-12-31, to=2023-01-01（逆転） | 200、ヒット 0 件（または 400 と仕様明確化要） |
| TC-laws-bv-84 | from=to=同日 | その日付の法令のみ |
| TC-laws-err-90 | from=2023-01-01, to=2023-13-31 | 400 |

#### `limit`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-bv-90 | `limit=1`（最小） | 1 件、`count=1`、`next_offset=1` |
| TC-laws-bv-91 | `limit=100`（既定） | 既定相当 |
| TC-laws-bv-92 | `limit=0` | 400 or 既定値適用（仕様明確化要、第1候補は 400） |
| TC-laws-bv-93 | `limit=-1` | 400 |
| TC-laws-bv-94 | `limit=2147483647`（int32 上限） | 400 or 上限クリップ（実装方針：上限を内部定数で抑える） |
| TC-laws-bv-95 | `limit=abc` | 400 |

#### `offset`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-bv-100 | `offset=0`（既定・最小） | 1 件目から |
| TC-laws-bv-101 | `offset=total_count - 1` | 末尾 1 件、`next_offset=null` |
| TC-laws-bv-102 | `offset=total_count`（境界外） | `count=0`、`next_offset=null` |
| TC-laws-bv-103 | `offset=-1` | 400 |
| TC-laws-bv-104 | `offset=abc` | 400 |

#### `order`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-110 | `order=law_info.law_id`（既定） | law_id 昇順 |
| TC-laws-eq-111 | `order=+law_info.law_id` | 昇順 |
| TC-laws-eq-112 | `order=-law_info.law_id` | 降順 |
| TC-laws-eq-113 | `order=+law_info.law_id,-revision_info.amendment_promulgate_date` | 複合ソート |
| TC-laws-err-110 | `order=non_existent_field` | 400（ホワイトリスト外） |
| TC-laws-err-111 | `order=law_info.law_id; DROP TABLE` | 400（SQL インジェクション防御） |
| TC-laws-err-112 | `order=`（空文字） | 既定値適用 |

#### `omit_current_revision_info`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-eq-120 | `omit_current_revision_info=true` | レスポンスに `current_revision_info` 含まれず |
| TC-laws-eq-121 | `omit_current_revision_info=false` | 含まれる（既定） |
| TC-laws-err-120 | `omit_current_revision_info=yes` | 400（boolean 厳格） |

### 3.2 組合せテスト

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-laws-comb-01 | `law_title=個人情報` + `law_type=Act` | AND 条件で絞り込み |
| TC-laws-comb-02 | `category_cd=001` + `repeal_status=None` + `asof=2024-01-01` | 3 条件 AND |
| TC-laws-comb-03 | `amendment_law_id` 指定時に `asof` も指定 | `asof` が無視される（API 仕様） |
| TC-laws-comb-04 | パラメータ全指定（網羅） | 200、整合した結果 |

### 3.3 レスポンス形状の確認

| ID | 期待結果 |
|---|---|
| TC-laws-compat-01 | レスポンスに `total_count`, `count`, `next_offset`, `laws` フィールドが必須 |
| TC-laws-compat-02 | `laws[].law_info` に `law_id`, `law_type`, `law_num`, `law_num_era`, `law_num_year`, `law_num_type`, `law_num_num`, `promulgation_date` が含まれる |
| TC-laws-compat-03 | `laws[].revision_info` に v2 仕様のフィールド一式が含まれる |
| TC-laws-compat-04 | `next_offset` は末尾到達時に `null` |

## 4. `/api/2/law_revisions/{law_id_or_num}` 法令履歴一覧取得

### 4.1 パス引数

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-rev-eq-01 | `/law_revisions/322CO0000000016`（law_id 完全一致） | 履歴複数件 |
| TC-rev-eq-02 | `/law_revisions/昭和二十二年政令第十六号`（law_num） | 履歴複数件 |
| TC-rev-eq-03 | `/law_revisions/ZZZ` | 404 or `total_count=0` |
| TC-rev-bv-01 | URL エンコード済み日本語 law_num | デコードして処理 |
| TC-rev-err-01 | パス引数なし `/law_revisions/` | 404 |
| TC-rev-err-02 | パスに `/` を含む不正値 | 404 |

### 4.2 レスポンス

| ID | 期待結果 |
|---|---|
| TC-rev-compat-01 | レスポンスに `law_info`, `revisions[]` が必須 |
| TC-rev-compat-02 | `revisions` は `law_revision_id` 新しい順（降順） |
| TC-rev-compat-03 | 各 `revisions[]` に `law_title`, `amendment_promulgate_date`, `amendment_law_id` 等が含まれる |

## 5. `/api/2/law_data/{law_id_or_num_or_revision_id}` 法令本文取得

### 5.1 パス引数の 3 形式（同値クラス）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-data-eq-01 | `/law_data/411AC0000000127`（law_id） | 最新リビジョンの本文 |
| TC-data-eq-02 | `/law_data/平成十一年法律第百二十七号`（law_num） | 最新リビジョン |
| TC-data-eq-03 | `/law_data/411AC0000000127_19990813_000000000000000`（law_revision_id） | 指定リビジョン |
| TC-data-eq-04 | 存在しない ID | 404 |

### 5.2 `law_full_text_format`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-data-eq-10 | `response_format=json`, `law_full_text_format=json` | `law_full_text` が JSON オブジェクト |
| TC-data-eq-11 | `response_format=json`, `law_full_text_format=xml` | `law_full_text` が **Base64 文字列**（仕様） |
| TC-data-eq-12 | `response_format=xml`, `law_full_text_format=xml` | XML 内に XML |
| TC-data-eq-13 | `response_format=xml`, `law_full_text_format=json` | `law_full_text` が **Base64 文字列** |
| TC-data-err-10 | `law_full_text_format=yaml` | 400 |

### 5.3 `json_format`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-data-eq-20 | `json_format=full`（既定） | `{tag, attr, children}` ツリー |
| TC-data-eq-21 | `json_format=light` | `{TagName: value or array}` 形 |
| TC-data-err-20 | `json_format=medium` | 400 |
| TC-data-compat-20 | `json_format=light` で `Ruby` がベーステキストのみで埋め込まれる（§11.11 の 1st 実装） | 仕様どおり |

### 5.4 `elm`（要素絞り込み）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-data-eq-30 | `elm=MainProvision` | 本則全体 |
| TC-data-eq-31 | `elm=MainProvision-Article_21` | 第 21 条全体 |
| TC-data-eq-32 | `elm=MainProvision-Article_21-Paragraph_3` | 第 21 条第 3 項 |
| TC-data-eq-33 | `elm=MainProvision-Article_21_2`（枝番） | 第 21 条の 2 |
| TC-data-eq-34 | `elm=SupplProvision[1]` | 1 つ目の附則 |
| TC-data-bv-30 | `elm=`（空文字） | 全文 |
| TC-data-bv-31 | `elm=NonExistent` | 200、`law_full_text` 空 or 404（仕様明確化要） |
| TC-data-err-30 | `elm=MainProvision/Article_21`（区切り誤り） | 400 |
| TC-data-err-31 | `elm=MainProvision-Article_21; DROP` | 400（インジェクション防御） |

### 5.5 `asof` / `omit_amendment_suppl_provision` / `include_attached_file_content`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-data-eq-40 | `asof=2020-01-01` | 当時のリビジョン |
| TC-data-eq-41 | path に `law_revision_id` 指定 + `asof` 指定 | `asof` 無視（API 仕様） |
| TC-data-eq-42 | `omit_amendment_suppl_provision=true` | 改正附則を除外（`suppl_type='Amend'`） |
| TC-data-eq-43 | `include_attached_file_content=true` | `attached_files_info.image_data` に Base64 |
| TC-data-eq-44 | `include_attached_file_content=false`（既定） | `image_data` 空 |

## 6. `/api/2/law_file/{file_type}/{law_id_or_num_or_revision_id}` 法令本文ファイル取得

### 6.1 `file_type`（1st リリースは xml / json のみ）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-file-eq-01 | `/law_file/xml/{id}` | XML ファイルバイナリ |
| TC-file-eq-02 | `/law_file/json/{id}` | JSON ファイルバイナリ |
| TC-file-err-01 | `/law_file/html/{id}` | **400**（1st リリース非対応、§10-3） |
| TC-file-err-02 | `/law_file/rtf/{id}` | **400** |
| TC-file-err-03 | `/law_file/docx/{id}` | **400** |
| TC-file-err-04 | `/law_file/pdf/{id}` | **400** |
| TC-file-err-05 | `/law_file/XML/{id}`（大文字） | 400 |
| TC-file-err-06 | `/law_file//{id}`（空） | 404 |

### 6.2 ID 解決

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-file-eq-10 | 各 ID 形式（law_id / law_num / law_revision_id） | 200 |
| TC-file-err-10 | 不存在 ID | 404 |

### 6.3 `asof`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-file-eq-20 | `asof=2023-04-01` | 当時の本文ファイル |
| TC-file-eq-21 | path に `law_revision_id` + `asof` | `asof` 無視 |

## 7. `/api/2/attachment/{law_revision_id}` 添付ファイル取得

### 7.1 `src` 指定/未指定の同値クラス

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-att-eq-01 | `src=./pict/M06SE065-001.jpg` | 単体 JPG バイナリ |
| TC-att-eq-02 | `src=./pict/sample.pdf` | 単体 PDF バイナリ |
| TC-att-eq-03 | `src` 未指定 | Zip 一括返却 |
| TC-att-err-01 | 不存在の `src` | 404 |
| TC-att-err-02 | 不存在の `law_revision_id` | 404 |
| TC-att-err-03 | `src=../etc/passwd`（パストラバーサル） | 400 |
| TC-att-err-04 | `src` に NULL バイト | 400 |

### 7.2 Content-Type

| ID | 期待結果 |
|---|---|
| TC-att-compat-01 | JPG → `image/jpeg` |
| TC-att-compat-02 | PDF → `application/pdf` |
| TC-att-compat-03 | Zip 一括 → `application/zip` |

## 8. `/api/2/keyword` キーワード検索

### 8.1 `keyword` 必須・形式

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-eq-01 | `keyword=デジタル庁` | 該当条文一覧 |
| TC-kw-bv-01 | `keyword=`（空文字） | 400 |
| TC-kw-err-01 | `keyword` 未指定 | 400 |
| TC-kw-bv-02 | `keyword` 1 文字（例: `庁`） | 200。pg_bigm では bigram にならず LIKE フォールバック（§5）|
| TC-kw-bv-03 | `keyword` 2 文字 | 200、bigram で索引利用 |
| TC-kw-bv-04 | `keyword` 1000 文字（極端長） | 200 or 414 URI too long |

### 8.2 検索式（AND / OR / NOT）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-eq-10 | `keyword=情報 公開`（AND） | 両方含む |
| TC-kw-eq-11 | `keyword=情報公開\|個人情報`（OR） | いずれか含む |
| TC-kw-eq-12 | `keyword=情報 !個人情報`（NOT） | 「情報」を含み「個人情報」を含まない |
| TC-kw-eq-13 | `keyword=(情報 公開)\|個人`（複合） | 仕様どおり |

### 8.3 ワイルドカード（pg_bigm 経路）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-eq-20 | `keyword=第*条` | 「第○○条」を含む条文 |
| TC-kw-eq-21 | `keyword=第?条` | 1 文字ワイルドカード |
| TC-kw-eq-22 | `keyword=であって*として*定める` | 連続ワイルドカード |
| TC-kw-err-20 | `keyword=*` のみ | 400 or 全件マッチ（仕様明確化要） |
| TC-kw-err-21 | ワイルドカードと AND/OR の組合せ（仕様外） | 400（API ドキュメントで「組合せ不可」と明記） |

### 8.4 `limit` / `sentences_limit` / `sentence_text_size` / `offset`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-bv-30 | `limit=1` | 1 件 |
| TC-kw-bv-31 | `limit=1000`（仕様上限） | 1000 件 |
| TC-kw-bv-32 | `limit=1001` | 400 or 1000 にクリップ |
| TC-kw-bv-33 | `limit=0` | 400 |
| TC-kw-bv-34 | `sentences_limit=5` + `limit=100` | sentences は 5 まで |
| TC-kw-bv-35 | `sentences_limit > limit` | `limit` 優先（仕様） |
| TC-kw-bv-36 | `sentence_text_size=20` | text 表示 20 文字 |
| TC-kw-bv-37 | `sentence_text_size=0` | 400 or 既定値適用 |
| TC-kw-bv-38 | `offset` 境界（共通仕様準拠） | TC-laws-bv-100〜104 と同様 |

### 8.5 `highlight_tag`

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-eq-40 | `highlight_tag=em` | `<em>...</em>` で囲む |
| TC-kw-eq-41 | `highlight_tag=`（既定） | `<span>...</span>` |
| TC-kw-err-40 | `highlight_tag=<script>` | エスケープ or 400（XSS 防御） |
| TC-kw-err-41 | `highlight_tag=div onclick="..."` | 400 |

### 8.6 法令絞り込み（laws と共通）

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-kw-comb-01 | `keyword=情報 公開` + `law_type=Act` | 法律のみから検索 |
| TC-kw-comb-02 | `keyword=デジタル` + `asof=2024-01-01` | 当時の法令本文を対象 |
| TC-kw-comb-03 | `keyword=情報` + `category_cd=001,002` | 分類絞り込み |

### 8.7 レスポンス形状

| ID | 期待結果 |
|---|---|
| TC-kw-compat-01 | レスポンスに `total_count`, `sentence_count`, `next_offset`, `items` |
| TC-kw-compat-02 | `items[].sentences[].position` は `law_node.path_text` 形式 |
| TC-kw-compat-03 | `items[].sentences[].text` にハイライトタグが埋め込まれる |
| TC-kw-compat-04 | XML レスポンス時はハイライトタグがエスケープされる（仕様） |

## 9. 1st リリース非対応事項のテスト

| ID | 入力 | 期待結果 |
|---|---|---|
| TC-scope-err-01 | `/law_file/html/...` | 400（§10-3）|
| TC-scope-err-02 | `/law_file/rtf/...` | 400 |
| TC-scope-err-03 | `/law_file/docx/...` | 400 |
| TC-scope-compat-01 | `Cache-Control` ヘッダ未設定 or `no-store` | レスポンスキャッシュ非対応（§10-4）|

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
