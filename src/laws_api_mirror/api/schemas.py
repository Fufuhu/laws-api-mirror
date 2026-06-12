"""API レスポンススキーマ（e-Gov 法令 API v2 互換、設計 §7）。

1st リリースは **インタフェース互換**（フィールド名・型・構造）を維持する方針（§10-9）。
取り込み済みデータで埋められないフィールドは ``null`` を返す。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class LawInfo(BaseModel):
    """法令メタ（履歴非依存、`law` 由来）。"""

    law_type: str | None = None
    law_id: str
    law_num: str | None = None
    law_num_era: str | None = None
    law_num_year: int | None = None
    law_num_type: str | None = None
    law_num_num: str | None = None
    promulgation_date: date | None = None


class RevisionInfo(BaseModel):
    """法令履歴メタ（`law_revision` 由来）。未取得項目は null。"""

    law_revision_id: str
    law_type: str | None = None
    law_title: str | None = None
    law_title_kana: str | None = None
    abbrev: str | None = None
    category: str | None = None
    updated: datetime | None = None
    amendment_promulgate_date: date | None = None
    amendment_enforcement_date: date | None = None
    amendment_enforcement_comment: str | None = None
    amendment_scheduled_enforcement_date: date | None = None
    amendment_law_id: str | None = None
    amendment_law_title: str | None = None
    amendment_law_title_kana: str | None = None
    amendment_law_num: str | None = None
    amendment_type: str | None = None
    repeal_status: str | None = None
    repeal_date: date | None = None
    remain_in_force: bool | None = None
    mission: str | None = None
    current_revision_status: str | None = None


class LawListItem(BaseModel):
    law_info: LawInfo
    revision_info: RevisionInfo
    current_revision_info: RevisionInfo


class LawsResponse(BaseModel):
    """`GET /api/2/laws` のレスポンス。"""

    total_count: int
    count: int
    next_offset: int | None = None
    laws: list[LawListItem]


class LawRevisionsResponse(BaseModel):
    """`GET /api/2/law_revisions/{id}` のレスポンス（法令履歴一覧）。"""

    law_info: LawInfo
    revisions: list[RevisionInfo]


class KeywordSentence(BaseModel):
    """検索ヒットした文（ハイライトタグ付き）。"""

    position: str
    text: str


class KeywordItem(BaseModel):
    law_info: LawInfo
    revision_info: RevisionInfo
    sentences: list[KeywordSentence]


class KeywordResponse(BaseModel):
    """`GET /api/2/keyword` のレスポンス。"""

    total_count: int
    sentence_count: int
    next_offset: int | None = None
    items: list[KeywordItem]


class LawDataResponse(BaseModel):
    """`GET /api/2/law_data/{id}` のレスポンス。

    ``law_full_text`` は ``law_full_text_format`` により JSON ツリー（dict）か
    Base64 XML 文字列（str）。1st リリースで ``attached_files_info`` は null。
    """

    attached_files_info: None = None
    law_info: LawInfo
    revision_info: RevisionInfo
    law_full_text: Any
