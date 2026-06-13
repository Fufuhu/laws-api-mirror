"""法令検索の MCP サーバー（Streamable HTTP）。

AI アシスタント（Claude 等）から日本の法令を全文検索できるよう、検索ツールを 1 つ
公開する。実体は稼働中の FastAPI（`/api/2/keyword`）を HTTP 経由で呼ぶ薄いプロキシ。

起動:
    laws-mcp                      # http://{mcp_host}:{mcp_port}/mcp で待受
前提:
    FastAPI を別途起動しておく（uvicorn laws_api_mirror.api.app:app）。
    接続先は settings.api_base_url（既定 http://127.0.0.1:8000）。
"""

from __future__ import annotations

from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from laws_api_mirror.core.config import settings

mcp = FastMCP("laws-api-mirror", host=settings.mcp_host, port=settings.mcp_port)


async def search_via_api(keyword: str, limit: int, *, client: httpx.AsyncClient) -> dict[str, Any]:
    """FastAPI の /api/2/keyword を呼び、AI 向けに要約した結果を返す。"""
    response = await client.get("/api/2/keyword", params={"keyword": keyword, "limit": limit})
    response.raise_for_status()
    data = response.json()
    return {
        "total_count": data["total_count"],
        "sentence_count": data["sentence_count"],
        "results": [
            {
                "law_id": item["law_info"]["law_id"],
                "law_title": item["revision_info"]["law_title"],
                "law_num": item["law_info"]["law_num"],
                "sentences": [
                    {"position": s["position"], "text": s["text"]} for s in item["sentences"]
                ],
            }
            for item in data["items"]
        ],
    }


@mcp.tool()
async def keyword_search(keyword: str, limit: int = 20) -> dict[str, Any]:
    """日本の法令を全文検索する。

    keyword は AND / OR / NOT・括弧・ワイルドカード(* ?)に対応した検索式。
    ヒットした法令（法令ID・題名・法令番号）と、該当した条文の抜粋（<span> で
    ハイライト）を返す。本文全体ではなく抜粋を返すため、必要なら法令IDで個別取得する。
    """
    async with httpx.AsyncClient(base_url=settings.api_base_url, timeout=30.0) as client:
        return await search_via_api(keyword, limit, client=client)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
