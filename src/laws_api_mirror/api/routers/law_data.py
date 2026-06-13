"""法令本文取得 API（`GET /api/2/law_data/{id}`、設計 §7.2 / §7.4）。

``law_xml`` に保存した原文 XML を源泉に、本文（または ``elm`` のサブツリー）を
JSON ツリー / Base64 XML で返す。id は law_revision_id / law_id / law_num を解決する。
"""

from __future__ import annotations

import gzip
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.mappers import build_law_info, build_revision_info
from laws_api_mirror.api.rendering import (
    element_to_full,
    element_to_light,
    element_to_xml_base64,
    navigate_elm,
)
from laws_api_mirror.api.repository import resolve_law
from laws_api_mirror.api.schemas import LawDataResponse
from laws_api_mirror.api.xml import negotiate
from laws_api_mirror.db.models import LawXml
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["law_data"])


@router.get(
    "/law_data/{law_id_or_num_or_revision_id}",
    response_model=LawDataResponse,
    summary="法令本文取得（JSON/XML）",
)
async def get_law_data(
    law_id_or_num_or_revision_id: str,
    law_full_text_format: str = Query("json", pattern="^(json|xml)$"),
    json_format: str = Query("full", pattern="^(full|light)$"),
    response_format: str = Query("json", pattern="^(json|xml)$"),
    elm: str | None = Query(None, description="取得する要素（例 MainProvision-Article_9）"),
    asof: date | None = Query(
        None, description="時点（YYYY-MM-DD）。施行期間が当該日を含む版を返す"
    ),
    session: AsyncSession = Depends(get_session),
) -> LawDataResponse | Response:
    resolved = await resolve_law(session, law_id_or_num_or_revision_id, asof=asof)
    if resolved is None:
        raise HTTPException(status_code=404, detail="法令が見つかりません")
    law, revision = resolved

    xml_gz = await session.scalar(
        select(LawXml.xml_gz).where(LawXml.law_revision_id == revision.law_revision_id)
    )
    if xml_gz is None:
        raise HTTPException(status_code=404, detail="法令本文が保存されていません")

    root = etree.fromstring(gzip.decompress(xml_gz))
    target = root if elm is None else navigate_elm(root, elm)
    if target is None:
        raise HTTPException(status_code=404, detail=f"elm が見つかりません: {elm}")

    law_full_text: Any
    if law_full_text_format == "xml":
        law_full_text = element_to_xml_base64(target)
    elif json_format == "light":
        law_full_text = element_to_light(target)
    else:
        law_full_text = element_to_full(target)

    model = LawDataResponse(
        law_info=build_law_info(law),
        revision_info=build_revision_info(revision),
        law_full_text=law_full_text,
    )
    return negotiate(response_format, "law_data_response", model)
