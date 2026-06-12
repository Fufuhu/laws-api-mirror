"""取り込み（bootstrap）と 4 つの互換 API の統合テスト（実 PostgreSQL）。

``database_url`` / ``ingested`` フィクスチャ（conftest.py）に依存し、Docker と
カスタム PG イメージが無い環境では自動スキップされる。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from laws_api_mirror.api.app import app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_db(client: AsyncClient, database_url: str) -> None:
    """/health/db が実 DB に対して 200 を返す。"""
    resp = await client.get("/health/db")
    assert resp.status_code == 200
    assert resp.json() == {"database": "ok"}


async def test_laws(client: AsyncClient, ingested: str) -> None:
    """/api/2/laws で投入した法令が引ける。"""
    resp = await client.get("/api/2/laws", params={"law_id": "322CO0000000014"})
    body = resp.json()
    assert body["total_count"] == 1
    info = body["laws"][0]["law_info"]
    assert info["law_id"] == "322CO0000000014"
    assert info["law_type"] == "CabinetOrder"
    assert info["promulgation_date"] == "1947-05-03"


async def test_law_revisions(client: AsyncClient, ingested: str) -> None:
    """/api/2/law_revisions で履歴が引ける。"""
    resp = await client.get("/api/2/law_revisions/322CO0000000014")
    body = resp.json()
    assert body["law_info"]["law_id"] == "322CO0000000014"
    assert body["revisions"][0]["law_revision_id"] == ingested


async def test_law_data_elm(client: AsyncClient, ingested: str) -> None:
    """/api/2/law_data で elm サブツリーを JSON で取得できる。"""
    resp = await client.get(
        f"/api/2/law_data/{ingested}",
        params={"elm": "MainProvision-Paragraph_1", "law_full_text_format": "json"},
    )
    full = resp.json()["law_full_text"]
    assert full["tag"] == "Paragraph"
    assert full["attr"]["Num"] == "1"


async def test_law_data_full_root_is_law(client: AsyncClient, ingested: str) -> None:
    """elm なしは root=Law を返す。"""
    resp = await client.get(f"/api/2/law_data/{ingested}")
    assert resp.json()["law_full_text"]["tag"] == "Law"


async def test_keyword(client: AsyncClient, ingested: str) -> None:
    """/api/2/keyword でハイブリッド検索＋ハイライトが効く。"""
    resp = await client.get("/api/2/keyword", params={"keyword": "勅令"})
    body = resp.json()
    assert body["total_count"] >= 1
    assert body["sentence_count"] >= 1
    text = body["items"][0]["sentences"][0]["text"]
    assert "<span>勅令</span>" in text


async def test_law_data_not_found(client: AsyncClient, database_url: str) -> None:
    """存在しない id は 404。"""
    resp = await client.get("/api/2/law_data/NONEXISTENT")
    assert resp.status_code == 404


async def test_law_file_xml(client: AsyncClient, ingested: str) -> None:
    """/api/2/law_file/xml は原文 XML をファイルとして返す。"""
    resp = await client.get(f"/api/2/law_file/xml/{ingested}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text.lstrip().startswith("<?xml")
    assert "勅令" in resp.text


async def test_law_file_json(client: AsyncClient, ingested: str) -> None:
    """/api/2/law_file/json は JSON ツリーをファイルとして返す。"""
    resp = await client.get(f"/api/2/law_file/json/{ingested}")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["tag"] == "Law"


async def test_law_file_unsupported_format(client: AsyncClient, ingested: str) -> None:
    """html / rtf / docx は 400（§10-3）。"""
    for file_type in ("html", "rtf", "docx"):
        resp = await client.get(f"/api/2/law_file/{file_type}/{ingested}")
        assert resp.status_code == 400
