"""initial schema

Revision ID: 31643562a6c2
Revises: 
Create Date: 2026-06-13 04:36:00.280165

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import laws_api_mirror.db.types

# revision identifiers, used by Alembic.
revision: str = '31643562a6c2'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# node_kind の代表集合（kind, category, is_container）。全要素は後続リビジョンで補完（§11.12.4）。
_CORE_NODE_KINDS: list[dict[str, object]] = [
    # meta
    {"kind": "Law", "category": "meta", "is_container": True},
    {"kind": "LawNum", "category": "meta", "is_container": False},
    {"kind": "LawBody", "category": "meta", "is_container": True},
    {"kind": "LawTitle", "category": "meta", "is_container": False},
    {"kind": "EnactStatement", "category": "meta", "is_container": False},
    {"kind": "Preamble", "category": "structure", "is_container": True},
    # toc
    {"kind": "TOC", "category": "toc", "is_container": True},
    {"kind": "TOCLabel", "category": "toc", "is_container": False},
    {"kind": "TOCPreambleLabel", "category": "toc", "is_container": False},
    {"kind": "TOCPart", "category": "toc", "is_container": True},
    {"kind": "TOCChapter", "category": "toc", "is_container": True},
    {"kind": "TOCSection", "category": "toc", "is_container": True},
    {"kind": "TOCSubsection", "category": "toc", "is_container": True},
    {"kind": "TOCDivision", "category": "toc", "is_container": True},
    {"kind": "TOCArticle", "category": "toc", "is_container": True},
    {"kind": "TOCSupplProvision", "category": "toc", "is_container": True},
    {"kind": "TOCAppdxTableLabel", "category": "toc", "is_container": False},
    # structure
    {"kind": "MainProvision", "category": "structure", "is_container": True},
    {"kind": "Part", "category": "structure", "is_container": True},
    {"kind": "Chapter", "category": "structure", "is_container": True},
    {"kind": "Section", "category": "structure", "is_container": True},
    {"kind": "Subsection", "category": "structure", "is_container": True},
    {"kind": "Division", "category": "structure", "is_container": True},
    {"kind": "Article", "category": "structure", "is_container": True},
    {"kind": "ArticleTitle", "category": "structure", "is_container": False},
    {"kind": "ArticleCaption", "category": "structure", "is_container": False},
    # block
    {"kind": "Paragraph", "category": "block", "is_container": True},
    {"kind": "ParagraphCaption", "category": "block", "is_container": False},
    {"kind": "ParagraphNum", "category": "block", "is_container": False},
    {"kind": "ParagraphSentence", "category": "block", "is_container": True},
    {"kind": "Item", "category": "block", "is_container": True},
    {"kind": "ItemTitle", "category": "block", "is_container": False},
    {"kind": "ItemSentence", "category": "block", "is_container": True},
    # sentence / inline
    {"kind": "Sentence", "category": "sentence", "is_container": False},
    {"kind": "Column", "category": "sentence", "is_container": True},
    {"kind": "List", "category": "sentence", "is_container": True},
    {"kind": "ListSentence", "category": "sentence", "is_container": True},
    {"kind": "Ruby", "category": "inline", "is_container": False},
    {"kind": "Rt", "category": "inline", "is_container": False},
    {"kind": "Line", "category": "inline", "is_container": False},
    {"kind": "QuoteStruct", "category": "inline", "is_container": False},
    {"kind": "ArithFormula", "category": "inline", "is_container": False},
    {"kind": "Sup", "category": "inline", "is_container": False},
    {"kind": "Sub", "category": "inline", "is_container": False},
    # table / fig
    {"kind": "TableStruct", "category": "table", "is_container": True},
    {"kind": "Table", "category": "table", "is_container": True},
    {"kind": "TableRow", "category": "table", "is_container": True},
    {"kind": "TableColumn", "category": "table", "is_container": True},
    {"kind": "FigStruct", "category": "fig", "is_container": True},
    {"kind": "Fig", "category": "fig", "is_container": False},
    # supplement / appdx / amend
    {"kind": "SupplProvision", "category": "supplement", "is_container": True},
    {"kind": "SupplProvisionLabel", "category": "supplement", "is_container": False},
    {"kind": "AppdxTable", "category": "appdx", "is_container": True},
    {"kind": "AppdxTableTitle", "category": "appdx", "is_container": False},
    {"kind": "AmendProvision", "category": "amend", "is_container": True},
    {"kind": "AmendProvisionSentence", "category": "amend", "is_container": False},
    {"kind": "NewProvision", "category": "amend", "is_container": True},
]


def upgrade() -> None:
    """Upgrade schema."""
    # 拡張（設計 §4.7.1 ltree / §5 pg_bigm / EXCLUDE の gist 等値比較に btree_gist）
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_bigm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('amendment_type',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_amendment_type'))
    )
    op.create_table('category',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_category'))
    )
    op.create_table('current_revision_status',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_current_revision_status'))
    )
    op.create_table('era',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_era'))
    )
    op.create_table('ingest_run',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('source_date', sa.Date(), nullable=True),
    sa.Column('stats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingest_run'))
    )
    op.create_table('law_num_type',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_law_num_type'))
    )
    op.create_table('law_type',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_law_type'))
    )
    op.create_table('mission',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_mission'))
    )
    op.create_table('node_kind',
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('category', sa.Text(), nullable=False),
    sa.Column('is_container', sa.Boolean(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('kind', name=op.f('pk_node_kind'))
    )
    op.create_table('repeal_status',
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('label', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('code', name=op.f('pk_repeal_status'))
    )
    op.create_table('ingest_law_event',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('ingest_run_id', sa.BigInteger(), nullable=True),
    sa.Column('law_revision_id', sa.Text(), nullable=True),
    sa.Column('action', sa.Text(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['ingest_run_id'], ['ingest_run.id'], name=op.f('fk_ingest_law_event_ingest_run_id_ingest_run')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ingest_law_event'))
    )
    op.create_index('ix_ingest_law_event_run', 'ingest_law_event', ['ingest_run_id'], unique=False)
    op.create_table('law',
    sa.Column('law_id', sa.Text(), nullable=False),
    sa.Column('law_type', sa.Text(), nullable=True),
    sa.Column('law_num', sa.Text(), nullable=False),
    sa.Column('law_num_era', sa.Text(), nullable=True),
    sa.Column('law_num_year', sa.SmallInteger(), nullable=True),
    sa.Column('law_num_type', sa.Text(), nullable=True),
    sa.Column('law_num_num', sa.Text(), nullable=True),
    sa.Column('promulgation_date', sa.Date(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['law_num_era'], ['era.code'], name=op.f('fk_law_law_num_era_era')),
    sa.ForeignKeyConstraint(['law_num_type'], ['law_num_type.code'], name=op.f('fk_law_law_num_type_law_num_type')),
    sa.ForeignKeyConstraint(['law_type'], ['law_type.code'], name=op.f('fk_law_law_type_law_type')),
    sa.PrimaryKeyConstraint('law_id', name=op.f('pk_law')),
    sa.UniqueConstraint('law_num', name='uq_law_law_num')
    )
    op.create_index('ix_law_num_components', 'law', ['law_num_era', 'law_num_year', 'law_num_type', 'law_num_num'], unique=False)
    op.create_index('ix_law_promulgation_date', 'law', ['promulgation_date'], unique=False)
    op.create_table('amendment_law',
    sa.Column('amendment_law_id', sa.Text(), nullable=False),
    sa.Column('amendment_law_title', sa.Text(), nullable=True),
    sa.Column('amendment_law_title_kana', sa.Text(), nullable=True),
    sa.Column('amendment_law_num', sa.Text(), nullable=True),
    sa.Column('amendment_promulgate_date', sa.Date(), nullable=True),
    sa.Column('linked_law_id', sa.Text(), nullable=True),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['linked_law_id'], ['law.law_id'], name=op.f('fk_amendment_law_linked_law_id_law'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('amendment_law_id', name=op.f('pk_amendment_law'))
    )
    op.create_index('ix_amendment_law_linked_law_id', 'amendment_law', ['linked_law_id'], unique=False)
    op.create_index('ix_amendment_law_promulgate_date', 'amendment_law', ['amendment_promulgate_date'], unique=False)
    op.create_table('law_revision',
    sa.Column('law_revision_id', sa.Text(), nullable=False),
    sa.Column('law_id', sa.Text(), nullable=False),
    sa.Column('law_type', sa.Text(), nullable=True),
    sa.Column('law_title', sa.Text(), nullable=False),
    sa.Column('law_title_kana', sa.Text(), nullable=True),
    sa.Column('abbrev', sa.Text(), nullable=True),
    sa.Column('category_cd', sa.Text(), nullable=True),
    sa.Column('updated_at_source', sa.DateTime(timezone=True), nullable=True),
    sa.Column('amendment_enforcement_date', sa.Date(), nullable=True),
    sa.Column('amendment_enforcement_comment', sa.Text(), nullable=True),
    sa.Column('amendment_scheduled_enforcement_date', sa.Date(), nullable=True),
    sa.Column('amendment_law_id', sa.Text(), nullable=True),
    sa.Column('amendment_type', sa.Text(), nullable=True),
    sa.Column('repeal_status', sa.Text(), nullable=True),
    sa.Column('repeal_date', sa.Date(), nullable=True),
    sa.Column('remain_in_force', sa.Boolean(), nullable=True),
    sa.Column('mission', sa.Text(), nullable=True),
    sa.Column('current_revision_status', sa.Text(), nullable=True),
    sa.Column('is_current_latest', sa.Boolean(), nullable=True),
    sa.Column('enforcement_period', postgresql.DATERANGE(), nullable=True),
    postgresql.ExcludeConstraint((sa.column('law_id'), '='), (sa.column('enforcement_period'), '&&'), deferrable='True', using='gist', name='enforcement_period_no_overlap'),
    sa.ForeignKeyConstraint(['amendment_law_id'], ['amendment_law.amendment_law_id'], name=op.f('fk_law_revision_amendment_law_id_amendment_law')),
    sa.ForeignKeyConstraint(['amendment_type'], ['amendment_type.code'], name=op.f('fk_law_revision_amendment_type_amendment_type')),
    sa.ForeignKeyConstraint(['category_cd'], ['category.code'], name=op.f('fk_law_revision_category_cd_category')),
    sa.ForeignKeyConstraint(['current_revision_status'], ['current_revision_status.code'], name=op.f('fk_law_revision_current_revision_status_current_revision_status')),
    sa.ForeignKeyConstraint(['law_id'], ['law.law_id'], name=op.f('fk_law_revision_law_id_law')),
    sa.ForeignKeyConstraint(['law_type'], ['law_type.code'], name=op.f('fk_law_revision_law_type_law_type')),
    sa.ForeignKeyConstraint(['mission'], ['mission.code'], name=op.f('fk_law_revision_mission_mission')),
    sa.ForeignKeyConstraint(['repeal_status'], ['repeal_status.code'], name=op.f('fk_law_revision_repeal_status_repeal_status')),
    sa.PrimaryKeyConstraint('law_revision_id', name=op.f('pk_law_revision'))
    )
    op.create_index('ix_law_revision_current_status', 'law_revision', ['current_revision_status'], unique=False)
    op.create_index('ix_law_revision_law_id_enforcement', 'law_revision', ['law_id', 'amendment_enforcement_date'], unique=False)
    op.create_table('attached_file',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('law_revision_id', sa.Text(), nullable=False),
    sa.Column('src', sa.Text(), nullable=False),
    sa.Column('content_type', sa.Text(), nullable=True),
    sa.Column('byte_size', sa.BigInteger(), nullable=True),
    sa.Column('sha256', postgresql.BYTEA(), nullable=False),
    sa.Column('object_key', sa.Text(), nullable=False),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['law_revision_id'], ['law_revision.law_revision_id'], name=op.f('fk_attached_file_law_revision_id_law_revision'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_attached_file')),
    sa.UniqueConstraint('law_revision_id', 'src', name='uq_attached_file_revision_src')
    )
    op.create_index('ix_attached_file_sha256', 'attached_file', ['sha256'], unique=False)
    op.create_table('law_node',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('law_revision_id', sa.Text(), nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=False),
    sa.Column('ordinal', sa.Integer(), nullable=False),
    sa.Column('num_text', sa.Text(), nullable=True),
    sa.Column('num_int', sa.Integer(), nullable=True),
    sa.Column('num_branches', postgresql.ARRAY(sa.Integer()), nullable=True),
    sa.Column('caption', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('label', sa.Text(), nullable=True),
    sa.Column('delete_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('hide_flag', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('old_style', sa.Boolean(), nullable=True),
    sa.Column('old_num', sa.Boolean(), nullable=True),
    sa.Column('extract_flag', sa.Boolean(), nullable=True),
    sa.Column('sentence_function', sa.Text(), nullable=True),
    sa.Column('sentence_indent', sa.Text(), nullable=True),
    sa.Column('writing_mode', sa.Text(), nullable=True),
    sa.Column('suppl_type', sa.Text(), nullable=True),
    sa.Column('amend_law_num', sa.Text(), nullable=True),
    sa.Column('fig_src', sa.Text(), nullable=True),
    sa.Column('rowspan', sa.Integer(), nullable=True),
    sa.Column('colspan', sa.Integer(), nullable=True),
    sa.Column('border_top', sa.Text(), nullable=True),
    sa.Column('border_bottom', sa.Text(), nullable=True),
    sa.Column('border_left', sa.Text(), nullable=True),
    sa.Column('border_right', sa.Text(), nullable=True),
    sa.Column('align', sa.Text(), nullable=True),
    sa.Column('valign', sa.Text(), nullable=True),
    sa.Column('attrs', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('raw_xml', sa.Text(), nullable=True),
    sa.Column('text_plain', sa.Text(), nullable=True),
    sa.Column('path', laws_api_mirror.db.types.LTREE(), nullable=False),
    sa.Column('path_text', sa.Text(), nullable=False),
    sa.Column('depth', sa.SmallInteger(), nullable=False),
    sa.Column('text_search', postgresql.TSVECTOR(), nullable=True),
    sa.ForeignKeyConstraint(['kind'], ['node_kind.kind'], name=op.f('fk_law_node_kind_node_kind')),
    sa.ForeignKeyConstraint(['law_revision_id'], ['law_revision.law_revision_id'], name=op.f('fk_law_node_law_revision_id_law_revision'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['parent_id'], ['law_node.id'], name=op.f('fk_law_node_parent_id_law_node'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_law_node')),
    sa.UniqueConstraint('law_revision_id', 'path', name='uq_law_node_revision_path')
    )
    op.create_index('ix_law_node_attrs', 'law_node', ['attrs'], unique=False, postgresql_using='gin', postgresql_ops={'attrs': 'jsonb_path_ops'})
    op.create_index('ix_law_node_path_gist', 'law_node', ['path'], unique=False, postgresql_using='gist')
    op.create_index('ix_law_node_revision_kind_num', 'law_node', ['law_revision_id', 'kind', 'num_int'], unique=False)
    op.create_index('ix_law_node_revision_parent_ordinal', 'law_node', ['law_revision_id', 'parent_id', 'ordinal'], unique=False)
    op.create_index('ix_law_node_text_plain_bigm', 'law_node', ['text_plain'], unique=False, postgresql_using='gin', postgresql_ops={'text_plain': 'gin_bigm_ops'})
    op.create_index('ix_law_node_text_search', 'law_node', ['text_search'], unique=False, postgresql_using='gin')
    op.create_table('law_revision_category',
    sa.Column('law_revision_id', sa.Text(), nullable=False),
    sa.Column('category_cd', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['category_cd'], ['category.code'], name=op.f('fk_law_revision_category_category_cd_category')),
    sa.ForeignKeyConstraint(['law_revision_id'], ['law_revision.law_revision_id'], name=op.f('fk_law_revision_category_law_revision_id_law_revision'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('law_revision_id', 'category_cd', name=op.f('pk_law_revision_category'))
    )
    op.create_table('law_xml',
    sa.Column('law_revision_id', sa.Text(), nullable=False),
    sa.Column('xml_gz', postgresql.BYTEA(), nullable=False),
    sa.Column('xml_sha256', postgresql.BYTEA(), nullable=False),
    sa.Column('byte_size', sa.Integer(), nullable=True),
    sa.Column('source_updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('xsd_version', sa.Text(), server_default='v3.0', nullable=False),
    sa.ForeignKeyConstraint(['law_revision_id'], ['law_revision.law_revision_id'], name=op.f('fk_law_xml_law_revision_id_law_revision'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('law_revision_id', name=op.f('pk_law_xml'))
    )
    # ### end Alembic commands ###

    _seed_reference_data()


def _seed_reference_data() -> None:
    """参照（マスタ）データの初期投入（設計 §4.1 / §2.6）。

    値域が固定の小さな enum（era / law_type 等）は全件投入する。
    category（全 50 種）と node_kind（XSD の全要素）は、本リビジョンでは
    代表値のみ投入し、完全な集合は後続のリファレンスデータ・リビジョンで補う
    （§11.12.4。category は e-Gov の事項別分類、node_kind は XSD から抽出）。
    """

    def code_label(name: str) -> sa.TableClause:
        return sa.table(name, sa.column("code", sa.Text), sa.column("label", sa.Text))

    op.bulk_insert(
        code_label("era"),
        [
            {"code": "Meiji", "label": "明治"},
            {"code": "Taisho", "label": "大正"},
            {"code": "Showa", "label": "昭和"},
            {"code": "Heisei", "label": "平成"},
            {"code": "Reiwa", "label": "令和"},
        ],
    )

    law_kinds = [
        {"code": "Constitution", "label": "憲法"},
        {"code": "Act", "label": "法律"},
        {"code": "CabinetOrder", "label": "政令"},
        {"code": "ImperialOrder", "label": "勅令"},
        {"code": "MinisterialOrdinance", "label": "府省令"},
        {"code": "Rule", "label": "規則"},
        {"code": "Misc", "label": "その他"},
    ]
    op.bulk_insert(code_label("law_num_type"), law_kinds)
    op.bulk_insert(code_label("law_type"), law_kinds)

    op.bulk_insert(
        code_label("repeal_status"),
        [
            {"code": "None", "label": "現行"},
            {"code": "Repeal", "label": "廃止"},
            {"code": "Expire", "label": "失効"},
            {"code": "Suspend", "label": "停止"},
            {"code": "LossOfEffectiveness", "label": "効力喪失"},
        ],
    )

    op.bulk_insert(
        code_label("current_revision_status"),
        [
            {"code": "CurrentEnforced", "label": "現行施行"},
            {"code": "UnEnforced", "label": "未施行"},
            {"code": "PreviousEnforced", "label": "旧施行"},
            {"code": "Repeal", "label": "廃止"},
        ],
    )

    op.bulk_insert(
        code_label("amendment_type"),
        [
            {"code": "1", "label": "新規制定"},
            {"code": "3", "label": "被改正"},
            {"code": "8", "label": "廃止"},
        ],
    )

    op.bulk_insert(
        code_label("mission"),
        [
            {"code": "New", "label": "新規制定"},
            {"code": "Partial", "label": "一部改正"},
        ],
    )

    # category: 全 50 種のうち代表値のみ（残りは後続リビジョンで補完）
    op.bulk_insert(
        code_label("category"),
        [
            {"code": "001", "label": "憲法"},
            {"code": "050", "label": "外事"},
        ],
    )

    # node_kind: XSD v3 の主要要素（代表集合。全要素は後続リビジョンで補完、§11.12.4）
    node_kind = sa.table(
        "node_kind",
        sa.column("kind", sa.Text),
        sa.column("category", sa.Text),
        sa.column("is_container", sa.Boolean),
    )
    op.bulk_insert(node_kind, _CORE_NODE_KINDS)


def downgrade() -> None:
    """Downgrade schema."""
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('law_xml')
    op.drop_table('law_revision_category')
    op.drop_index('ix_law_node_text_search', table_name='law_node', postgresql_using='gin')
    op.drop_index('ix_law_node_text_plain_bigm', table_name='law_node', postgresql_using='gin', postgresql_ops={'text_plain': 'gin_bigm_ops'})
    op.drop_index('ix_law_node_revision_parent_ordinal', table_name='law_node')
    op.drop_index('ix_law_node_revision_kind_num', table_name='law_node')
    op.drop_index('ix_law_node_path_gist', table_name='law_node', postgresql_using='gist')
    op.drop_index('ix_law_node_attrs', table_name='law_node', postgresql_using='gin', postgresql_ops={'attrs': 'jsonb_path_ops'})
    op.drop_table('law_node')
    op.drop_index('ix_attached_file_sha256', table_name='attached_file')
    op.drop_table('attached_file')
    op.drop_index('ix_law_revision_law_id_enforcement', table_name='law_revision')
    op.drop_index('ix_law_revision_current_status', table_name='law_revision')
    op.drop_table('law_revision')
    op.drop_index('ix_amendment_law_promulgate_date', table_name='amendment_law')
    op.drop_index('ix_amendment_law_linked_law_id', table_name='amendment_law')
    op.drop_table('amendment_law')
    op.drop_index('ix_law_promulgation_date', table_name='law')
    op.drop_index('ix_law_num_components', table_name='law')
    op.drop_table('law')
    op.drop_index('ix_ingest_law_event_run', table_name='ingest_law_event')
    op.drop_table('ingest_law_event')
    op.drop_table('repeal_status')
    op.drop_table('node_kind')
    op.drop_table('mission')
    op.drop_table('law_type')
    op.drop_table('law_num_type')
    op.drop_table('ingest_run')
    op.drop_table('era')
    op.drop_table('current_revision_status')
    op.drop_table('category')
    op.drop_table('amendment_type')
    # ### end Alembic commands ###
