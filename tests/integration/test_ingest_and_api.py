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


async def test_health_ingest(client: AsyncClient, ingested: str) -> None:
    """/health/ingest が取り込み状態を集約して返す（C-1 / C-3）。"""
    resp = await client.get("/health/ingest")
    assert resp.status_code == 200
    body = resp.json()
    # フィクスチャ投入で full ラン 1 件が成功している
    assert body["total_runs"] >= 1
    assert body["status"] in {"ok", "stale"}  # 鮮度は実行時刻依存
    assert body["last_run"]["kind"] == "full"
    assert body["last_run"]["status"] == "success"
    assert body["recent_failures"] == 0
    assert body["last_success_at"] is not None


async def test_laws(client: AsyncClient, ingested: str) -> None:
    """/api/2/laws で投入した法令が引ける。"""
    resp = await client.get("/api/2/laws", params={"law_id": "322CO0000000014"})
    body = resp.json()
    assert body["total_count"] == 1
    info = body["laws"][0]["law_info"]
    assert info["law_id"] == "322CO0000000014"
    assert info["law_type"] == "CabinetOrder"
    assert info["promulgation_date"] == "1947-05-03"


async def test_laws_filter_and_order(client: AsyncClient, ingested: str) -> None:
    """/laws の公布日フィルタ・order・asof パラメータが受理され機能する。"""
    # 公布日範囲（フィクスチャは 1947-05-03）に含む
    hit = await client.get(
        "/api/2/laws",
        params={"promulgation_date_from": "1947-01-01", "promulgation_date_to": "1947-12-31"},
    )
    assert hit.status_code == 200
    assert any(it["law_info"]["law_id"] == "322CO0000000014" for it in hit.json()["laws"])
    # 範囲外は除外
    miss = await client.get("/api/2/laws", params={"promulgation_date_from": "2000-01-01"})
    assert all(it["law_info"]["law_id"] != "322CO0000000014" for it in miss.json()["laws"])
    # order（公布日降順）は 200 で受理
    assert (
        await client.get("/api/2/laws", params={"order": "-law_info.promulgation_date"})
    ).status_code == 200
    # asof: 施行(1947-05-03)以降の時点は含み、それ以前は除外（A-2 で enforcement_period を計算）
    after = await client.get("/api/2/laws", params={"asof": "1948-01-01"})
    assert any(it["law_info"]["law_id"] == "322CO0000000014" for it in after.json()["laws"])
    before = await client.get("/api/2/laws", params={"asof": "1900-01-01"})
    assert all(it["law_info"]["law_id"] != "322CO0000000014" for it in before.json()["laws"])


async def test_response_format_xml(client: AsyncClient, ingested: str) -> None:
    """response_format=xml で各エンドポイントが XML 封筒を返す。"""
    laws = await client.get(
        "/api/2/laws", params={"law_id": "322CO0000000014", "response_format": "xml"}
    )
    assert laws.headers["content-type"].startswith("application/xml")
    assert laws.text.startswith("<laws_response>")
    assert "<law_id>322CO0000000014</law_id>" in laws.text

    rev = await client.get(
        "/api/2/law_revisions/322CO0000000014", params={"response_format": "xml"}
    )
    assert rev.text.startswith("<law_revisions_response>")
    assert "<revisions><revision>" in rev.text

    kw = await client.get("/api/2/keyword", params={"keyword": "勅令", "response_format": "xml"})
    assert kw.text.startswith("<keyword_response>")

    data = await client.get(
        f"/api/2/law_data/{ingested}",
        params={"elm": "MainProvision-Paragraph_1", "response_format": "xml"},
    )
    assert data.text.startswith("<law_data_response>")


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


async def test_keyword_boolean_and(client: AsyncClient, ingested: str) -> None:
    """AND 検索: 両語を含むノードのみヒットする。"""
    both = await client.get("/api/2/keyword", params={"keyword": "勅令 AND 政令"})
    assert both.json()["total_count"] >= 1
    missing = await client.get("/api/2/keyword", params={"keyword": "勅令 AND 存在しない語句"})
    assert missing.json()["total_count"] == 0


async def test_keyword_boolean_not(client: AsyncClient, ingested: str) -> None:
    """NOT 検索: 除外語を含むノードは外れる（本文は勅令と政令が同居）。"""
    resp = await client.get("/api/2/keyword", params={"keyword": "勅令 NOT 政令"})
    assert resp.json()["total_count"] == 0


async def test_keyword_wildcard(client: AsyncClient, ingested: str) -> None:
    """ワイルドカード: 勅* が勅令にヒットする。"""
    resp = await client.get("/api/2/keyword", params={"keyword": "勅*"})
    assert resp.json()["total_count"] >= 1


async def test_keyword_facet_law_type(client: AsyncClient, ingested: str) -> None:
    """ファセット（D-2）: 法令種別で絞り込める。"""
    hit = await client.get("/api/2/keyword", params={"keyword": "勅令", "law_type": "CabinetOrder"})
    assert hit.json()["total_count"] >= 1
    miss = await client.get("/api/2/keyword", params={"keyword": "勅令", "law_type": "Act"})
    assert miss.json()["total_count"] == 0


async def test_keyword_facet_asof_and_current(client: AsyncClient, ingested: str) -> None:
    """ファセット（D-2）: asof（施行時点）と current（現行最新）で絞り込める。"""
    after = await client.get("/api/2/keyword", params={"keyword": "勅令", "asof": "1948-01-01"})
    assert after.json()["total_count"] >= 1
    before = await client.get("/api/2/keyword", params={"keyword": "勅令", "asof": "1900-01-01"})
    assert before.json()["total_count"] == 0
    cur = await client.get("/api/2/keyword", params={"keyword": "勅令", "current": "true"})
    assert cur.json()["total_count"] >= 1


async def test_keyword_snippet_length(client: AsyncClient, ingested: str) -> None:
    """スニペット（D-3）: snippet_length 指定でヒット周辺の窓を返しつつハイライトする。"""
    resp = await client.get("/api/2/keyword", params={"keyword": "勅令", "snippet_length": "12"})
    text = resp.json()["items"][0]["sentences"][0]["text"]
    assert "<span>勅令</span>" in text
