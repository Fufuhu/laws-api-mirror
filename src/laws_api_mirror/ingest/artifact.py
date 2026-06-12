"""ダウンロード成果物のメタデータ。

docs/design/12-全件ダウンロード.md §12.5 の ``download_artifact`` テーブルに対応する
アプリ側モデル。DB への永続化は後続フェーズの責務とし、本モジュールは取得結果を
表現する Pydantic モデルと、landing zone に置くサイドカー JSON の入出力のみを担う。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel

#: サイドカーメタファイルの拡張子（生 Zip と同じ場所に並べて置く）
META_SUFFIX = ".meta.json"


class DownloadArtifact(BaseModel):
    """1 回の一括ダウンロードで取得した生 Zip の記録（§12.5）。"""

    file_section: int
    category_cd: str | None = None
    update_date: date | None = None
    only_xml: bool
    source_url: str
    object_key: str
    """landing zone 上のキー（§12.4）。"""
    landing_path: str
    """ローカル landing zone 上の絶対パス。"""
    sha256: str
    """取得物の SHA-256（16 進文字列）。同一性判定・冪等スキップに用いる（§12.5 / §13.7）。"""
    byte_size: int
    http_status: int
    fetched_at: datetime
    law_count: int | None = None
    """Zip 展開後に数える法令フォルダ数（§12.5）。ダウンロード段では未確定のため None。"""

    def meta_path(self) -> Path:
        """サイドカーメタ JSON のパス。"""
        return Path(self.landing_path + META_SUFFIX)

    def write_meta(self) -> Path:
        """生 Zip の隣にメタ JSON を書き出す。"""
        path = self.meta_path()
        path.write_text(self.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    @classmethod
    def read_meta(cls, path: Path) -> DownloadArtifact:
        """サイドカーメタ JSON を読み込む。"""
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
