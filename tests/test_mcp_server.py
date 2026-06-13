"""MCP 検索ツール（FastAPI プロキシ＋要約）の単体テスト。

FastAPI 呼び出しは httpx.MockTransport で差し替える（実サーバー不要）。
"""

from __future__ import annotations

from collections.abc import Callable

import httpx

from laws_api_mirror.mcp_server import (
    law_text_via_api,
    laws_via_api,
    revisions_via_api,
    search_via_api,
)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test")


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


async def test_laws_via_api_summarizes() -> None:
    """search_laws: 題名/種別の絞り込みを渡し、簡潔な一覧で返す。"""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "total_count": 1,
                "count": 1,
                "next_offset": None,
                "laws": [
                    {
                        "law_info": {
                            "law_id": "321CONSTITUTION",
                            "law_num": "昭和二十一年憲法",
                            "law_type": "Constitution",
                            "promulgation_date": "1946-11-03",
                        },
                        "revision_info": {"law_title": "日本国憲法"},
                    }
                ],
            },
        )

    async with _client(handler) as client:
        result = await laws_via_api(title="憲法", law_type="Constitution", limit=20, client=client)

    assert "law_title=" in captured["url"] and "law_type=Constitution" in captured["url"]
    assert result["total_count"] == 1
    item = result["results"][0]
    assert item["law_id"] == "321CONSTITUTION"
    assert item["law_type"] == "Constitution"
    assert item["promulgation_date"] == "1946-11-03"


async def test_revisions_via_api() -> None:
    """list_law_revisions: 履歴を簡潔に返す。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "law_info": {"law_id": "X"},
                "revisions": [
                    {
                        "law_revision_id": "X_r1",
                        "law_title": "法A",
                        "amendment_enforcement_date": None,
                    }
                ],
            },
        )

    async with _client(handler) as client:
        result = await revisions_via_api("X", client=client)
    assert result["law_id"] == "X"
    assert result["revisions"][0]["law_revision_id"] == "X_r1"


async def test_revisions_via_api_not_found() -> None:
    """404 はエラーオブジェクトとして返す（例外にしない）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "not found"})

    async with _client(handler) as client:
        result = await revisions_via_api("NONE", client=client)
    assert result["error"] and result["law_id"] == "NONE"


async def test_law_text_via_api_with_elm() -> None:
    """get_law_text: elm を渡し、light 本文を content に入れて返す。"""
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "attached_files_info": None,
                "law_info": {"law_id": "321CONSTITUTION"},
                "revision_info": {
                    "law_revision_id": "321CONSTITUTION_x",
                    "law_title": "日本国憲法",
                },
                "law_full_text": {"Article": [{"ArticleTitle": "第九条"}]},
            },
        )

    async with _client(handler) as client:
        result = await law_text_via_api("321CONSTITUTION", "MainProvision-Article_9", client=client)

    assert "json_format=light" in captured["url"]
    assert "elm=" in captured["url"]
    assert result["law_id"] == "321CONSTITUTION"
    assert result["elm"] == "MainProvision-Article_9"
    assert result["content"] == {"Article": [{"ArticleTitle": "第九条"}]}
