"""法令検索の MCP サーバー（Streamable HTTP）。

AI アシスタント（Claude 等）から日本の法令を検索・取得できるようツールを公開する。
実体は稼働中の FastAPI（`/api/2/...`）を HTTP 経由で呼ぶ薄いプロキシで、AI 向けに
要約（必要十分な情報に絞る）してトークンを節約する。

公開ツール（探す → 絞る → 取る）:

- ``keyword_search``: 検索式で全文検索し、該当条文の抜粋を返す。
- ``search_laws``: 題名・種別で法令を探す。
- ``list_law_revisions``: 法令の履歴一覧。
- ``get_law_text``: 法令本文（``elm`` で特定の条文だけ）を取得する。

起動:
    laws-mcp                      # http://{mcp_host}:{mcp_port}/mcp で待受
前提:
    FastAPI を別途起動しておく（接続先は settings.api_base_url）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from laws_api_mirror.core.config import settings

mcp = FastMCP("laws-api-mirror", host=settings.mcp_host, port=settings.mcp_port)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=settings.api_base_url, timeout=30.0)


def _today_iso() -> str:
    return datetime.now(UTC).date().isoformat()


# --- FastAPI 呼び出し本体（テストで client を差し替えられるよう分離） ---


async def search_via_api(
    keyword: str,
    limit: int,
    *,
    law_type: str | None = None,
    category_cd: str | None = None,
    asof: str | None = None,
    current: bool = False,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"keyword": keyword, "limit": limit}
    if law_type:
        params["law_type"] = law_type
    if category_cd:
        params["category_cd"] = category_cd
    if asof:
        params["asof"] = asof
    if current:
        params["current"] = "true"
    response = await client.get("/api/2/keyword", params=params)
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


async def laws_via_api(
    *,
    title: str | None,
    law_type: str | None,
    limit: int,
    category_cd: str | None = None,
    asof: str | None = None,
    current: bool = False,
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    params: dict[str, str | int] = {"limit": limit}
    if title:
        params["law_title"] = title
    if law_type:
        params["law_type"] = law_type
    if category_cd:
        params["category_cd"] = category_cd
    if asof:
        params["asof"] = asof
    if current:
        # /laws は asof で時点を選ぶ。current は「本日時点」の糖衣として扱う。
        params.setdefault("asof", _today_iso())
    response = await client.get("/api/2/laws", params=params)
    response.raise_for_status()
    data = response.json()
    return {
        "total_count": data["total_count"],
        "next_offset": data["next_offset"],
        "results": [
            {
                "law_id": item["law_info"]["law_id"],
                "law_title": item["revision_info"]["law_title"],
                "law_num": item["law_info"]["law_num"],
                "law_type": item["law_info"]["law_type"],
                "promulgation_date": item["law_info"]["promulgation_date"],
            }
            for item in data["laws"]
        ],
    }


async def revisions_via_api(law_id: str, *, client: httpx.AsyncClient) -> dict[str, Any]:
    response = await client.get(f"/api/2/law_revisions/{law_id}")
    if response.status_code == 404:
        return {"error": "法令が見つかりません", "law_id": law_id}
    response.raise_for_status()
    data = response.json()
    return {
        "law_id": data["law_info"]["law_id"],
        "revisions": [
            {
                "law_revision_id": rev["law_revision_id"],
                "law_title": rev["law_title"],
                "amendment_enforcement_date": rev.get("amendment_enforcement_date"),
                # AI が「どの版を読むべきか」を選べるよう、現行判定・状態・改正法令を含める
                "is_current_latest": rev.get("is_current_latest"),
                "current_revision_status": rev.get("current_revision_status"),
                "amendment_law_id": rev.get("amendment_law_id"),
            }
            for rev in data["revisions"]
        ],
    }


async def law_text_via_api(
    identifier: str, elm: str | None, *, asof: str | None = None, client: httpx.AsyncClient
) -> dict[str, Any]:
    params: dict[str, str] = {"law_full_text_format": "json", "json_format": "light"}
    if elm:
        params["elm"] = elm
    if asof:
        # identifier が法令ID/法令番号のとき、施行期間が当該日を含む版を返す。
        params["asof"] = asof
    response = await client.get(f"/api/2/law_data/{identifier}", params=params)
    if response.status_code == 404:
        return {"error": "法令または elm が見つかりません", "id": identifier, "elm": elm}
    response.raise_for_status()
    data = response.json()
    return {
        "law_id": data["law_info"]["law_id"],
        "law_title": data["revision_info"]["law_title"],
        "law_revision_id": data["revision_info"]["law_revision_id"],
        "elm": elm,
        "content": data["law_full_text"],
    }


# --- MCP ツール ---


@mcp.tool()
async def keyword_search(
    keyword: str,
    limit: int = 20,
    law_type: str | None = None,
    category_cd: str | None = None,
    asof: str | None = None,
    current: bool = False,
) -> dict[str, Any]:
    """日本の法令を全文検索する。

    keyword は AND / OR / NOT・括弧・ワイルドカード(* ?)に対応した検索式。
    ヒットした法令（法令ID・題名・法令番号）と、該当した条文の抜粋（<span> で
    ハイライト）を返す。結果はヒット文数の多い順（関連度順）。本文全体ではなく抜粋を返す。

    絞り込み:
    - law_type: 法令種別（Constitution / Act / CabinetOrder など）。
    - category_cd: 事項別分類コード（"1".."50"）。
    - asof: 時点（YYYY-MM-DD）。その日に施行されていた版に限定する。
    - current: True で現在施行中の版のみに限定する。
    """
    async with _client() as client:
        return await search_via_api(
            keyword,
            limit,
            law_type=law_type,
            category_cd=category_cd,
            asof=asof,
            current=current,
            client=client,
        )


@mcp.tool()
async def search_laws(
    title: str | None = None,
    law_type: str | None = None,
    limit: int = 20,
    category_cd: str | None = None,
    asof: str | None = None,
    current: bool = False,
) -> dict[str, Any]:
    """法令を題名（部分一致）や種別で探し、一覧（法令ID・題名・番号）を返す。

    law_type 例: Constitution / Act / CabinetOrder / MinisterialOrdinance など。
    category_cd は事項別分類コード（"1".."50"）。asof（YYYY-MM-DD）でその時点に施行
    されていた版に、current=True で現在施行中の版に限定する。
    返ってきた law_id を get_law_text / list_law_revisions に渡して詳細を取得する。
    """
    async with _client() as client:
        return await laws_via_api(
            title=title,
            law_type=law_type,
            limit=limit,
            category_cd=category_cd,
            asof=asof,
            current=current,
            client=client,
        )


@mcp.tool()
async def list_law_revisions(law_id: str) -> dict[str, Any]:
    """指定した法令（law_id または法令番号）の改正履歴（リビジョン）一覧を返す。

    各リビジョンには施行日・現行最新フラグ（is_current_latest）・状態・改正法令IDを
    含むので、「今どの版が施行中か」「特定時点の版」を判断して law_revision_id を
    get_law_text に渡せる。
    """
    async with _client() as client:
        return await revisions_via_api(law_id, client=client)


@mcp.tool()
async def get_law_text(
    law_id: str, elm: str | None = None, asof: str | None = None
) -> dict[str, Any]:
    """法令本文を取得する（JSON light）。

    law_id は法令ID / 法令番号 / リビジョンID のいずれか。``elm`` を指定すると特定の
    要素だけを返す（例 ``MainProvision-Chapter_2-Article_9`` で第9条）。法令全体は
    大きいので、条文を読むときは elm で範囲を絞ること。

    ``asof``（YYYY-MM-DD）を指定すると、law_id が法令ID/法令番号のとき、その日に
    施行されていた版の本文を返す（リビジョンID 直接指定時は無視）。過去・将来の条文を
    読むときに使う。
    """
    async with _client() as client:
        return await law_text_via_api(law_id, elm, asof=asof, client=client)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
