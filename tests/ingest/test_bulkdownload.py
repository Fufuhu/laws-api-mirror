"""BulkDownloadRequest（リクエスト仕様）の単体テスト。"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from laws_api_mirror.ingest.bulkdownload import BulkDownloadRequest, FileSection

BASE_URL = "https://laws.e-gov.go.jp/bulkdownload"


def test_all_xml_builds_url_and_object_key() -> None:
    """全件・XML のみ（既定）が、正しいクエリ・URL・landing キーを
    生成することを確認する。"""
    req = BulkDownloadRequest(file_section=FileSection.ALL)
    assert req.query_params() == {"file_section": "1", "only_xml_flag": "true"}
    assert req.build_url(BASE_URL) == f"{BASE_URL}?file_section=1&only_xml_flag=true"
    assert req.object_key(date(2026, 6, 13)) == "raw/bulk/20260613/section1/all_xml.zip"


def test_full_data_omits_only_xml_flag() -> None:
    """全データ取得（only_xml=False）時に only_xml_flag を付与せず、
    キー名が full になることを確認する。"""
    req = BulkDownloadRequest(file_section=FileSection.ALL, only_xml=False)
    assert "only_xml_flag" not in req.query_params()
    assert req.object_key(date(2026, 6, 13)) == "raw/bulk/20260613/section1/all_full.zip"


def test_delta_requires_update_date() -> None:
    """差分（section=3）で update_date 未指定なら検証エラーになることを確認する。"""
    with pytest.raises(ValidationError, match="update_date が必要"):
        BulkDownloadRequest(file_section=FileSection.DELTA)


def test_delta_formats_update_date() -> None:
    """差分で update_date が YYYYMMDD に整形され、クエリと landing キーに
    反映されることを確認する。"""
    req = BulkDownloadRequest(file_section=FileSection.DELTA, update_date=date(2026, 6, 13))
    params = req.query_params()
    assert params["file_section"] == "3"
    assert params["update_date"] == "20260613"
    assert req.object_key(date(2026, 6, 14)) == "raw/bulk/20260614/section3/20260613_xml.zip"


def test_category_requires_category_cd() -> None:
    """分類別（section=2）で category_cd 未指定なら検証エラーになることを確認する。"""
    with pytest.raises(ValidationError, match="category_cd が必要"):
        BulkDownloadRequest(file_section=FileSection.CATEGORY)


def test_category_builds_params() -> None:
    """分類別で category_cd がクエリと landing キーに反映されることを確認する。"""
    req = BulkDownloadRequest(file_section=FileSection.CATEGORY, category_cd="003")
    params = req.query_params()
    assert params["file_section"] == "2"
    assert params["category_cd"] == "003"
    assert req.object_key(date(2026, 6, 13)) == "raw/bulk/20260613/section2/003_xml.zip"


def test_all_rejects_extra_params() -> None:
    """全件（section=1）に update_date 等の余分なパラメータを与えると
    検証エラーになることを確認する。"""
    with pytest.raises(ValidationError, match="指定できません"):
        BulkDownloadRequest(file_section=FileSection.ALL, update_date=date(2026, 6, 13))
