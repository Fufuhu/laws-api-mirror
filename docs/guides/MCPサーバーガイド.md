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
| `keyword_search(keyword, limit=20)` | 検索式で全文検索し、該当条文の抜粋を返す | `/api/2/keyword` |
| `search_laws(title=None, law_type=None, limit=20)` | 題名・種別で法令を探す | `/api/2/laws` |
| `list_law_revisions(law_id)` | 法令の改正履歴一覧 | `/api/2/law_revisions/{id}` |
| `get_law_text(law_id, elm=None)` | 法令本文（`elm` で特定条文だけ）を light JSON で取得 | `/api/2/law_data/{id}` |

典型フロー: `keyword_search`/`search_laws` で `law_id` を見つけ → `get_law_text(law_id, elm="MainProvision-Article_9")` で条文を読む。法令が見つからない場合は例外ではなく `{"error": ...}` を返す。

### `keyword_search(keyword, limit=20)`

日本の法令を全文検索する。

- `keyword`: 検索式。AND / OR / NOT・括弧・ワイルドカード（`*` `?`）に対応（§7.1）。
- `limit`: 返す法令件数（既定 20）。
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

`position` は `law_node.path_text`。条文本文の詳細が必要なときは `law_id` を使って別途取得する（将来 `get_law_text` ツールを追加予定）。

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

接続後、`keyword_search` ツールが利用可能になる。

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
