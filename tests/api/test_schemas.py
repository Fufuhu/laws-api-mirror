"""API スキーマのシリアライズ（日付フォーマット・構造）の単体テスト。"""

from __future__ import annotations

from datetime import date

from laws_api_mirror.api.schemas import LawInfo, LawListItem, LawsResponse, RevisionInfo


def test_law_info_serializes_date_as_iso() -> None:
    """promulgation_date は YYYY-MM-DD で出力される。"""
    info = LawInfo(law_id="321CONSTITUTION", promulgation_date=date(1946, 11, 3))
    dumped = info.model_dump(mode="json")
    assert dumped["promulgation_date"] == "1946-11-03"
    assert dumped["law_id"] == "321CONSTITUTION"
    # 未設定メタは null
    assert dumped["law_num"] is None


def test_laws_response_shape() -> None:
    """レスポンスが total_count/count/next_offset/laws の構造を持つ。"""
    item = LawListItem(
        law_info=LawInfo(law_id="X"),
        revision_info=RevisionInfo(law_revision_id="X_r1"),
        current_revision_info=RevisionInfo(law_revision_id="X_r1"),
    )
    resp = LawsResponse(total_count=1, count=1, next_offset=None, laws=[item])
    dumped = resp.model_dump(mode="json")
    assert set(dumped) == {"total_count", "count", "next_offset", "laws"}
    assert dumped["laws"][0]["law_info"]["law_id"] == "X"
    assert dumped["laws"][0]["revision_info"]["law_revision_id"] == "X_r1"
