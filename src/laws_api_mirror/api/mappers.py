"""ORM 行 → API スキーマの変換（共有ヘルパ）。"""

from __future__ import annotations

from laws_api_mirror.api.schemas import LawInfo, RevisionInfo
from laws_api_mirror.db.models import Law, LawRevision


def build_law_info(law: Law) -> LawInfo:
    return LawInfo(
        law_type=law.law_type,
        law_id=law.law_id,
        law_num=law.law_num,
        law_num_era=law.law_num_era,
        law_num_year=law.law_num_year,
        law_num_type=law.law_num_type,
        law_num_num=law.law_num_num,
        promulgation_date=law.promulgation_date,
    )


def build_revision_info(revision: LawRevision) -> RevisionInfo:
    return RevisionInfo(
        law_revision_id=revision.law_revision_id,
        law_type=revision.law_type,
        law_title=revision.law_title,
        law_title_kana=revision.law_title_kana,
        abbrev=revision.abbrev,
    )
