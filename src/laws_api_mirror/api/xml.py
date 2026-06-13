"""レスポンス封筒の XML シリアライズとコンテンツネゴシエーション（設計 §7.3 / §10-9）。

`response_format=xml` のとき、Pydantic モデルの JSON 表現を e-Gov v2 互換の XML 構造に
変換して返す。インタフェース互換（要素名・構造）を維持し、バイト単位一致は目指さない。

変換規則（実 API を踏襲）:

- dict → ``<key>...子...</key>`` を再帰。
- list → 複数形ラッパ ``<key>`` の中に単数要素（``laws``→``law`` 等）を並べる。
- None → 自己終了 ``<key/>``、空文字 → ``<key></key>``、bool → ``true`` / ``false``。
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

from fastapi import Response
from pydantic import BaseModel

#: list フィールド名 → 各要素のタグ（複数形 → 単数形）
_ITEM_TAGS = {
    "laws": "law",
    "revisions": "revision",
    "items": "item",
    "sentences": "sentence",
    "children": "item",
}


def _element(tag: str, value: Any) -> str:
    if value is None:
        return f"<{tag}/>"
    if isinstance(value, bool):
        return f"<{tag}>{'true' if value else 'false'}</{tag}>"
    if isinstance(value, dict):
        inner = "".join(_element(str(k), v) for k, v in value.items())
        return f"<{tag}>{inner}</{tag}>"
    if isinstance(value, list):
        item_tag = _ITEM_TAGS.get(tag, "item")
        inner = "".join(_element(item_tag, v) for v in value)
        return f"<{tag}>{inner}</{tag}>"
    text = str(value)
    return f"<{tag}></{tag}>" if text == "" else f"<{tag}>{escape(text)}</{tag}>"


def render_xml(root_tag: str, data: dict[str, Any]) -> str:
    inner = "".join(_element(k, v) for k, v in data.items())
    return f"<{root_tag}>{inner}</{root_tag}>"


def negotiate[M: BaseModel](response_format: str, root_tag: str, model: M) -> M | Response:
    """``response_format=xml`` なら XML Response、それ以外はモデルをそのまま返す。"""
    if response_format == "xml":
        body = render_xml(root_tag, model.model_dump(mode="json"))
        return Response(content=body, media_type="application/xml")
    return model
