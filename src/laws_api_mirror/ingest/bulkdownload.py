"""e-Gov XML 一括ダウンロード（bulkdownload）のリクエスト仕様。

docs/design/12-全件ダウンロード.md §12.2「`/bulkdownload` エンドポイント仕様」に対応。
URL とクエリパラメータの組み立て、landing zone 上のオブジェクトキー生成を担う。
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum
from urllib.parse import urlencode

from pydantic import BaseModel, model_validator


class FileSection(IntEnum):
    """`file_section` パラメータ（§12.2.1）。"""

    ALL = 1
    """全件（すべての法令データ）。"""
    CATEGORY = 2
    """分類別（``category_cd`` で指定）。"""
    DELTA = 3
    """差分（``update_date`` で指定。提供は過去 3 か月分）。"""


class BulkDownloadRequest(BaseModel):
    """一括ダウンロードの 1 リクエストを表す。

    ``file_section`` に応じた必須パラメータの整合性を生成時に検証する。
    初期ブートストラップ（§13）では ``FileSection.ALL`` を用いる。
    """

    file_section: FileSection
    only_xml: bool = True
    """``True`` で XML のみ（``only_xml_flag=true``）。``False`` で画像・様式を含む全データ。"""
    category_cd: str | None = None
    update_date: date | None = None

    @model_validator(mode="after")
    def _validate_combination(self) -> BulkDownloadRequest:
        if self.file_section is FileSection.ALL:
            if self.category_cd is not None or self.update_date is not None:
                raise ValueError(
                    "file_section=1 (全件) では category_cd / update_date を指定できません"
                )
        elif self.file_section is FileSection.CATEGORY:
            if not self.category_cd:
                raise ValueError("file_section=2 (分類別) には category_cd が必要です")
            if self.update_date is not None:
                raise ValueError("file_section=2 (分類別) で update_date は指定できません")
        elif self.file_section is FileSection.DELTA:
            if self.update_date is None:
                raise ValueError("file_section=3 (差分) には update_date が必要です")
            if self.category_cd is not None:
                raise ValueError("file_section=3 (差分) で category_cd は指定できません")
        return self

    def query_params(self) -> dict[str, str]:
        """e-Gov に渡すクエリパラメータを構築する。

        ``only_xml_flag`` は ``True`` のときのみ付与する（省略＝全データ、§12.2.1）。
        """
        params: dict[str, str] = {"file_section": str(int(self.file_section))}
        if self.category_cd is not None:
            params["category_cd"] = self.category_cd
        if self.update_date is not None:
            params["update_date"] = self.update_date.strftime("%Y%m%d")
        if self.only_xml:
            params["only_xml_flag"] = "true"
        return params

    def build_url(self, base_url: str) -> str:
        """取得先 URL を組み立てる。"""
        return f"{base_url}?{urlencode(self.query_params())}"

    def object_key(self, captured_date: date) -> str:
        """landing zone 上のオブジェクトキー（§12.4）。

        例: ``raw/bulk/20260613/section1/all_xml.zip``
        """
        stamp = captured_date.strftime("%Y%m%d")
        variant = "xml" if self.only_xml else "full"
        if self.file_section is FileSection.ALL:
            name = "all_xml.zip" if self.only_xml else "all_full.zip"
            return f"raw/bulk/{stamp}/section1/{name}"
        if self.file_section is FileSection.CATEGORY:
            return f"raw/bulk/{stamp}/section2/{self.category_cd}_{variant}.zip"
        # DELTA（_validate_combination で update_date の存在は保証済み）
        assert self.update_date is not None
        return f"raw/bulk/{stamp}/section3/{self.update_date.strftime('%Y%m%d')}_{variant}.zip"
