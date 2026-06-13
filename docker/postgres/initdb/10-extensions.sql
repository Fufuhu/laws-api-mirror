-- 初回 initdb 時に POSTGRES_DB に対して実行される（/docker-entrypoint-initdb.d）。
-- 法令データの取り込み・検索に必要な拡張を有効化する。
--   - ltree:   elm パス解決（設計 §4.7.1）
--   - pg_bigm: 全文検索の bigram インデックス（設計 §5）
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pg_bigm;
