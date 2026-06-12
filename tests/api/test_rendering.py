"""法令本文レンダリング（XML→JSON / elm 解決）の単体テスト（DB 非依存）。"""

from __future__ import annotations

import base64
from pathlib import Path

from lxml import etree

from laws_api_mirror.api.rendering import (
    element_to_full,
    element_to_xml_base64,
    navigate_elm,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "laws" / "322CO0000000014.xml"


def _root() -> object:
    return etree.fromstring(FIXTURE.read_bytes())


def test_element_to_full_root_is_law() -> None:
    """elm なし（root）は tag=Law、子に LawNum/LawBody を持つ。"""
    full = element_to_full(_root())
    assert full["tag"] == "Law"
    assert full["attr"]["LawType"] == "CabinetOrder"
    child_tags = [c["tag"] for c in full["children"] if isinstance(c, dict)]
    assert child_tags == ["LawNum", "LawBody"]


def test_navigate_elm_to_paragraph() -> None:
    """elm でリビジョン本文のサブツリーを辿れる。"""
    target = navigate_elm(_root(), "MainProvision-Paragraph_1")
    assert target is not None
    full = element_to_full(target)
    assert full["tag"] == "Paragraph"
    assert full["attr"]["Num"] == "1"
    assert full["attr"]["OldNum"] == "true"


def test_navigate_elm_sentence_text_is_string_child() -> None:
    """Sentence の混在テキストは children に文字列として入る。"""
    target = navigate_elm(_root(), "MainProvision-Paragraph_1-ParagraphSentence-Sentence")
    assert target is not None
    full = element_to_full(target)
    assert full["tag"] == "Sentence"
    assert full["attr"]["WritingMode"] == "vertical"
    assert len(full["children"]) == 1
    assert isinstance(full["children"][0], str)
    assert "勅令" in full["children"][0]


def test_navigate_elm_not_found() -> None:
    """存在しない elm は None。"""
    assert navigate_elm(_root(), "MainProvision-Article_999") is None


def test_element_to_xml_base64_roundtrip() -> None:
    """Base64 XML をデコードすると元の要素 XML になる。"""
    target = navigate_elm(_root(), "MainProvision-Paragraph_1")
    assert target is not None
    decoded = base64.b64decode(element_to_xml_base64(target)).decode("utf-8")
    assert decoded.startswith("<Paragraph")
    assert "勅令" in decoded
