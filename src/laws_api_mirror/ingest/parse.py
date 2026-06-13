"""法令標準 XML を構造化行に変換するパーサ（Stage 3: Parse、設計 §8 / §4.7）。

1 法令の XML を受け取り、``law`` / ``law_revision`` 相当のメタと ``law_node`` の
ツリー（行 DTO の前順リスト）に変換する。DB 投入（COPY・親子 ID 解決）は後続の
ロード相（Stage 4）の責務で、本モジュールは純粋な変換のみを行う。

設計上の取り扱い:

- 本文ツリー(``law_node``)の根は **LawBody 直下の要素**（MainProvision /
  SupplProvision / Preamble / TOC / AppdxTable 等）とする。``elm`` パスが
  ``MainProvision-Article_21-...`` で始まる API 仕様（§4.7.1）に合わせ、
  Law / LawBody / LawTitle / LawNum はツリーに含めずメタとして取り出す。
- **インライン要素**（Ruby / Sup / Sub / Line / QuoteStruct / ArithFormula 等）は
  独立ノードにせず、葉ノードの ``raw_xml`` / ``text_plain`` に畳み込む（§4.7-5）。
- ``path`` は ltree ラベル（``kind`` または ``kind_Num``）で構築し、Num を持たない
  同種兄弟は出現順サフィックスで一意化する（§4.7.1。外向け ``[n]`` 表記は §11.11）。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from lxml import etree

#: 独立ノードにせず親の raw_xml/text_plain に畳み込むインライン要素（§4.7-5）
INLINE_KINDS = frozenset(
    {"Line", "Ruby", "Rt", "Sup", "Sub", "QuoteStruct", "ArithFormula", "ArithFormulaNum"}
)

#: 専用カラムへマップし attrs(JSONB) からは除外する属性
_MAPPED_ATTRS = frozenset(
    {
        "Num",
        "Delete",
        "Hide",
        "OldStyle",
        "OldNum",
        "Extract",
        "Function",
        "Indent",
        "WritingMode",
        "Type",
        "AmendLawNum",
        "src",
        "rowspan",
        "colspan",
        "BorderTop",
        "BorderBottom",
        "BorderLeft",
        "BorderRight",
        "Align",
        "Valign",
    }
)

#: 元号 → 元年の西暦
_ERA_BASE_YEAR = {
    "Meiji": 1868,
    "Taisho": 1912,
    "Showa": 1926,
    "Heisei": 1989,
    "Reiwa": 2019,
}


@dataclass
class ParsedNode:
    """``law_node`` 1 行に相当する変換結果。"""

    kind: str
    ordinal: int
    depth: int
    path: str
    path_text: str
    parent_index: int | None
    num_text: str | None = None
    num_int: int | None = None
    num_branches: list[int] | None = None
    delete_flag: bool = False
    hide_flag: bool = False
    old_style: bool | None = None
    old_num: bool | None = None
    extract_flag: bool | None = None
    sentence_function: str | None = None
    sentence_indent: str | None = None
    writing_mode: str | None = None
    suppl_type: str | None = None
    amend_law_num: str | None = None
    fig_src: str | None = None
    rowspan: int | None = None
    colspan: int | None = None
    border_top: str | None = None
    border_bottom: str | None = None
    border_left: str | None = None
    border_right: str | None = None
    align: str | None = None
    valign: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)
    raw_xml: str | None = None
    text_plain: str | None = None


@dataclass
class ParsedLaw:
    """1 法令の変換結果（メタ ＋ 本文ノード列）。"""

    law_id: str | None
    law_type: str | None
    law_num: str | None
    law_num_era: str | None
    law_num_year: int | None
    law_num_num: str | None
    promulgation_date: date | None
    law_title: str | None
    law_title_kana: str | None
    abbrev: str | None
    nodes: list[ParsedNode]


def _localname(tag: Any) -> str:
    return str(tag).split("}")[-1]


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.lower() == "true"


def _int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_num(num: str | None) -> tuple[str | None, int | None, list[int] | None]:
    if not num:
        return None, None, None
    branches = [int(x) for x in re.findall(r"\d+", num)]
    return num, (branches[0] if branches else None), (branches or None)


def _sanitize_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _plain_text(el: Any) -> str | None:
    """インライン要素を剥がしたプレーンテキスト（Ruby の振り仮名 Rt は除外、§11.11-1 案A）。"""
    parts: list[str] = []

    def rec(node: Any) -> None:
        if _localname(node.tag) == "Rt":
            return
        if node.text:
            parts.append(node.text)
        for child in node:
            rec(child)
            if child.tail:
                parts.append(child.tail)

    rec(el)
    text = "".join(parts).strip()
    return text or None


def _inner_xml(el: Any) -> str | None:
    """要素の内側 XML（インライン子要素を含む混在内容を原文保持）。"""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(etree.tostring(child, encoding="unicode"))
    text = "".join(parts).strip()
    return text or None


def _is_leaf(el: Any) -> bool:
    """子要素を持たない、または子がすべてインラインなら葉（独立ノードを作らない）。"""
    return all(_localname(c.tag) in INLINE_KINDS for c in el)


def _label_base(el: Any) -> str:
    kind = _localname(el.tag)
    num = el.get("Num")
    return f"{kind}_{_sanitize_label(num)}" if num else kind


def _assign_labels(children: list[Any]) -> list[str]:
    """兄弟ノードの ltree ラベルを一意に割り当てる。

    重複する base には出現順サフィックスを付けるが、**実在の枝番ラベルと衝突しない**
    ものを採用する。例: ``Num="23"`` が 3 つあり別に ``Num="23_2"`` がある場合、
    採番の ``_23_2`` が ``Num="23_2"`` の自然ラベルと衝突しないようスキップする。
    """
    bases = [_label_base(c) for c in children]
    counts = Counter(bases)
    # 一意な base は確定ラベルとして予約し、重複側はこれらを避けて採番する
    taken: set[str] = {base for base in bases if counts[base] == 1}
    seen: dict[str, int] = defaultdict(int)
    labels: list[str] = []
    for base in bases:
        if counts[base] == 1:
            labels.append(base)
            continue
        while True:
            seen[base] += 1
            candidate = f"{base}_{seen[base]}"
            if candidate not in taken:
                taken.add(candidate)
                labels.append(candidate)
                break
    return labels


def _node_children(el: Any) -> list[Any]:
    return [c for c in el if _localname(c.tag) not in INLINE_KINDS]


def _build_node(
    el: Any,
    label: str,
    parent_index: int | None,
    parent_path: str | None,
    parent_path_text: str | None,
    depth: int,
    ordinal: int,
    nodes: list[ParsedNode],
) -> None:
    path = label if parent_path is None else f"{parent_path}.{label}"
    path_text = label if parent_path_text is None else f"{parent_path_text}-{label}"
    kind = _localname(el.tag)
    num_text, num_int, num_branches = _parse_num(el.get("Num"))

    attrs = {k: v for k, v in el.attrib.items() if k not in _MAPPED_ATTRS}

    node = ParsedNode(
        kind=kind,
        ordinal=ordinal,
        depth=depth,
        path=path,
        path_text=path_text,
        parent_index=parent_index,
        num_text=num_text,
        num_int=num_int,
        num_branches=num_branches,
        delete_flag=bool(_bool(el.get("Delete"))),
        hide_flag=bool(_bool(el.get("Hide"))),
        old_style=_bool(el.get("OldStyle")),
        old_num=_bool(el.get("OldNum")),
        extract_flag=_bool(el.get("Extract")),
        sentence_function=el.get("Function"),
        sentence_indent=el.get("Indent"),
        writing_mode=el.get("WritingMode"),
        suppl_type=el.get("Type"),
        amend_law_num=el.get("AmendLawNum"),
        fig_src=el.get("src") if kind == "Fig" else None,
        rowspan=_int(el.get("rowspan")),
        colspan=_int(el.get("colspan")),
        border_top=el.get("BorderTop"),
        border_bottom=el.get("BorderBottom"),
        border_left=el.get("BorderLeft"),
        border_right=el.get("BorderRight"),
        align=el.get("Align"),
        valign=el.get("Valign"),
        attrs=attrs,
    )
    index = len(nodes)
    nodes.append(node)

    if _is_leaf(el):
        node.raw_xml = _inner_xml(el)
        node.text_plain = _plain_text(el)
        return

    children = _node_children(el)
    labels = _assign_labels(children)
    for child_ordinal, (child, child_label) in enumerate(zip(children, labels, strict=True)):
        _build_node(child, child_label, index, path, path_text, depth + 1, child_ordinal, nodes)


def _promulgation_date(law: Any) -> date | None:
    era = law.get("Era")
    year = _int(law.get("Year"))
    month = _int(law.get("PromulgateMonth"))
    day = _int(law.get("PromulgateDay"))
    base = _ERA_BASE_YEAR.get(era) if era else None
    if base is None or not year or not month or not day:
        return None
    try:
        return date(base + year - 1, month, day)
    except ValueError:
        return None


def parse_law(xml: bytes, *, law_id: str | None = None) -> ParsedLaw:
    """法令 XML（bytes）を ``ParsedLaw`` に変換する。"""
    root = etree.fromstring(xml)
    if _localname(root.tag) != "Law":
        raise ValueError(f"ルート要素が Law ではありません: {_localname(root.tag)}")

    law_body = root.find("LawBody")
    law_num_el = root.find("LawNum")
    law_num = law_num_el.text if law_num_el is not None else None

    law_title = law_title_kana = abbrev = None
    nodes: list[ParsedNode] = []
    if law_body is not None:
        title_el = law_body.find("LawTitle")
        if title_el is not None:
            law_title = _plain_text(title_el)
            law_title_kana = title_el.get("Kana")
            abbrev = title_el.get("Abbrev")

        # LawBody 直下（LawTitle 以外）を本文ツリーの根として構築
        roots = [c for c in law_body if _localname(c.tag) != "LawTitle"]
        labels = _assign_labels(roots)
        for ordinal, (el, label) in enumerate(zip(roots, labels, strict=True)):
            _build_node(el, label, None, None, None, 0, ordinal, nodes)

    return ParsedLaw(
        law_id=law_id,
        law_type=root.get("LawType"),
        law_num=law_num,
        law_num_era=root.get("Era"),
        law_num_year=_int(root.get("Year")),
        law_num_num=root.get("Num"),
        promulgation_date=_promulgation_date(root),
        law_title=law_title,
        law_title_kana=law_title_kana,
        abbrev=abbrev,
        nodes=nodes,
    )
