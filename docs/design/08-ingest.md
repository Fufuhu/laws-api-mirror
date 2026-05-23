## 8. 取り込みパイプライン

```
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│  Downloader      │ → │  XML Parser      │ → │  Loader (UPSERT) │
│ bulkdownload zip │   │ lxml.iterparse   │   │ law / law_revision│
└──────────────────┘   └──────────────────┘   │ law_xml / law_node│
                                              │ attached_file    │
                                              └──────┬───────────┘
                                                     │ (バイナリ)
                                                     ↓
                                              ┌──────────────────┐
                                              │ Object Storage   │
                                              │ S3 / S3互換       │
                                              └──────────────────┘
                                                     ↓
                                              ┌──────────────────┐
                                              │ Search Indexer   │
                                              │ pg_bigm + tsvector│
                                              └──────────────────┘
```

- 全件取り込み: `file_section=1` の Zip をローカルに展開 → 法令ごとに XML → DB UPSERT。
- 差分取り込み: 日次で `file_section=3&update_date=YYYYMMDD` を取得（過去 3 か月のみ参照可）。
- **UPSERT キー**は `law_revision_id`。同一 ID で `xml_sha256` が変化したら更新。
- **トランザクション境界**は「1 法令リビジョン = 1 トランザクション」を基本とし、失敗を局所化する。
- `law_node` の挿入は子要素が大量（数万行）になり得るので `COPY` を使う。
- **添付ファイル**: 取り込み中に Zip から抽出したバイナリは `sha256` で重複排除しつつ S3 (／互換) にアップロードし、`attached_file` 行を UPSERT する。DB トランザクションコミット前に S3 PUT が成功している前提で、失敗時は `attached_file` 行を作らず再試行可能にする。

