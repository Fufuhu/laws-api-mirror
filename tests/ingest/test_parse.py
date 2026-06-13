"""法令 XML パーサ（Stage 3）の単体テスト。"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from laws_api_mirror.ingest.parse import parse_law

FIXTURE = Path(__file__).parent.parent / "fixtures" / "laws" / "322CO0000000014.xml"

# インライン畳み込み・枝番・重複兄弟の一意化を検証する合成 XML
SYNTHETIC = """<?xml version="1.0" encoding="UTF-8"?>
<Law Era="Heisei" Year="15" Num="57" LawType="Act" PromulgateMonth="05" PromulgateDay="30">
  <LawNum>平成十五年法律第五十七号</LawNum>
  <LawBody>
    <LawTitle Kana="こじんじょうほう">個人情報の保護に関する法律</LawTitle>
    <MainProvision>
      <Article Num="21_2">
        <ArticleTitle>第二十一条の二</ArticleTitle>
        <Paragraph Num="1">
          <ParagraphSentence>
            <Sentence>この<Ruby>法律<Rt>ほうりつ</Rt></Ruby>は、<Sub>個人</Sub>情報を保護する。</Sentence>
          </ParagraphSentence>
        </Paragraph>
      </Article>
    </MainProvision>
    <SupplProvision><SupplProvisionLabel>附則一</SupplProvisionLabel></SupplProvision>
    <SupplProvision><SupplProvisionLabel>附則二</SupplProvisionLabel></SupplProvision>
  </LawBody>
</Law>
""".encode()


def test_parse_fixture_metadata() -> None:
    """実法令 XML から law / law_revision 相当のメタを抽出することを確認する。"""
    law = parse_law(FIXTURE.read_bytes(), law_id="322CO0000000014")
    assert law.law_id == "322CO0000000014"
    assert law.law_type == "CabinetOrder"
    assert law.law_num == "昭和二十二年政令第十四号"
    assert (law.law_num_era, law.law_num_year, law.law_num_num) == ("Showa", 22, "014")
    assert law.promulgation_date == date(1947, 5, 3)  # 昭和22年 = 1947
    assert law.law_title is not None and law.law_title.startswith("昭和二十二年政令第十四号")
    assert law.law_title_kana is not None and law.law_title_kana.startswith("にほんこく")
    assert law.abbrev == ""


def test_parse_fixture_tree() -> None:
    """本文ツリーが LawBody 直下を根とし、path が一意であることを確認する。"""
    law = parse_law(FIXTURE.read_bytes())
    paths = [n.path for n in law.nodes]
    assert len(paths) == len(set(paths))  # path 一意

    roots = [n for n in law.nodes if n.depth == 0]
    assert {n.kind for n in roots} == {"MainProvision", "SupplProvision"}

    # MainProvision 直下に Num 付き Paragraph 2 件
    paras = [
        n for n in law.nodes if n.path in ("MainProvision.Paragraph_1", "MainProvision.Paragraph_2")
    ]
    assert len(paras) == 2
    assert all(p.kind == "Paragraph" for p in paras)
    assert {p.num_int for p in paras} == {1, 2}
    assert all(p.old_num is True and p.hide_flag is False for p in paras)

    # Sentence は葉。text_plain と raw_xml を持つ
    sentence = next(
        n for n in law.nodes if n.path == "MainProvision.Paragraph_1.ParagraphSentence.Sentence"
    )
    assert sentence.text_plain is not None and "勅令" in sentence.text_plain
    assert sentence.raw_xml is not None
    assert sentence.writing_mode == "vertical"


def test_inline_elements_folded_into_leaf() -> None:
    """インライン要素(Ruby/Sub)は独立ノードにせず、葉の text_plain/raw_xml に畳み込む。"""
    law = parse_law(SYNTHETIC)
    kinds = {n.kind for n in law.nodes}
    assert "Ruby" not in kinds and "Rt" not in kinds and "Sub" not in kinds

    sentence = next(n for n in law.nodes if n.kind == "Sentence")
    # Rt（振り仮名）は除外し、Ruby ベース・Sub テキストは残る
    assert sentence.text_plain == "この法律は、個人情報を保護する。"
    # raw_xml には混在内容（インラインタグ）が原文保持される
    assert sentence.raw_xml is not None
    assert "<Ruby>" in sentence.raw_xml and "<Rt>" in sentence.raw_xml


def test_num_branches_and_label() -> None:
    """枝番 Num="21_2" が num_branches/ラベルに正しく反映されることを確認する。"""
    law = parse_law(SYNTHETIC)
    article = next(n for n in law.nodes if n.kind == "Article")
    assert article.num_text == "21_2"
    assert article.num_int == 21
    assert article.num_branches == [21, 2]
    assert article.path == "MainProvision.Article_21_2"


def test_disambiguation_avoids_collision_with_branch_label() -> None:
    """採番サフィックスが実在の枝番ラベルと衝突しないことを確認する（全件実走で発見）。

    Num="23" が 3 つ＋ Num="23_2" が 1 つ → 自然ラベル AppdxFormat_23_2 と採番が衝突しない。
    """
    xml = """<?xml version="1.0"?>
<Law Era="Heisei" Year="12" Num="82" LawType="MinisterialOrdinance">
  <LawNum>平成十二年厚生省令第八十二号</LawNum>
  <LawBody>
    <LawTitle>テスト省令</LawTitle>
    <AppdxFormat Num="23"><AppdxFormatTitle>a</AppdxFormatTitle></AppdxFormat>
    <AppdxFormat Num="23"><AppdxFormatTitle>b</AppdxFormatTitle></AppdxFormat>
    <AppdxFormat Num="23"><AppdxFormatTitle>c</AppdxFormatTitle></AppdxFormat>
    <AppdxFormat Num="23_2"><AppdxFormatTitle>d</AppdxFormatTitle></AppdxFormat>
  </LawBody>
</Law>
""".encode()
    law = parse_law(xml)
    roots = [n for n in law.nodes if n.depth == 0]
    paths = [n.path for n in roots]
    assert len(paths) == len(set(paths))  # 4 つの AppdxFormat が一意
    # Num="23_2" の自然ラベルは保持される
    assert "AppdxFormat_23_2" in paths
    # Num="23"×3 はいずれも AppdxFormat_23_2 を使わない
    num23 = [n for n in roots if n.num_text == "23"]
    assert len(num23) == 3
    assert all(n.path != "AppdxFormat_23_2" for n in num23)


def test_duplicate_siblings_disambiguated() -> None:
    """Num を持たない同種兄弟（SupplProvision×2）が一意なラベルになることを確認する。"""
    law = parse_law(SYNTHETIC)
    suppl_paths = sorted(n.path for n in law.nodes if n.kind == "SupplProvision")
    assert suppl_paths == ["SupplProvision_1", "SupplProvision_2"]


def test_parent_index_links_tree() -> None:
    """parent_index が前順リスト内の親を指し、根のみ None であることを確認する。"""
    law = parse_law(FIXTURE.read_bytes())
    roots = [n for n in law.nodes if n.parent_index is None]
    assert all(n.depth == 0 for n in roots)
    for i, node in enumerate(law.nodes):
        if node.parent_index is not None:
            assert 0 <= node.parent_index < i  # 親は自分より前
            assert law.nodes[node.parent_index].depth == node.depth - 1
