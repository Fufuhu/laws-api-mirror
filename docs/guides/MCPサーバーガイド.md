# 法令検索 MCP サーバーガイド

AI アシスタント（Claude 等）から日本の法令を全文検索できるようにする MCP（Model Context Protocol）サーバーの使い方。実装は `src/laws_api_mirror/mcp_server.py`。

## 構成

稼働中の FastAPI（`/api/2/keyword`）を HTTP 経由で呼ぶ**薄いプロキシ**として動く。

```
Claude 等 ──(MCP: Streamable HTTP)──▶ laws-mcp (127.0.0.1:8765/mcp)
                                          └─(HTTP)→ FastAPI /api/2/keyword → PostgreSQL
```

- **トランスポート**: Streamable HTTP（`/mcp`）。
- **再利用**: 検索・取得ロジックは FastAPI 側を流用（MCP は要約のみ担当）。
- 「**探す → 絞る → 取る**」を意識し、本文全体ではなく必要十分な情報に絞って返す。

## 公開ツール

| ツール | 用途 | 叩く API |
|---|---|---|
| `keyword_search(keyword, limit=20, law_type=None, category_cd=None, asof=None, current=False)` | 検索式で全文検索し、該当条文の抜粋を返す（関連度順・ファセット絞り込み） | `/api/2/keyword` |
| `search_laws(title=None, law_type=None, limit=20, category_cd=None, asof=None, current=False)` | 題名・種別・分類・時点で法令を探す | `/api/2/laws` |
| `list_law_revisions(law_id)` | 法令の改正履歴一覧（現行最新フラグ・状態・改正法令ID つき） | `/api/2/law_revisions/{id}` |
| `get_law_text(law_id, elm=None, asof=None)` | 法令本文（`elm` で特定条文・`asof` で時点指定）を light JSON で取得 | `/api/2/law_data/{id}` |

典型フロー: `keyword_search`/`search_laws` で `law_id` を見つけ → `get_law_text(law_id, elm="MainProvision-Article_9")` で条文を読む。法令が見つからない場合は例外ではなく `{"error": ...}` を返す。

時点指定（`asof`）と `current=True` を使うと、過去・将来・現行の各版の条文を読み分けられる（A-2 の施行期間に基づく）。`list_law_revisions` の `is_current_latest` で現行版の `law_revision_id` を確認してから `get_law_text` に渡してもよい。

### `keyword_search(keyword, limit=20, law_type=None, category_cd=None, asof=None, current=False)`

日本の法令を全文検索する。

- `keyword`: 検索式。AND / OR / NOT・括弧・ワイルドカード（`*` `?`）に対応（§7.1）。
- `limit`: 返す法令件数（既定 20）。結果は**ヒット文数の多い順（関連度順）**。
- `law_type` / `category_cd`: 法令種別・事項別分類コード（`"1".."50"`）で絞り込む。
- `asof`（YYYY-MM-DD）: その日に施行されていた版に限定する。`current=True` は現在施行中の版のみ。
- 返り値（**本文全体ではなく抜粋**を返してトークンを節約）:

```json
{
  "total_count": 1,
  "sentence_count": 1,
  "results": [
    {
      "law_id": "321CONSTITUTION",
      "law_title": "日本国憲法",
      "law_num": "昭和二十一年憲法",
      "sentences": [
        {"position": "MainProvision-Chapter_2-ChapterTitle", "text": "第二章　<span>戦争の放棄</span>"}
      ]
    }
  ]
}
```

`position` は `law_node.path_text`。条文本文の詳細が必要なときは `law_id` と `position`（＝`elm`）を `get_law_text` に渡して取得する。

## 起動手順

```sh
# 1. データ取り込み済みの FastAPI を起動（接続先は api_base_url）
uv run uvicorn laws_api_mirror.api.app:app          # http://127.0.0.1:8000

# 2. MCP サーバーを起動
uv run laws-mcp                                     # http://127.0.0.1:8765/mcp
```

起動すると Uvicorn が `mcp_host:mcp_port` で待受し、`/mcp` で Streamable HTTP を提供する。
非 MCP の素の HTTP リクエストには `406 Not Acceptable` を返す（プロトコル検証）。

## MCP クライアントからの接続

Streamable HTTP に対応した MCP クライアント（Claude Desktop / Claude Code 等）から、
URL `http://127.0.0.1:8765/mcp` を MCP サーバーとして登録する。設定例（クライアント側の
MCP サーバー定義、HTTP 型）:

```json
{
  "mcpServers": {
    "laws-api-mirror": { "url": "http://127.0.0.1:8765/mcp" }
  }
}
```

### Claude Code（CLI）での登録

Claude Code では `claude mcp add` で HTTP 型として登録する（MCP サーバーが稼働している前提）:

```sh
# 自分だけが使う（既定: local スコープ＝このマシンのこのプロジェクトのみ）
claude mcp add --transport http laws-api-mirror http://127.0.0.1:8765/mcp

# チームで共有する（project スコープ＝リポジトリ直下の .mcp.json に書き出す。コミットして共有）
claude mcp add --transport http --scope project laws-api-mirror http://127.0.0.1:8765/mcp

# 自分の全プロジェクトで使う（user スコープ）
claude mcp add --transport http --scope user laws-api-mirror http://127.0.0.1:8765/mcp
```

登録内容の確認・削除:

```sh
claude mcp list                 # 登録済みサーバーと接続状態
claude mcp get laws-api-mirror  # 詳細（URL・トランスポート・スコープ）
claude mcp remove laws-api-mirror
```

Claude Code のセッション内では `/mcp` で接続状態と公開ツール一覧を確認できる。

接続後、`keyword_search` / `search_laws` / `list_law_revisions` / `get_law_text` の 4 ツールが利用可能になる。

## 設定（環境変数 / `.env`）

| 環境変数 | 既定 | 用途 |
|---|---|---|
| `API_BASE_URL` | `http://127.0.0.1:8000` | MCP ツールが叩く FastAPI のベース URL |
| `MCP_HOST` | `127.0.0.1` | MCP サーバーの待受ホスト |
| `MCP_PORT` | `8765` | MCP サーバーの待受ポート（FastAPI と別ポート） |

## 前提・制約

- **FastAPI と取り込み済み PostgreSQL が必要**（MCP 単体では検索できない）。
- 認証は未設定（ローカル利用前提）。リモート公開時は MCP の OAuth / 経路上の認可を別途検討。

## 今後の拡張候補

- `get_law_outline(law_id)`: 章・節・条の見出しだけを返すナビ用ツール（`law_node` の構造クエリ。専用 API エンドポイントの追加が前提）。
- `get_law_text` のプレーンテキスト出力モード（単一条文を読む用途で light JSON より簡潔に）。
- リモート公開時の認証（MCP OAuth）。
