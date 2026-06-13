"""レスポンス封筒 XML シリアライザ（DB 非依存）の単体テスト。"""

from __future__ import annotations

from laws_api_mirror.api.xml import render_xml


def test_render_scalars_and_null() -> None:
    """スカラ・null・bool・空文字を規則どおりに出力する。"""
    xml = render_xml("root", {"n": 1, "s": "x", "empty": "", "nothing": None, "flag": False})
    assert xml.startswith("<root>") and xml.endswith("</root>")
    assert "<n>1</n>" in xml
    assert "<s>x</s>" in xml
    assert "<empty></empty>" in xml
    assert "<nothing/>" in xml
    assert "<flag>false</flag>" in xml


def test_render_list_uses_singular_item_tag() -> None:
    """list は複数形ラッパ＋単数要素（laws→law）。"""
    xml = render_xml("laws_response", {"laws": [{"law_info": {"law_id": "X"}}]})
    assert "<laws><law><law_info><law_id>X</law_id></law_info></law></laws>" in xml


def test_render_escapes_special_chars() -> None:
    """XML 特殊文字をエスケープする。"""
    xml = render_xml("root", {"v": "a & b < c"})
    assert "<v>a &amp; b &lt; c</v>" in xml
