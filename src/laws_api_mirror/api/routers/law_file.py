"""法令本文ファイル取得 API（`GET /api/2/law_file/{file_type}/{id}`、設計 §7.2 / §10-3）。

本文（または ``elm`` のサブツリー）をファイルとしてダウンロードさせる。

1st リリースは **xml / json のみ**対応する。html / rtf / docx は 400 Bad Request を返す
（§10-3。レンダリング層の拡充は §11.10 で将来検討）。
"""

from __future__ import annotations

import gzip
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from laws_api_mirror.api.rendering import element_to_full, element_to_light, navigate_elm
from laws_api_mirror.api.repository import resolve_law
from laws_api_mirror.db.models import LawXml
from laws_api_mirror.db.session import get_session

router = APIRouter(prefix="/api/2", tags=["law_file"])

_SUPPORTED = {"xml", "json"}
_UNSUPPORTED = {"html", "rtf", "docx"}


def _disposition(filename: str) -> dict[str, str]:
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get(
    "/law_file/{file_type}/{law_id_or_num_or_revision_id}",
    summary="法令本文ファイル取得（xml / json）",
)
async def get_law_file(
    file_type: str,
    law_id_or_num_or_revision_id: str,
    json_format: str = Query("full", pattern="^(full|light)$"),
    elm: str | None = Query(None, description="取得する要素（例 MainProvision-Article_9）"),
    session: AsyncSession = Depends(get_session),
) -> Response:
    if file_type in _UNSUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"file_type={file_type} は未対応です（1st リリースは xml / json のみ）",
        )
    if file_type not in _SUPPORTED:
        raise HTTPException(status_code=400, detail=f"未知の file_type: {file_type}")

    resolved = await resolve_law(session, law_id_or_num_or_revision_id)
    if resolved is None:
        raise HTTPException(status_code=404, detail="法令が見つかりません")
    _, revision = resolved

    xml_gz = await session.scalar(
        select(LawXml.xml_gz).where(LawXml.law_revision_id == revision.law_revision_id)
    )
    if xml_gz is None:
        raise HTTPException(status_code=404, detail="法令本文が保存されていません")
    raw = gzip.decompress(xml_gz)

    filename = f"{revision.law_revision_id}.{file_type}"

    if file_type == "xml":
        if elm is None:
            content = raw  # 全文は原文 XML をそのまま（完全一致）
        else:
            target = navigate_elm(etree.fromstring(raw), elm)
            if target is None:
                raise HTTPException(status_code=404, detail=f"elm が見つかりません: {elm}")
            content = etree.tostring(target, encoding="utf-8")
        return Response(content, media_type="application/xml", headers=_disposition(filename))

    # json
    root = etree.fromstring(raw)
    target = root if elm is None else navigate_elm(root, elm)
    if target is None:
        raise HTTPException(status_code=404, detail=f"elm が見つかりません: {elm}")
    tree = element_to_light(target) if json_format == "light" else element_to_full(target)
    body = json.dumps(tree, ensure_ascii=False).encode("utf-8")
    return Response(body, media_type="application/json", headers=_disposition(filename))
