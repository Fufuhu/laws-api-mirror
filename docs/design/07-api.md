## 7. API 設計（v2 互換）

### 7.1 ベースパス

`/api/2/` を維持（e-Gov クライアントがそのまま使えるようにする）。

### 7.2 エンドポイント一覧

| メソッド | パス | 概要 | 実装ノート |
|---|---|---|---|
| GET | `/api/2/laws` | 法令一覧取得 | 14 個のクエリパラメータを Pydantic で受け、`law_revision` を中心に絞り込み |
| GET | `/api/2/law_revisions/{law_id_or_num}` | 法令履歴一覧取得 | `law` をキーに `law_revision` を全件返却 |
| GET | `/api/2/law_data/{law_id_or_num_or_revision_id}` | 法令本文取得（JSON/XML） | `law_xml` から原文 XML を取り出し or `law_node` から再構築。`omit_amendment_suppl_provision=true` は `suppl_type='Amend'` サブツリーを SQL で除外（§11.4）。`json_format=full/light` はインタフェース互換のみ維持し、詳細は最も容易な実装（§10-9 / §11.11）|
| GET | `/api/2/law_file/{file_type}/{law_id_or_num_or_revision_id}` | 法令本文ファイル | **1st リリース対応形式は `xml` / `json` のみ**（§10-3）。`html` / `rtf` / `docx` は **400 Bad Request**。将来追加検討は §11.10。`xml` / `json` は DB から再構築 |
| GET | `/api/2/attachment/{law_revision_id}` | 添付ファイル | `src` 指定で単体返却（S3 / SeaweedFS から fetch して透過プロキシ）、未指定で Zip 一括返却（§11.2）。`include_attached_file_content` で `attached_files_info.image_data` の Base64 同梱可 |
| GET | `/api/2/keyword` | キーワード検索 | pg_bigm + tsvector ハイブリッド検索（§5）→ `law_node` ヒット位置 |

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

