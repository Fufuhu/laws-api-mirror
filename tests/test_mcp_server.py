"""MCP 検索ツール（FastAPI プロキシ＋要約）の単体テスト。

FastAPI 呼び出しは httpx.MockTransport で差し替える（実サーバー不要）。
"""

from __future__ import annotations

import httpx

from laws_api_mirror.mcp_server import search_via_api

# /api/2/keyword の代表レスポンス
_KEYWORD_RESPONSE = {
    "total_count": 1,
    "sentence_count": 1,
    "next_offset": None,
    "items": [
        {
            "law_info": {"law_id": "321CONSTITUTION", "law_num": "昭和二十一年憲法"},
            "revision_info": {"law_revision_id": "321CONSTITUTION_x", "law_title": "日本国憲法"},
            "sentences": [
                {
                    "position": "MainProvision-Chapter_2-ChapterTitle",
                    "text": "第二章　<span>戦争の放棄</span>",
                }
            ],
        }
    ],
}


async def test_search_via_api_summarizes() -> None:
    """keyword 検索を呼び、AI 向けに要約した形（id/題名/抜粋）で返す。"""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=_KEYWORD_RESPONSE)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        result = await search_via_api("戦争の放棄", 20, client=client)

    assert "/api/2/keyword" in captured["url"]
    assert "keyword=" in captured["url"]
    assert result["total_count"] == 1
    assert result["sentence_count"] == 1
    item = result["results"][0]
    assert item["law_id"] == "321CONSTITUTION"
    assert item["law_title"] == "日本国憲法"
    assert item["law_num"] == "昭和二十一年憲法"
    assert "<span>戦争の放棄</span>" in item["sentences"][0]["text"]
    # 冗長な law_info/revision_info 全体は含めない（トークン節約）
    assert set(item) == {"law_id", "law_title", "law_num", "sentences"}
