"""法令本文のレンダリング（XML → JSON ツリー / Base64 XML、設計 §7 / §10-9）。

原文 XML（``law_xml`` に保存、§4.6）を源泉として再構築する。``elm`` の解決は法令本文の
パスラベル規則（パーサと共有、§4.7.1）で XML ツリーを辿る。

- ``full`` JSON: ``{tag, attr, children}`` 再帰。children はテキスト（文字列）と子要素
  （dict）を文書順に保持する（§10-9 想定実装）。
- ``light`` JSON: ``{TagName: 値 or 配列}`` 再帰（最も容易な実装、§10-9 / §11.11）。
- XML: 要素を直列化して Base64（封筒が JSON で本文が XML のため、§7.3）。
"""

from __future__ import annotations

import base64
from typing import Any

from lxml import etree

from laws_api_mirror.ingest.parse import (
    INLINE_KINDS,
    _assign_labels,
    _localname,
    _node_children,
)


def element_to_full(el: Any) -> dict[str, Any]:
    """要素を ``{tag, attr, children}`` ツリーに変換する（full、混在内容保持）。"""
    children: list[Any] = []
    if el.text and el.text.strip():
        children.append(el.text)
    for child in el:
        children.append(element_to_full(child))
        if child.tail and child.tail.strip():
            children.append(child.tail)
    return {"tag": _localname(el.tag), "attr": dict(el.attrib), "children": children}


def element_to_light(el: Any) -> dict[str, Any]:
    """要素を ``{TagName: 値 or 配列}`` に変換する（light、簡易実装）。"""
    tag = _localname(el.tag)
    children = list(el)
    if not children:  # 葉: テキストをそのまま
        return {tag: (el.text or "").strip()}
    return {tag: [element_to_light(child) for child in children]}


def element_to_xml_base64(el: Any) -> str:
    """要素を XML 文字列に直列化し Base64 エンコードする。"""
    xml = etree.tostring(el, encoding="unicode")
    return base64.b64encode(xml.encode("utf-8")).decode("ascii")


def _match(children: list[Any], labels: list[str], segment: str) -> Any | None:
    for child, label in zip(children, labels, strict=True):
        if label == segment:
            return child
    return None


def navigate_elm(root: Any, elm: str) -> Any | None:
    """``elm``（例 ``MainProvision-Article_9-Paragraph_1``）の指す要素を返す。

    本文ツリーの根は LawBody 直下（LawTitle を除く）。見つからなければ None。
    """
    body = root.find("LawBody")
    if body is None:
        return None
    segments = [s for s in elm.split("-") if s]
    if not segments:
        return None

    # 第 1 段: LawBody 直下（LawTitle・インラインを除く）
    candidates = [
        c for c in body if _localname(c.tag) != "LawTitle" and _localname(c.tag) not in INLINE_KINDS
    ]
    target = _match(candidates, _assign_labels(candidates), segments[0])

    for segment in segments[1:]:
        if target is None:
            return None
        children = _node_children(target)
        target = _match(children, _assign_labels(children), segment)
    return target
